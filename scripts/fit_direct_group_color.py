"""Explore color refinement on the same training-only fragment surfaces.

This follow-up was proposed after inspecting the geometric holdout diagnostic.
It is exploratory, even though no holdout pixels enter its fitting objective.
"""

import os
os.environ.setdefault("OMP_NUM_THREADS","4")
os.environ.setdefault("OPENBLAS_NUM_THREADS","4")

import argparse
import copy
import json
from pathlib import Path

import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree

from register_scans import preprocess,metrics,score,acceptance,save_json
from reconstruction_probe.offline import file_sha256


def read(path):return json.loads(path.read_text(encoding="utf-8"))


def color_metrics(source,target,matrix):
    points=np.asarray(source.points)@matrix[:3,:3].T+matrix[:3,3]
    distances,ids=cKDTree(np.asarray(target.points)).query(points)
    kept=distances<=1.
    if not kept.any():return dict(correspondences_within_1mm=0)
    delta=np.abs(np.asarray(source.colors)[kept]-np.asarray(target.colors)[ids[kept]])*255
    return dict(correspondences_within_1mm=int(kept.sum()),median_rgb_mae_255=float(np.median(delta.mean(1))),
                p90_rgb_mae_255=float(np.percentile(delta.mean(1),90)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared",type=Path,required=True)
    parser.add_argument("--geometric",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();prepared=args.prepared.resolve();geometric=args.geometric.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error("Use a new/empty output directory")
    out.mkdir(parents=True,exist_ok=True)
    previous=read(geometric/"summary.json");training=read(prepared/"training.json")
    paths={row["id_high"]:Path(row["path"]) for row in training["groups"]}
    source=o3d.io.read_point_cloud(str(paths[1]));target=o3d.io.read_point_cloud(str(paths[0]))
    if not source.has_colors() or not target.has_colors():raise ValueError("Training colors required")
    fine_s,_=preprocess(source,.5);fine_t,_=preprocess(target,.5)
    source_m=copy.deepcopy(source).scale(.001,center=(0,0,0));target_m=copy.deepcopy(target).scale(.001,center=(0,0,0))
    levels=[]
    for voxel in [.002,.001,.0005]:
        s,t=source_m.voxel_down_sample(voxel),target_m.voxel_down_sample(voxel)
        for pc in [s,t]:
            pc.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel*2.5,max_nn=50));pc.normalize_normals()
        levels.append((voxel,s,t))
    candidates=[]
    for old in previous["candidates"]:
        row=copy.deepcopy(old);row["training_color_metrics"]=color_metrics(fine_s,fine_t,np.array(row["transform"]))
        candidates.append(row)
    for initial in [row for row in previous["candidates"] if row["label"] in ("direct_best_training","direct_alternative_1")]:
        matrix=np.array(initial["transform"]);matrix[:3,3]*=.001;steps=[];error=None
        for (voxel,s,t),iterations in zip(levels,[50,35,25]):
            try:
                result=o3d.pipelines.registration.registration_colored_icp(s,t,voxel*2,matrix,
                    o3d.pipelines.registration.TransformationEstimationForColoredICP(.968),
                    o3d.pipelines.registration.ICPConvergenceCriteria(relative_fitness=1e-6,relative_rmse=1e-6,max_iteration=iterations))
                matrix=np.array(result.transformation,copy=True)
                steps.append(dict(voxel_m=voxel,max_correspondence_m=voxel*2,max_iterations=iterations,
                    geometric_fitness=float(result.fitness),geometric_inlier_rmse_m=float(result.inlier_rmse)))
            except RuntimeError as exc:
                error=str(exc);break
        if error:
            candidates.append(dict(label="color_failed_from_"+initial["label"],transform=initial["transform"],color_fit_error=error,steps=steps,
                selection="Failed color refinement; unchanged initial transform retained for diagnostics"))
            continue
        matrix[:3,3]*=1000;values=metrics(fine_s,fine_t,matrix,[1.,2.5,5.]);passed,checks=acceptance(values,matrix,[1.,2.5,5.])
        label="colored_from_best" if initial["label"]=="direct_best_training" else "colored_from_alternative_1"
        candidates.append(dict(label=label,transform=matrix.tolist(),initial_label=initial["label"],steps=steps,
            training_metrics=values,training_score=score(values,[1.,2.5,5.]),training_color_metrics=color_metrics(fine_s,fine_t,matrix),
            passes_original_geometric_gate=passed,geometric_gate_checks=checks,
            selection="Exploratory color family; training-only refinement; no heldout reranking"))
    for row in candidates:
        aligned=copy.deepcopy(source).transform(np.array(row["transform"]));path=out/(row["label"]+"-group-1-aligned-mm.ply")
        o3d.io.write_point_cloud(str(path),aligned);row["aligned_path"]=str(path)
    report=dict(reference_group=0,moving_group=1,prepared_path=str(prepared),external_reference_geometry_used=False,
        heldout_depths_used_for_fitting=False,exploratory_followup_after_viewing_geometric_holdout=True,
        geometry_fitting_unit="metres; translations converted back to mm",lambda_geometric=.968,
        candidates=candidates,input_sha256={str(p):file_sha256(p) for p in [prepared/"split.json",prepared/"training.json",geometric/"summary.json",paths[0],paths[1]]},
        method_source="https://www.open3d.org/docs/latest/tutorial/pipelines/colored_pointcloud_registration.html",
        limitations=["Color does not necessarily identify physical surface points under exposure, lighting, reflection or low texture.",
          "The color experiment was added after viewing the geometric holdout results; subsequent checks are exploratory, not an untouched test.",
          "Existing candidates keep their labels; no winner is selected using heldout scores.",
          "Geometry and color training metrics remain in-sample descriptive diagnostics."])
    save_json(out/"summary.json",report)
    print(json.dumps(dict(candidates=[{k:v for k,v in row.items() if k in ("label","training_score","training_color_metrics","color_fit_error")} for row in candidates])),flush=True)


if __name__=="__main__":main()

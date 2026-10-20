"""Fit fragment alignment from training surfaces alone, retaining different poses."""

import os
os.environ.setdefault("OMP_NUM_THREADS","4")
os.environ.setdefault("OPENBLAS_NUM_THREADS","4")

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d

from register_scans import preprocess,pca_transforms,global_candidates,refine,metrics,score,acceptance,save_json
from reconstruction_probe.candidate_selection import distinct_hypothesis_indices,hypothesis_rms_displacement
from reconstruction_probe.offline import file_sha256


def read(path):return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();prepared=args.prepared.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error("Use a new/empty output directory")
    out.mkdir(parents=True,exist_ok=True)
    training=read(prepared/"training.json")
    if training["split_sha256"]!=file_sha256(prepared/"split.json"):raise ValueError("Split provenance changed")
    paths={row["id_high"]:Path(row["path"]) for row in training["groups"]}
    source=o3d.io.read_point_cloud(str(paths[1]));target=o3d.io.read_point_cloud(str(paths[0]))
    coarse_s,_=preprocess(source,2.);coarse_t,_=preprocess(target,2.)
    fine_s,_=preprocess(source,.5);fine_t,_=preprocess(target,.5)
    probes=np.asarray(coarse_s.points)[::max(1,len(coarse_s.points)//128)]
    thresholds=[1.,2.5,5.]
    center=np.eye(4);center[:3,3]=coarse_t.get_center()-coarse_s.get_center()
    initial=[("saved_relative_identity",np.eye(4),{}),("centroid",center,{})]
    initial += [(name,matrix,{}) for name,matrix in pca_transforms(coarse_s,coarse_t)]
    initial += global_candidates(coarse_s,coarse_t,2.)
    rows=[]
    for name,matrix,info in initial:
        fitted,details=refine(coarse_s,coarse_t,matrix,[7.,4.],iterations=30)
        values=metrics(coarse_s,coarse_t,fitted,thresholds)
        rows.append(dict(method=name,transform=fitted.tolist(),coarse_score=score(values,thresholds),coarse_metrics=values,**info,**details))
    rows.sort(key=lambda row:row["coarse_score"],reverse=True)
    chosen=distinct_hypothesis_indices([np.array(row["transform"]) for row in rows],probes,maximum=6,minimum_rms=2.)
    fine_rows=[]
    for i in chosen:
        row=rows[i]
        fitted,details=refine(fine_s,fine_t,np.array(row["transform"]),[3.,1.5,1.],iterations=55)
        values=metrics(fine_s,fine_t,fitted,thresholds)
        fine_rows.append(dict(method=row["method"],transform=fitted.tolist(),training_metrics=values,training_score=score(values,thresholds),**details))
    fine_rows.sort(key=lambda row:row["training_score"],reverse=True)
    chosen_final=distinct_hypothesis_indices([np.array(row["transform"]) for row in fine_rows],probes,maximum=3,minimum_rms=2.)
    candidates=[dict(label="saved_relative_identity",transform=np.eye(4).tolist(),selection="Unchanged saved-pose relation; not optimized")]
    for rank,i in enumerate(chosen_final):
        row=fine_rows[i];matrix=np.array(row["transform"]);accepted,checks=acceptance(row["training_metrics"],matrix,thresholds)
        candidate=dict(label="direct_best_training" if rank==0 else f"direct_alternative_{rank}",**row,
            passes_original_geometric_gate=accepted,geometric_gate_checks=checks,selection="Training-only ranking; heldout depths not read")
        candidates.append(candidate)
    for row in candidates:
        aligned=copy.deepcopy(source).transform(np.array(row["transform"]))
        path=out/(row["label"]+"-group-1-aligned-mm.ply");o3d.io.write_point_cloud(str(path),aligned)
        row["aligned_path"]=str(path)
    report=dict(reference_group=0,moving_group=1,transform_direction="Original group-1 coordinates to original group-0 coordinates, in mm",
        external_reference_geometry_used=False,heldout_depths_used_for_fitting=False,
        prepared_path=str(prepared),distance_thresholds_mm=thresholds,coarse_trials=len(rows),coarse_diverse_refined=len(chosen),
        diversity_rule="Training source probe RMS displacement >=2 mm; rank by training geometry only",
        input_sha256={str(p):file_sha256(p) for p in [prepared/"split.json",prepared/"training.json",paths[0],paths[1]]},
        candidates=candidates,coarse_candidates=rows,fine_candidates=fine_rows,
        limitations=["Symmetric, partial and thin cup surfaces can admit several plausible rigid alignments.",
          "Training scores and geometric gates are not held-out validation or physical accuracy.",
          "The original ROI was proposed previously from all source observations.",
          "No source pose or main model is overwritten; candidates are not automatically accepted."])
    save_json(out/"summary.json",report)
    command=[sys.executable,"scripts/build_reconstruction_review.py","--unit","mm","--up-axis","x","--invert-up","--allow-overlay","--max-points","30000","--out",str(out/"review.html"),"--notes","同一扫描两片段，仅用训练帧表面直接配准；未借助其他扫描参考。多个候选只按训练几何排序，留出深度尚未用于选择。各候选为同一移动片段的不同位置，建议逐项开启。"]
    command += ["--cloud","固定片段 0="+str(paths[0])]
    for row in candidates:command += ["--cloud",row["label"]+"="+row["aligned_path"]]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    print(json.dumps({k:v for k,v in report.items() if k not in ["coarse_candidates","fine_candidates","input_sha256","limitations"]}),flush=True)


if __name__=="__main__":main()

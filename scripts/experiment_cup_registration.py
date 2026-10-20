"""Register independent cup surfaces and ROI candidates, preserving all inputs.

The visually similar cup samples are an object-identity hypothesis. Geometric
gates decide inclusion in an experimental combined surface cloud, not truth.
"""

import os
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

import argparse
import copy
import json
import re
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d

from register_scans import preprocess, pca_transforms, global_candidates, refine, metrics, score, acceptance, save_json
from reconstruction_probe.offline import file_sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sources", nargs="+", help="Optional unique_id=path.ply sources; coordinates in mm")
    args = parser.parse_args()
    root, output = args.study.resolve(), args.out.resolve()
    if output.exists() and any(output.iterdir()): parser.error("Use a new/empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    reference_id = "scan_20261018131019"
    target_path = root/"reconstruction"/reference_id/"tsdf_pointcloud_mm.ply"
    target = o3d.io.read_point_cloud(str(target_path))
    coarse_t, _ = preprocess(target, 2.)
    fine_t, _ = preprocess(target, .5)
    reports, display = [], [("参考 13:10:19", target_path)]
    combined = copy.deepcopy(target)
    sources = [("scan_20261018131127", root/"reconstruction/scan_20261018131127/tsdf_pointcloud_mm.ply"),
        *[(key,root/"experiments/cup-roi/candidate"/key/"tsdf_pointcloud_mm.ply") for key in ["scan_20261018131222","scan_20261018131359"]]]
    if args.sources:
        sources=[]
        for item in args.sources:
            key,separator,path=item.partition("=")
            if not separator or not re.fullmatch(r"[A-Za-z0-9_-]+",key) or any(key==previous for previous,_ in sources):
                parser.error("Sources must have unique labels and a PLY path")
            sources.append((key,Path(path).resolve()))
    for key, path in sources:
        source = o3d.io.read_point_cloud(str(path))
        coarse_s, _ = preprocess(source, 2.)
        fine_s, _ = preprocess(source, .5)
        thresholds = [1.,2.5,5.]
        initial = [(name,t,{}) for name,t in pca_transforms(coarse_s,coarse_t)]
        initial += global_candidates(coarse_s,coarse_t,2.)
        trials = []
        for name, t, info in initial:
            transform, icp = refine(coarse_s,coarse_t,t,[7.,4.],iterations=30)
            m = metrics(coarse_s,coarse_t,transform,thresholds)
            trials.append({"method":name,"transform":transform.tolist(),"coarse_score":score(m,thresholds),**info})
        trials.sort(key=lambda row:row["coarse_score"],reverse=True)
        for row in trials[:6]:
            transform, icp = refine(fine_s,fine_t,np.array(row["transform"]),[3.,1.5,1.],iterations=55)
            m = metrics(fine_s,fine_t,transform,thresholds)
            row.update(transform=transform.tolist(),metrics=m,score=score(m,thresholds),**icp)
        finalists = sorted([row for row in trials if "score" in row],key=lambda row:row["score"],reverse=True)
        best = finalists[0];transform = np.array(best["transform"])
        accepted, checks = acceptance(best["metrics"],transform,thresholds)
        aligned = copy.deepcopy(source).transform(transform)
        aligned_path = output/(key+"-aligned-candidate-mm.ply")
        o3d.io.write_point_cloud(str(aligned_path),aligned)
        display.append((key.removeprefix("scan_")+(' · 通过几何门槛' if accepted else ' · 未通过，单独审阅'),aligned_path))
        if accepted:combined += aligned
        report = {"scan_id":key,"reference_scan_id":reference_id,"unit":"mm",
            "identity_status":"visually similar green cup; not independently confirmed",
            "source_sha256":file_sha256(path),"reference_sha256":file_sha256(target_path),
            "source_path":str(path),"reference_path":str(target_path),
            "accepted_for_experimental_combination":accepted,"checks":checks,
            "transform_source_scan_to_reference_scan":transform.tolist(),"metrics":best["metrics"],
            "trials":trials,"limitations":["Geometric agreement does not establish object identity or physical accuracy.",
                "Registration and evaluation use the same underlying surface observations; scores are not held-out validation.",
                "Symmetric cup regions can admit ambiguous alignments; manual point/region review remains necessary.",
                "ROI inputs are cropped and use finer effective TSDF voxels than original failed-scan baselines."]}
        save_json(output/(key+"-registration.json"),report)
        reports.append(report)
        print(json.dumps({"scan_id":key,"accepted":accepted,"source_to_reference":best["metrics"]["source_to_reference"],"reference_to_source":best["metrics"]["reference_to_source"]}),flush=True)
    combined = combined.voxel_down_sample(.6)
    combined_path = output/"combined-accepted-surface-cloud-mm.ply"
    o3d.io.write_point_cloud(str(combined_path),combined)
    save_json(output/"summary.json",{"reference_scan_id":reference_id,"unit":"mm","combination":"voxel averaging of accepted aligned per-scan TSDF surface samples; not multi-scan depth TSDF",
        "combination_status":"additional_sources_passed" if any(r["accepted_for_experimental_combination"] for r in reports) else "no_additional_sources_passed_the_original_geometric_gate",
        "included_sources":[r["scan_id"] for r in reports if r["accepted_for_experimental_combination"]],
        "combined_points":len(combined.points),"registrations":[{k:v for k,v in r.items() if k!="trials"} for r in reports]})
    command = [sys.executable,"scripts/build_reconstruction_review.py","--unit","mm","--up-axis","x","--invert-up","--allow-overlay","--max-points","25000","--out",str(output/"review.html"),"--notes","不同扫描的表面配准候选，参考为 13:10:19。仅通过几何门槛的来源纳入组合点云；仍需检查杯柄、口沿和内壁。自动门槛不是身份或精度证明。组合是表面点体素整合，不是多工程深度重新 TSDF。"]
    combined_label = "通过门槛后的组合表面点云" if any(r["accepted_for_experimental_combination"] for r in reports) else "无额外来源通过 · 仅参考重采样"
    for label,path in display+[(combined_label,combined_path)]:command += ["--cloud",label+"="+str(path)]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()

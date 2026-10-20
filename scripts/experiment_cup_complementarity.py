"""Reciprocal depth evidence and an explicitly unpromoted two-surface candidate."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d

from reconstruct_scans import clean_depth_edges,optical_to_pose_axes,write_json
from reconstruction_probe.visibility import depth_observation_deltas


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();root=args.study.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error("Use a new/empty output directory")
    out.mkdir(parents=True,exist_ok=True)
    reg=root/"experiments/cup-registration";key="scan_20261018131127"
    T=np.array(json.loads((reg/(key+"-registration.json")).read_text(encoding="utf-8"))["transform_source_scan_to_reference_scan"])
    index=json.loads((root/"decoded"/key/"index.json").read_text(encoding="utf-8"))
    frames=[f for f in index["frames"] if f.get("optimized_pose_status")=="parsed"];selected=frames[::8]
    if selected[-1]["id"]!=frames[-1]["id"]:selected.append(frames[-1])
    views=[]
    for f in selected:
        folder=root/"decoded"/key/f"frame_{f['id']:010d}"
        with np.load(folder/"frame.npz",allow_pickle=False) as d:depth=d["depth_mm"]
        depth,_=clean_depth_edges(depth,3.)
        views.append((np.load(folder/"pose_optimized.npy",allow_pickle=False),depth))
    original=root/"reconstruction/scan_20261018131019/tsdf_pointcloud_mm.ply"
    flipped=root/"reconstruction"/key/"tsdf_pointcloud_mm.ply"
    results=[]
    for label,path,transform in [("13:11 self-control",flipped,False),("13:10 surface in 13:11 frame",original,True)]:
        cloud=o3d.io.read_point_cloud(str(path));all_xyz=np.asarray(cloud.points)
        ids=np.linspace(0,len(all_xyz)-1,min(20000,len(all_xyz)),dtype=int);xyz=all_xyz[ids]
        if transform:xyz=(xyz-T[:3,3])@T[:3,:3]
        support=np.zeros((2,len(xyz)),np.uint16);conflict=support.copy()
        for pose,depth in views:
            chosen,delta=depth_observation_deltas(xyz,pose,depth,index["intrinsics"]["Pl"],optical_to_pose_axes(index))
            for i,t in enumerate([2.,4.]):
                support[i,chosen[np.abs(delta)<=t]]+=1;conflict[i,chosen[delta>t]]+=1
        results.append({"query":label,"sample_points":len(xyz),"sample_reference_views":len(views),
            "thresholds":[{"tolerance_mm":t,"points_with_at_least_two_supports":int((support[i]>=2).sum()),
                "points_with_at_least_three_conflicts":int((conflict[i]>=3).sum())} for i,t in enumerate([2.,4.])]})
    reference=o3d.io.read_point_cloud(str(original));source=o3d.io.read_point_cloud(str(reg/(key+"-aligned-candidate-mm.ply")))
    candidate=(reference+source).voxel_down_sample(.6);path=out/"two-surface-candidate-mm.ply";o3d.io.write_point_cloud(str(path),candidate)
    report={"status":"exploratory_only_not_promoted","scans":["scan_20261018131019",key],"unit":"mm","candidate_points":len(candidate.points),
        "transform_source_1311_to_reference_1310":T.tolist(),"reciprocal_depth_checks":results,
        "forward_depth_checks":"../cup-visibility/summary.json",
        "interpretation":"Low overlap and repeated free-space conflict are distinct. Part of the unmatched surface may be complementary; manual region review is still needed.",
        "limitations":["Same pose and geometry sources enter fitting and evidence; no independent truth.","The original strict geometric gate did not accept this pair.",
            "Self-control on 13:11 has its own conflicts, showing threshold sensitivity and saved-data inconsistency.","Candidate combines per-scan surface samples, not all-depth multi-scan TSDF.","No unseen geometry is invented or certified."]}
    write_json(out/"summary.json",report)
    command=[sys.executable,"scripts/build_reconstruction_review.py","--unit","mm","--up-axis","x","--invert-up","--allow-overlay","--max-points","30000","--out",str(out/"review.html"),"--notes","探索候选：13:10 与翻面 13:11。完整重叠门槛未通过，深度检查提示部分差异可能是未共同观察的表面。候选只供人工检查，未纳入主结果。组合为表面点体素整合。"]
    for label,p in [("13:10 原表面",original),("13:11 已对齐候选",reg/(key+"-aligned-candidate-mm.ply")),("两表面组合探索候选",path)]:command += ["--cloud",label+"="+str(p)]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    print(json.dumps(report),flush=True)


if __name__=="__main__":main()

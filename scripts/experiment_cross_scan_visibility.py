"""Inspect candidate aligned surfaces against saved reference depth images.

Counts describe sampled-view evidence, not independent confidence or accuracy.
Depth is checked after discontinuity filtering; unseen and occluded points are
not treated as conflicts. Reference TSDF is included as an internal control.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d

from reconstruct_scans import clean_depth_edges, optical_to_pose_axes, write_json
from reconstruction_probe.visibility import depth_observation_deltas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--points", type=int, default=20000)
    parser.add_argument("--frame-stride", type=int, default=8)
    args = parser.parse_args()
    if args.points<100 or args.frame_stride<1:parser.error("Positive sampling parameters required")
    root, output = args.study.resolve(), args.out.resolve()
    if output.exists() and any(output.iterdir()):parser.error("Use a new/empty output directory")
    output.mkdir(parents=True,exist_ok=True)
    reference_id = "scan_20261018131019"
    decoded = root/"decoded"/reference_id
    index = json.loads((decoded/"index.json").read_text(encoding="utf-8"))
    calibration=index["intrinsics"]["Pl"];K=np.array(calibration["K"]);signs=optical_to_pose_axes(index)
    saved_frames = [f for f in index["frames"] if (decoded/f"frame_{f['id']:010d}"/"pose_optimized.npy").is_file()]
    selected=saved_frames[::args.frame_stride]
    if selected[-1]["id"]!=saved_frames[-1]["id"]:selected.append(saved_frames[-1])
    views=[]
    for frame in selected:
        folder=decoded/f"frame_{frame['id']:010d}"
        with np.load(folder/"frame.npz",allow_pickle=False) as saved:depth=saved["depth_mm"]
        depth,_=clean_depth_edges(depth,3.)
        views.append((frame["id"],np.load(folder/"pose_optimized.npy",allow_pickle=False),depth))
    registration=root/"experiments/cup-registration"
    sources=[("reference_tsdf_control",root/"reconstruction"/reference_id/"tsdf_pointcloud_mm.ply")]
    sources += [(key,registration/(key+"-aligned-candidate-mm.ply")) for key in ["scan_20261018131127","scan_20261018131222","scan_20261018131359"]]
    results,clouds=[],[]
    colors=np.array([[85,200,126],[186,108,226],[244,94,96],[130,144,160]],float)/255
    for key,path in sources:
        cloud=o3d.io.read_point_cloud(str(path));all_xyz=np.asarray(cloud.points)
        ids=np.linspace(0,len(all_xyz)-1,min(args.points,len(all_xyz)),dtype=np.int64);xyz=all_xyz[ids]
        support=np.zeros((2,len(xyz)),np.uint16);conflict=support.copy();occluded=support.copy();observed=np.zeros(len(xyz),np.uint16)
        for rid,pose,depth in views:
            chosen,delta=depth_observation_deltas(xyz,pose,depth,calibration,signs)
            observed[chosen]+=1
            for i,tolerance in enumerate([2.,4.]):
                support[i,chosen[np.abs(delta)<=tolerance]]+=1
                conflict[i,chosen[delta>tolerance]]+=1
                occluded[i,chosen[delta < -tolerance]]+=1
        classes=np.full(len(xyz),3,np.uint8)
        supported=support[0]>=2;opposed=conflict[0]>=3
        classes[supported&~opposed]=0;classes[supported&opposed]=1;classes[~supported&opposed]=2
        classifications={name:int((classes==i).sum()) for i,name in enumerate(["supported_without_repeated_conflict","mixed_support_and_conflict","repeated_conflict_without_two_supports","inconclusive"])}
        row={"source":key,"sampled_surface_points":len(xyz),"reference_scan_id":reference_id,"sampled_reference_views":len(views),"view_ids":[v[0] for v in views],
            "class_rule":"2mm tolerance; >=2 support views; >=3 conflict views; four classes retain mixed evidence",
            "classes_at_2mm":classifications,"threshold_checks":[],
            "no_valid_projected_depth":int((observed==0).sum())}
        for i,tolerance in enumerate([2.,4.]):
            row["threshold_checks"].append({"tolerance_mm":tolerance,"points_with_two_or_more_support_views":int((support[i]>=2).sum()),
                "points_with_three_or_more_free_space_conflicts":int((conflict[i]>=3).sum()),
                "points_with_three_or_more_occluded_views":int((occluded[i]>=3).sum())})
        np.savez_compressed(output/(key+"-evidence.npz"),source_point_indices=ids,xyz_reference_mm=xyz,support_counts=support,
            free_space_conflict_counts=conflict,occluded_counts=occluded,observed_counts=observed,classes_at_2mm=classes)
        visual=o3d.geometry.PointCloud();visual.points=o3d.utility.Vector3dVector(xyz);visual.colors=o3d.utility.Vector3dVector(colors[classes])
        out=output/(key+"-evidence-mm.ply");o3d.io.write_point_cloud(str(out),visual)
        clouds.append((key,out));results.append(row);print(json.dumps(row),flush=True)
    write_json(output/"summary.json",{"method":"Reproject candidate surface points into saved reference depth views; classify signed optical-Z differences",
        "positive_delta":"Reference depth farther than candidate point: possible free-space conflict",
        "negative_delta":"Reference surface nearer: candidate may be occluded, not a contradiction",
        "sampling":{"points_per_cloud":args.points,"reference_frame_stride":args.frame_stride},
        "results":results,"limitations":["Depth, poses, alignment and TSDF are algorithm outputs; no independent physical truth is used.",
            "Views are correlated. View counts are descriptive and not probability or confidence.",
            "Pixel rounding, depth edges, calibration errors and pose uncertainty can cause apparent conflicts.",
            "Missing/occluded observations do not prove a point is correct; conflicts do not prove which source is wrong.",
            "This evidence does not automatically accept registration or change any pose/selection."]})
    command=[sys.executable,"scripts/build_reconstruction_review.py","--unit","mm","--up-axis","x","--invert-up","--max-points",str(args.points),"--allow-overlay","--out",str(output/"review.html"),"--notes","颜色为深度观测证据：绿=至少两视图支持且无重复冲突；紫=支持与冲突并存；红=重复冲突且不足两次支持；灰=未定。阈值 2mm，重复冲突至少三视图。遮挡不算冲突。切换单个对象并用自动着色查看；叠加模式会按对象着色。此证据不自动修改配准。"]
    for label,path in clouds:command += ["--cloud",label+"="+str(path)]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()

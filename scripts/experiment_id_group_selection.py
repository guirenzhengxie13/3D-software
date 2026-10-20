"""Reconstruct saved ID groups separately without changing their pose values."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d

from reconstruct_scans import reconstruct,optical_to_pose_axes,clean_depth_edges,write_json
from experiment_color_seeded_roi import optical_points
from reconstruction_probe.visibility import depth_observation_deltas


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();root=args.study.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error("Use a new/empty output directory")
    out.mkdir(parents=True,exist_ok=True)
    key="scan_20261018131359";scan=root/"decoded"/key;index=json.loads((scan/"index.json").read_text(encoding="utf-8"))
    selection=json.loads((root/"experiments/cup-roi"/(key+"-selection.json")).read_text(encoding="utf-8"))
    lower,upper=np.array(selection["bounds_min_mm"]),np.array(selection["bounds_max_mm"])
    calibration=index["intrinsics"]["Pl"];signs=optical_to_pose_axes(index)
    groups={}
    for f in index["frames"]:
        p=scan/f"frame_{f['id']:010d}"/"pose_optimized.npy"
        if p.exists():groups.setdefault(f["id"]>>32,{})[f["id"]]=np.load(p,allow_pickle=False)
    def selected_depth(depth,pose):
        ids,xyz=optical_points(depth,calibration);world=(xyz*signs)@pose[:3,:3].T+pose[:3,3]
        inside=np.all((world>=lower)&(world<=upper),axis=1);result=depth.copy();result.ravel()[ids[~inside]]=0
        return result,int((~inside).sum())
    ref=root/"decoded/scan_20261018131019";ri=json.loads((ref/"index.json").read_text(encoding="utf-8"));views=[]
    selected=ri["frames"][::8]
    if selected[-1]["id"]!=ri["frames"][-1]["id"]:selected.append(ri["frames"][-1])
    for f in selected:
        folder=ref/f"frame_{f['id']:010d}"
        with np.load(folder/"frame.npz",allow_pickle=False) as saved:depth=saved["depth_mm"]
        depth,_=clean_depth_edges(depth,3.);views.append((np.load(folder/"pose_optimized.npy",allow_pickle=False),depth))
    T=np.array(json.loads((root/"experiments/cup-registration"/(key+"-registration.json")).read_text(encoding="utf-8"))["transform_source_scan_to_reference_scan"])
    rows=[];clouds=[("两组原 ROI 结果",root/"experiments/cup-roi/candidate"/key/"tsdf_pointcloud_mm.ply")]
    for group,poses in sorted(groups.items()):
        group_root=out/f"id_high_{group}"
        report=reconstruct(scan,group_root,.6,2.4,3.,1,True,pose_overrides=poses,depth_filter=selected_depth,
            evaluate_vendor=False,bounds_override_mm=(lower,upper),reconstruction_note=f"Selection only: ID high word {group}; original optimized poses unchanged; same box and voxel grid as the two-group ROI baseline.")
        path=group_root/key/"tsdf_pointcloud_mm.ply";cloud=o3d.io.read_point_cloud(str(path));points=np.asarray(cloud.points)
        ids=np.linspace(0,len(points)-1,min(20000,len(points)),dtype=int);xyz=points[ids]@T[:3,:3].T+T[:3,3]
        support=np.zeros(len(xyz),int);conflict=support.copy()
        for pose,depth in views:
            chosen,delta=depth_observation_deltas(xyz,pose,depth,ri["intrinsics"]["Pl"],optical_to_pose_axes(ri))
            support[chosen[np.abs(delta)<=2]]+=1;conflict[chosen[delta>2]]+=1
        row={"id_high_word":group,"frame_ids":sorted(poses),"frames":len(poses),"quality":report["quality"],"voxel_mm":report["voxel_mm"],
            "same_original_pose_values":True,"sampled_surface_points":len(xyz),"depth_check_tolerance_mm":2.,
            "two_or_more_reference_depth_supports":int((support>=2).sum()),"three_or_more_reference_free_space_conflicts":int((conflict>=3).sum())}
        rows.append(row);clouds.append((f"仅 ID 高位组 {group} · {len(poses)} 帧",path))
    write_json(out/"summary.json",{"scan_id":key,"groups":rows,"cross_scan_transform":"Same pre-existing whole-scan candidate transform used for both groups; not refitted per group.",
        "limitations":["ID high word is a grouping key of unknown vendor semantics, not a decoded tracking status.","All pose values are unchanged; only frame participation is selected.",
            "Groups have different observation counts; point density and support may differ for that reason.","Visibility uses vendor-derived depths and an estimated cross-scan transform, not independent truth.","A weaker group may still contain complementary real surfaces; no automatic deletion or main-result promotion."]})
    cmd=[sys.executable,"scripts/build_reconstruction_review.py","--unit","mm","--up-axis","x","--invert-up","--allow-overlay","--max-points","30000","--out",str(out/"review.html"),"--notes","分组只改变参与帧，未修改位姿、空间盒或实际体素。ID 高位的厂商语义未确认。不同组的观测数量不同，不能仅据点数或单项残差删除整组。"]
    for label,path in clouds:cmd += ["--cloud",label+"="+str(path)]
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)


if __name__=="__main__":main()

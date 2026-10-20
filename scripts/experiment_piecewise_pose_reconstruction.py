"""Compare whole-scan and per-ID-group rigid alignment on identical depths.

Both use the same original ROI pixel selection, Tensor TSDF settings and frame
IDs. The group transforms are fitted to another reconstructed scan, so this
is explicitly reference-assisted research, not independent pose recovery.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d

from reconstruct_scans import reconstruct,optical_to_pose_axes,clean_depth_edges,write_json
from experiment_color_seeded_roi import optical_points
from reconstruction_probe.visibility import depth_observation_deltas


def read(path):return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();root=args.study.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error("Use a new/empty output directory")
    out.mkdir(parents=True,exist_ok=True)
    key="scan_20261018131359";scan=root/"decoded"/key;index=read(scan/"index.json")
    selection=read(root/"experiments/cup-roi"/(key+"-selection.json"));lower=np.array(selection["bounds_min_mm"]);upper=np.array(selection["bounds_max_mm"])
    whole=np.array(read(root/"experiments/cup-registration"/(key+"-registration.json"))["transform_source_scan_to_reference_scan"])
    group_transforms={g:np.array(read(root/"experiments/cup-id-registration"/(f"group_{g}-registration.json"))["transform_source_scan_to_reference_scan"]) for g in [0,1]}
    original={f["id"]:np.load(scan/f"frame_{f['id']:010d}"/"pose_optimized.npy",allow_pickle=False) for f in index["frames"]}
    ref=root/"decoded/scan_20261018131019";reference=read(ref/"index.json");selected=reference["frames"][::8]
    if selected[-1]["id"]!=reference["frames"][-1]["id"]:selected.append(reference["frames"][-1])
    views=[]
    for f in selected:
        folder=ref/f"frame_{f['id']:010d}"
        with np.load(folder/"frame.npz",allow_pickle=False) as saved:depth=saved["depth_mm"]
        depth,_=clean_depth_edges(depth,3.);views.append((np.load(folder/"pose_optimized.npy",allow_pickle=False),depth))
    summaries=[];clouds=[];calibration=index["intrinsics"]["Pl"];signs=optical_to_pose_axes(index)
    for stage in ["whole_scan_control","piecewise_candidate"]:
        poses={rid:(whole if stage=="whole_scan_control" else group_transforms[rid>>32])@pose for rid,pose in original.items()}
        lookup={}
        for rid,matrix in poses.items():
            value=matrix.astype("<f8").tobytes()
            if value in lookup and not np.array_equal(lookup[value],original[rid]):raise ValueError("Ambiguous pose key for fixed original selection")
            lookup[value]=original[rid]
        selection_digest=hashlib.sha256()
        def fixed_original_selection(depth,updated_pose):
            source_pose=lookup[np.asarray(updated_pose,dtype="<f8").tobytes()]
            ids,xyz=optical_points(depth,calibration);world=(xyz*signs)@source_pose[:3,:3].T+source_pose[:3,3]
            selected=np.all((world>=lower)&(world<=upper),axis=1)
            result=depth.copy();result.ravel()[ids[~selected]]=0
            selection_digest.update(result.astype("<f4").tobytes())
            return result,int((~selected).sum())
        report=reconstruct(scan,out/stage,.6,2.4,3.,1,True,pose_overrides=poses,depth_filter=fixed_original_selection,
            evaluate_vendor=False,coordinate_frame="reference_scan_20261018131019_mm",
            reconstruction_note=f"Reference-assisted {stage}: identical original ROI pixels; only group alignment differs; no official output geometry used.",
            tsdf_backend="tensor",tsdf_weight_threshold=3.)
        path=out/stage/key/"tsdf_pointcloud_mm.ply";cloud=o3d.io.read_point_cloud(str(path));xyz=np.asarray(cloud.points)
        chosen=np.linspace(0,len(xyz)-1,min(20000,len(xyz)),dtype=int);xyz=xyz[chosen]
        support=np.zeros(len(xyz),np.uint16);conflict=support.copy()
        for pose,depth in views:
            ids,delta=depth_observation_deltas(xyz,pose,depth,reference["intrinsics"]["Pl"],optical_to_pose_axes(reference))
            support[ids[np.abs(delta)<=2.]]+=1;conflict[ids[delta>2.]]+=1
        summaries.append({"stage":stage,"integrated_frames":report["integrated_frames"],"input_valid_pixels":report["input_valid_pixels"],
            "selection_array_sha256":selection_digest.hexdigest(),
            "selected_pixels_omitted":report["depth_selection_pixels_omitted"],"voxel_mm":report["voxel_mm"],"quality":report["quality"],
            "sampled_surface_points":len(xyz),"two_or_more_reference_depth_supports":int((support>=2).sum()),
            "three_or_more_reference_depth_conflicts":int((conflict>=3).sum())})
        np.savez_compressed(out/(stage+"-poses.npz"),**{f"pose_{rid}":matrix for rid,matrix in poses.items()})
        clouds.append((stage,path))
    identical=all(summaries[0][k]==summaries[1][k] for k in ["integrated_frames","input_valid_pixels","selected_pixels_omitted","voxel_mm","selection_array_sha256"])
    report={"status":"exploratory_only_not_promoted","scan_id":key,"same_input_frames_pixels_and_voxel":identical,
        "original_roi_selection_mm":{"min":lower.tolist(),"max":upper.tolist(),"frame":"original scan_20261018131359"},
        "whole_scan_transform":whole.tolist(),"group_transforms":{str(g):v.tolist() for g,v in group_transforms.items()},"results":summaries,
        "limitations":["Target reconstructed geometry fits the group transforms and its saved depths evaluate them; this is not held-out or physical accuracy validation.",
            "A rigid transform per ID group cannot repair nonrigid distortion or tracking drift within the group.",
            "Original ROI selection may exclude real parts, unchanged in both arms.","Frame-group identity and physical flipping are hypotheses, not decoded vendor semantics.",
            "No original pose files or main results are overwritten."]}
    write_json(out/"summary.json",report)
    cmd=[sys.executable,"scripts/build_reconstruction_review.py","--unit","mm","--up-axis","x","--invert-up","--allow-overlay","--max-points","35000","--out",str(out/"review.html"),"--notes","相同 358 帧、相同原 ROI 像素和固定 0.6 mm 稀疏 TSDF。对照使用整扫描统一变换，候选按两个 ID 组分别对齐。变换借助另一份自研表面拟合，属于参考辅助实验；未纳入主结果。"]
    for label,path in clouds:cmd += ["--cloud",label+"="+str(path)]
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if not identical:raise RuntimeError("Paired inputs differ")


if __name__=="__main__":main()

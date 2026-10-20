"""Study a reviewable color-seeded object box on two failed cup scans.

This is a cohort-specific proposal, not a general segmentation algorithm.
RGB only proposes a box; all measured colors inside the box are retained.
Both baselines and candidates trust the same saved optimized poses.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from reconstruct_scans import reconstruct, optical_to_pose_axes, write_json


def optical_points(depth, calibration, selected=None):
    h, w = depth.shape
    ids = np.flatnonzero(depth.ravel()>0) if selected is None else selected
    v, u = np.divmod(ids, w)
    z = depth.ravel()[ids]
    K = np.asarray(calibration["K"])
    return ids, np.column_stack(((u*calibration["width"]/w-K[0,2])*z/K[0,0],
        (v*calibration["height"]/h-K[1,2])*z/K[1,1], z))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scans", nargs="+", default=["scan_20261018131222", "scan_20261018131359"])
    args = parser.parse_args()
    output = args.out.resolve()
    if output.exists() and any(output.iterdir()): parser.error("Use a new/empty experiment directory")
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for key in args.scans:
        scan = args.decoded/key; index = json.loads((scan/"index.json").read_text(encoding="utf-8"))
        original = Path(index["source_directory"]).resolve()
        if output == original or original in output.parents or output == scan.resolve() or scan.resolve() in output.parents:
            raise ValueError("Keep experiments separate from source and decoded records")
        if index.get("color_layout_version") != 2: raise ValueError("Verified physical RGB convention required")
        calibration = index["intrinsics"]["Pl"]; signs = optical_to_pose_axes(index)
        seeds, frames = [], []
        for f in index["frames"]:
            folder = scan/f"frame_{f['id']:010d}"
            if not(folder/"pose_optimized.npy").is_file():continue
            pose = np.load(folder/"pose_optimized.npy", allow_pickle=False)
            with np.load(folder/"frame.npz", allow_pickle=False) as saved:
                depth, rgba = saved["depth_mm"], saved["rgba"]
            rgb = rgba[:,:3].astype(float)
            # This threshold targets the green cup; it is explicitly not used
            # as a per-pixel final mask, so black print/interior may survive.
            seed = (rgb[:,1]-rgb[:,0]>3)&(rgb[:,1]-rgb[:,2]>8)&(rgb[:,1]>12)
            ids = np.flatnonzero(depth.ravel()>0)[seed][::8]
            _, xyz = optical_points(depth, calibration, ids)
            world = (xyz*signs)@pose[:3,:3].T+pose[:3,3]
            seeds.append(world)
            frames.append({"id":f["id"], "green_seed_pixels":int(seed.sum()), "sampled_seed_points":len(world)})
        seed_points = np.concatenate(seeds)
        if len(seed_points)<1000: raise ValueError("Insufficient color support for a box proposal")
        lower, upper = np.percentile(seed_points,[.5,99.5],axis=0)
        lower-=6;upper+=6
        def depth_selection(depth, pose):
            ids, xyz = optical_points(depth, calibration)
            world = (xyz*signs)@pose[:3,:3].T+pose[:3,3]
            keep = np.all((world>=lower)&(world<=upper),axis=1)
            result = depth.copy();result.ravel()[ids[~keep]]=0
            return result, int((~keep).sum())
        row = {"scan_id":key,"proposal":"green-color-supported axis-aligned box in native scan frame",
            "color_seed_rule":"G-R>3, G-B>8, G>12; uint8 physical RGB",
            "sampling":"each eighth color-supported valid pixel of every optimized-pose frame",
            "box_rule":"per-axis 0.5/99.5 percentiles of seeds, expanded 6 mm per side",
            "seed_points":len(seed_points), "bounds_min_mm":lower.tolist(),"bounds_max_mm":upper.tolist(),
            "same_saved_optimized_poses":True,"uses_vendor_geometry_as_reference":False,
            "frames":frames,
            "limitations":["Color threshold is specific to this green object; it can miss parts or include unrelated green surfaces.",
                "Box includes every measured color inside; it is not proof of complete physical-object preservation.",
                "Poses are unchanged; cropping does not repair tracking or recover unseen surfaces.",
                "Tighter bounds change effective voxel size, so more points are not independent accuracy evidence.",
                "The proposal needs visual review before use in an interactive workflow."]}
        write_json(output/(key+"-selection.json"),row)
        result = reconstruct(scan,output/"candidate",.6,2.4,3.,1,True,
            depth_filter=depth_selection,evaluate_vendor=False,pose_policy="optimized",
            bounds_override_mm=(lower,upper),reconstruction_note="Color-seeded ROI experiment; unchanged optimized poses; all measured colors within proposed box retained. Vendor geometry not used.")
        baseline = json.loads((args.baseline/key/"reconstruction.json").read_text(encoding="utf-8"))
        row["baseline"]={k:baseline[k] for k in ["voxel_mm","integrated_frames","quality","input_valid_pixels","omitted_discontinuity_pixels"]}
        row["candidate"]={k:result[k] for k in ["voxel_mm","integrated_frames","quality","input_valid_pixels","reference_unsupported_pixels_omitted","omitted_discontinuity_pixels"]}
        row["selected_pixels_fraction"]=1-result["reference_unsupported_pixels_omitted"]/result["input_valid_pixels"]
        write_json(output/(key+"-selection.json"),row)
        summaries.append({k:v for k,v in row.items() if k!="frames"})
        command=[sys.executable,"scripts/build_reconstruction_review.py","--unit","mm","--up-axis","x","--invert-up","--max-points","30000","--allow-overlay","--out",str(output/(key+"-review.html")),"--notes","同一位姿与帧；候选仅按颜色提出的空间盒裁剪，所有盒内颜色保留。候选范围缩小，实际体素变细。需要人工检查是否裁掉真实部分；不能视为跟踪已修复。"]
        for label,path in [("原全场景 TSDF",args.baseline/key/"tsdf_pointcloud_mm.ply"),("物体盒裁剪候选",output/"candidate"/key/"tsdf_pointcloud_mm.ply")]:command += ["--cloud",label+"="+str(path)]
        subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    write_json(output/"summary.json",summaries)
    lines=["# 颜色辅助的物体区域实验\n","保持原优化位姿，用绿色观测提出空间盒，再保留盒内所有颜色的深度。未使用官方预览或融合几何选区。该阈值只适用于本次绿色杯子，是交互式选区候选，仍需检查遗漏和背景。\n","| 工程 | 原/候选体素 mm | 原/候选点数 | 原/候选主连通面 | 保留深度像素 |","| --- | --- | --- | --- | --- |"]
    for row in summaries:
        a,b=row["baseline"],row["candidate"];key=row["scan_id"]
        lines.append(f"| [{key}]({key}-review.html) | {a['voxel_mm']:.3f} / {b['voxel_mm']:.3f} | {a['quality']['point_count']:,} / {b['quality']['point_count']:,} | {a['quality']['largest_component_triangle_fraction']:.1%} / {b['quality']['largest_component_triangle_fraction']:.1%} | {row['selected_pixels_fraction']:.1%} |")
    lines += ["\n点数、连通性和密度反映表示与裁剪变化，不是物理精度测量。背景排除与实际体素改变共同影响输出，不能把差异全部归因于算法修复。\n"]
    (output/"README.md").write_text("\n".join(lines),encoding="utf-8")


if __name__ == "__main__":
    main()

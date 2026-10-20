"""Re-fuse all saved depths with frozen fragment corrections, as candidates."""

import os
os.environ.setdefault("OMP_NUM_THREADS","4")

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d
from PIL import Image,ImageDraw

from reconstruct_scans import reconstruct,optical_to_pose_axes,write_json
from experiment_color_seeded_roi import optical_points
from build_attribute_study_report import render,font
from reconstruction_probe.offline import file_sha256


def read(path):return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared",type=Path,required=True)
    parser.add_argument("--registration",type=Path,required=True)
    parser.add_argument("--labels",nargs="+",default=["saved_relative_identity","direct_best_training","direct_alternative_1"])
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();prepared=args.prepared.resolve();registration=args.registration.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error("Use a new/empty output directory")
    out.mkdir(parents=True,exist_ok=True)
    split=read(prepared/"split.json");fitted=read(registration/"summary.json");root=Path(split["source_study"]);key=split["scan_id"]
    decoded=root/"decoded"/key;index=read(decoded/"index.json")
    candidates={row["label"]:row for row in fitted["candidates"]}
    if len(set(args.labels))!=len(args.labels) or set(args.labels)-set(candidates):parser.error("Labels must be unique fitted candidates")
    lower=np.array(split["roi_mm"]["min"]);upper=np.array(split["roi_mm"]["max"])
    original={frame["id"]:np.load(decoded/f"frame_{frame['id']:010d}"/"pose_optimized.npy",allow_pickle=False) for frame in index["frames"]}
    rows=[];clouds=[]
    for label in args.labels:
        correction=np.array(candidates[label]["transform"])
        overrides={rid:(correction@matrix if rid>>32==1 else matrix.copy()) for rid,matrix in original.items()}
        lookup={}
        for rid,matrix in overrides.items():
            code=np.asarray(matrix,dtype="<f8").tobytes()
            if code in lookup and not np.array_equal(lookup[code],original[rid]):raise ValueError("Ambiguous original pose lookup")
            lookup[code]=original[rid]
        digest=hashlib.sha256()
        def original_roi(depth,updated):
            pose=lookup[np.asarray(updated,dtype="<f8").tobytes()]
            ids,xyz=optical_points(depth,index["intrinsics"]["Pl"]);native=(xyz*optical_to_pose_axes(index))@pose[:3,:3].T+pose[:3,3]
            kept=np.all((native>=lower)&(native<=upper),axis=1);selected=depth.copy();selected.ravel()[ids[~kept]]=0
            digest.update(selected.astype("<f4").tobytes())
            return selected,int((~kept).sum())
        result=reconstruct(decoded,out/label,.6,2.4,3.,1,True,pose_overrides=overrides,depth_filter=original_roi,
            evaluate_vendor=False,tsdf_backend="tensor",tsdf_weight_threshold=3.,coordinate_frame="original_group_0_scan_20261018131359_mm",
            reconstruction_note=f"Full-data demonstration of frozen {label} fragment correction, fitted on training frames only. Same original ROI pixels in each arm; all 358 depths are now integrated, so this fused output is not a heldout evaluation.")
        path=out/label/key/"tsdf_pointcloud_mm.ply"
        np.savez_compressed(out/(label+"-poses.npz"),**{f"pose_{rid}":matrix for rid,matrix in overrides.items()})
        rows.append(dict(label=label,integrated_frames=result["integrated_frames"],selected_depth_array_sha256=digest.hexdigest(),
            input_valid_pixels=result["input_valid_pixels"],roi_excluded_pixels=result["depth_selection_pixels_omitted"],quality=result["quality"],
            voxel_mm=result["voxel_mm"],truncation_mm=result["sdf_truncation_mm"],path=str(path)))
        clouds.append((label,o3d.io.read_point_cloud(str(path)),path))
    same=all(all(row[key]==rows[0][key] for key in ["integrated_frames","selected_depth_array_sha256","input_valid_pixels","roi_excluded_pixels","voxel_mm","truncation_mm"]) for row in rows)
    write_json(out/"summary.json",dict(status="exploratory_full_data_candidates_not_promoted",same_input_pixels_and_parameters=same,
        original_roi_mm=split["roi_mm"],results=rows,input_sha256={str(p):file_sha256(p) for p in [prepared/"split.json",registration/"summary.json",decoded/"index.json"]},
        limitations=["All saved depths, including earlier heldout frames, now contribute to the demonstration surfaces; evaluate fitting using the prior holdout report, not these outputs.",
          "The fixed original ROI may exclude real parts; pose corrections cannot restore unseen or excluded geometry.",
          "Point count and connectivity are not physical accuracy or proof of correct fragment identity/orientation.",
          "Original source poses, decoded data and main baseline outputs remain unchanged."]))
    if not same:raise ValueError("Paired reconstruction pixels/parameters differ")
    command=[sys.executable,"scripts/build_reconstruction_review.py","--unit","mm","--up-axis","x","--invert-up","--allow-overlay","--max-points","40000","--out",str(out/"review.html"),"--notes","直接片段配准候选的全 358 帧演示，固定原 ROI、0.6mm、2.4mm 截断及权重阈值 3。位姿修正由训练帧拟合；本页已融合所有帧，不能当留出测试。原位姿与主基线不覆盖。"]
    for label,_,path in clouds:command += ["--cloud",label+"="+str(path)]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    bounds=(np.min([pc.get_min_bound() for _,pc,_ in clouds],axis=0),np.max([pc.get_max_bound() for _,pc,_ in clouds],axis=0))
    picture=Image.new("RGB",(500*len(clouds),530),(24,33,47));draw=ImageDraw.Draw(picture)
    for i,((label,pc,_),row) in enumerate(zip(clouds,rows)):
        draw.text((i*500+12,10),label,font=font(18),fill="#edf3fa")
        picture.paste(render(pc,(490,390),yaw=1.2,pitch=.15,bounds=bounds),(i*500+5,45))
        draw.text((i*500+12,452),f"{row['quality']['point_count']:,} 点 · 主连通面 {row['quality']['largest_component_triangle_fraction']:.1%}",font=font(17),fill="#edf3fa")
    draw.text((12,500),"同一原 ROI、同一358帧与固定融合参数；颜色显示增亮1.8倍，模型文件保留原色。",font=font(16),fill="#adbed1")
    picture.save(out/"comparison.png")
    print(json.dumps(dict(same_inputs=same,results=rows)),flush=True)


if __name__=="__main__":main()

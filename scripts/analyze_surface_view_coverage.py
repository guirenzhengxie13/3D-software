"""Trace a candidate surface to saved depths and measure view directions.

This describes internal observation coverage of a reconstructed surface. It
does not find completely unseen geometry or certify surface correctness.
"""

import os
os.environ.setdefault("OMP_NUM_THREADS","4")

import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d
from PIL import Image,ImageDraw

from build_attribute_study_report import render,font
from reconstruct_scans import clean_depth_edges,optical_to_pose_axes,write_json
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.poses import _rigid_matrix
from reconstruction_probe.visibility import project_depth_observations
from reconstruction_probe.view_coverage import ViewDirectionAccumulator


LABELS=["supported_broad_first_view_separation","supported_intermediate","supported_narrow_first_view_separation","fewer_than_three_support_views","repeated_free_space_conflict"]
COLORS=np.array([[85,200,126],[95,170,225],[235,182,91],[134,145,162],[192,106,220]],float)/255


def read(path):return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--prepared",type=Path,required=True);parser.add_argument("--fusion",type=Path,required=True);parser.add_argument("--label",default="direct_best_training");parser.add_argument("--out",type=Path,required=True);parser.add_argument("--max-points",type=int,default=40000)
    args=parser.parse_args();prepared=args.prepared.resolve();fusion=args.fusion.resolve();out=args.out.resolve()
    if not 100<=args.max_points<=100000:parser.error("Use 100..100000 surface samples")
    if out.exists() and any(out.iterdir()):parser.error("Use a new/empty output directory")
    out.mkdir(parents=True,exist_ok=True)
    split=read(prepared/"split.json");key=split["scan_id"];root=Path(split["source_study"]);decoded=root/"decoded"/key;index=read(decoded/"index.json")
    full=read(fusion/"summary.json");row=next(r for r in full["results"] if r["label"]==args.label)
    path=Path(row["path"]);pose_path=fusion/(args.label+"-poses.npz")
    cloud=o3d.io.read_point_cloud(str(path));all_xyz=np.asarray(cloud.points)
    if not cloud.has_normals():cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=2.,max_nn=40))
    chosen=np.linspace(0,len(all_xyz)-1,min(args.max_points,len(all_xyz)),dtype=np.int64);xyz=all_xyz[chosen];n=len(xyz)
    normals=np.asarray(cloud.normals)[chosen].copy();lengths=np.linalg.norm(normals,axis=1);valid_normals=np.isfinite(normals).all(1)&(lengths>1e-12)
    normals[valid_normals]/=lengths[valid_normals,None];normals[~valid_normals]=0
    frames=index["frames"];frame_ids=np.array([f['id'] for f in frames],np.int64)
    support=np.zeros((2,n),np.uint16);conflict=support.copy();occluded=support.copy();observed=np.zeros(n,np.uint16);by_group=np.zeros((2,n),np.uint16)
    directions=ViewDirectionAccumulator(n);support_flags=np.zeros((len(frames),n),bool)
    best_view=np.full(n,-1,np.int32);best_pixel=np.full(n,-1,np.int32);best_incidence=np.full(n,-1.,float);best_abs_delta=np.full(n,np.inf)
    range_sum=np.zeros(n,float);camera_centers=[];frame_rows=[]
    with np.load(pose_path,allow_pickle=False) as overrides:
        for ordinal,frame in enumerate(frames):
            rid=frame['id'];pose=_rigid_matrix(np.asarray(overrides[f'pose_{rid}'],dtype='<f8').tobytes(),0,1e-5)
            camera_centers.append(pose[:3,3].copy())
            folder=decoded/f"frame_{rid:010d}"
            with np.load(folder/"frame.npz",allow_pickle=False) as saved:depth=saved['depth_mm']
            depth,_=clean_depth_edges(depth,3.)
            evidence=project_depth_observations(xyz,pose,depth,index['intrinsics']['Pl'],optical_to_pose_axes(index))
            ids,delta=evidence.point_indices,evidence.signed_delta_mm;observed[ids]+=1
            for j,tolerance in enumerate([2.,4.]):
                support[j,ids[np.abs(delta)<=tolerance]]+=1;conflict[j,ids[delta>tolerance]]+=1;occluded[j,ids[delta < -tolerance]]+=1
            inside=np.abs(delta)<=2.;supported=ids[inside];pixels=evidence.pixel_indices[inside];absolute=np.abs(delta[inside])
            rays=pose[:3,3]-xyz[supported];ranges=np.linalg.norm(rays,axis=1)
            directions.add(supported,rays);support_flags[ordinal,supported]=True;range_sum[supported]+=ranges
            high=rid>>32
            if high not in [0,1]:raise ValueError("Unexpected fragment group")
            by_group[high,supported]+=1
            incidence=np.abs(np.sum(normals[supported]*(rays/ranges[:,None]),axis=1))
            better=(incidence>best_incidence[supported]+1e-8)|((np.abs(incidence-best_incidence[supported])<=1e-8)&(absolute<best_abs_delta[supported]))
            selected=supported[better];best_view[selected]=ordinal;best_pixel[selected]=pixels[better];best_incidence[selected]=incidence[better];best_abs_delta[selected]=absolute[better]
            frame_rows.append(dict(frame_id=rid,id_high=high,observed_samples=len(ids),support_samples_2mm=len(supported),conflict_samples_2mm=int((delta>2.).sum())))
            if ordinal%64==0 or ordinal==len(frames)-1:print(f"coverage {ordinal+1}/{len(frames)} views",flush=True)
    if not np.array_equal(directions.count,support[0]):raise ValueError("Direction/support count mismatch")
    angular=directions.metrics();separation=angular['first_support_max_separation_deg']
    categories=np.ones(n,np.uint8);categories[(support[0]>=5)&(separation>=30)]=0;categories[(support[0]>=3)&(separation<15)]=2;categories[support[0]<3]=3;categories[conflict[0]>=3]=4
    mean_range=np.divide(range_sum,support[0],out=np.zeros(n,float),where=support[0]>0)
    oriented=normals.copy();flip=np.sum(oriented*directions.first,axis=1)<0;oriented[flip]*=-1
    np.savez_compressed(out/"coverage-data.npz",source_point_indices=chosen,xyz_scan_mm=xyz,original_normals=normals,normal_toward_first_support=oriented,
        support_counts=support,conflict_counts=conflict,occluded_counts=occluded,observed_counts=observed,support_by_id_high=by_group,
        support_view_bits=np.packbits(support_flags.T,axis=1,bitorder='little'),frame_ids=frame_ids,camera_centers_mm=np.array(camera_centers),
        first_support_direction=directions.first,best_view_index=best_view,best_view_pixel_index=best_pixel,best_abs_normal_dot=best_incidence,
        mean_support_range_mm=mean_range,categories=categories,**angular)
    outputs=[];pcs=[]
    actual=np.asarray(cloud.colors)[chosen] if cloud.has_colors() else np.full((n,3),.65)
    gradient=(np.clip(np.nan_to_num(separation,nan=0)/60,0,1)[:,None]*np.array([90,190,220])+(1-np.clip(np.nan_to_num(separation,nan=0)/60,0,1))[:,None]*np.array([230,178,90]))/255
    for label,rgb in [("原表面颜色",actual),("观测覆盖分类",COLORS[categories]),("与首支持视角的夹角",gradient)]:
        pc=o3d.geometry.PointCloud();pc.points=o3d.utility.Vector3dVector(xyz);pc.colors=o3d.utility.Vector3dVector(rgb);pc.normals=o3d.utility.Vector3dVector(normals)
        name=["physical-rgb-mm.ply","coverage-classes-mm.ply","angular-separation-mm.ply"][len(outputs)];output=out/name;o3d.io.write_point_cloud(str(output),pc);outputs.append((label,output));pcs.append(pc)
    positive=support[0]>0
    summary=dict(scan_id=key,candidate_label=args.label,surface_sample_count=n,full_surface_points=len(all_xyz),saved_views=len(frames),
        coordinate_frame='original_group_0_scan_20261018131359_mm',class_counts={label:int((categories==i).sum()) for i,label in enumerate(LABELS)},
        support_count_quantiles=np.percentile(support[0],[0,25,50,75,100]).tolist(),
        first_support_separation_deg_quantiles=np.percentile(separation[positive],[0,25,50,75,100]).tolist(),
        geometry_path=str(path),pose_overrides_path=str(pose_path),decoded_path=str(decoded),
        thresholds=dict(support_tolerance_mm=2.,support_views_minimum=3,broad_support_views_minimum=5,broad_first_separation_degrees=30.,narrow_first_separation_degrees=15.,repeated_conflict_minimum_views=3),
        input_sha256={str(p):file_sha256(p) for p in [path,pose_path,decoded/'index.json',prepared/'split.json',fusion/'summary.json']},
        limitations=["This surface already integrates all depths used in the coverage check; the counts are internal diagnostics, not held-out accuracy.",
          "View directions use estimated object-relative poses; turntable trajectories are not absolute room camera trajectories.",
          "First-support separation is a lower bound on maximum pairwise separation, not a solid angle or statistical independence measure.",
          "Normal signs were oriented toward the first supporting camera only for descriptive display/proposal calculations.",
          "This analysis cannot color or prove the shape of completely unobserved surfaces that are absent from the model.",
          "More support or a larger angle does not certify physical correctness. No frames or surfaces are automatically discarded."])
    write_json(out/'summary.json',summary)
    with (out/'frame-evidence.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(frame_rows[0]));writer.writeheader();writer.writerows(frame_rows)
    command=[sys.executable,'scripts/build_reconstruction_review.py','--unit','mm','--up-axis','x','--invert-up','--max-points',str(min(n,40000)),'--out',str(out/'review.html'),'--notes','同一表面抽样的内部观测覆盖。绿=至少5视图且与首支持视角相差至少30度；蓝=中间；黄=至少3支持但首视角最大夹角小于15度；灰=不足3支持；紫=至少3自由空间冲突。角度与数量不是精度或独立置信度。']
    for label,path in outputs:command+=['--cloud',label+'='+str(path)]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    picture=Image.new('RGB',(1500,510),(24,33,47));draw=ImageDraw.Draw(picture);bounds=(xyz.min(0),xyz.max(0))
    for i,((label,_),pc) in enumerate(zip(outputs,pcs)):
        draw.text((i*500+12,10),label,font=font(20),fill='#edf3fa');picture.paste(render(pc,(490,390),yaw=1.2,pitch=.15,gain=1.8 if i==0 else 1.,bounds=bounds),(i*500+5,45))
    draw.text((12,465),'覆盖诊断来自同源深度与估计位姿，不等于真实精度；第三图夹角0–60度由黄到蓝显示。',font=font(16),fill='#adbed1');picture.save(out/'comparison.png')
    lines=['# 重建表面的保存视角覆盖','','同一张模型上，一百个相近方向的帧与多个不同方向的帧提供的几何约束不同。本检查分别保留支持次数、深度冲突、遮挡、分组来源，以及相对首个支持视角的最大夹角。','','![覆盖与角度](comparison.png)','','| 类别 | 抽样点数 | 占比 |','| --- | --- | --- |']
    for label,count in summary['class_counts'].items():lines.append(f'| {label} | {count:,} | {count/n:.1%} |')
    lines+=['','方向夹角是至少实际观察到的两方向分离程度，不是所有视角的完整最大值，更不是置信度。完全没有重建出来的区域无法在本图中出现。模型和这些深度同源，因此这些数值不能当作独立精度结果。','','每个抽样表面点保留原 PLY 点编号、支持视图位图、最佳入射视图及像素位置，可继续回查原深度/颜色。最佳入射视图只按已有法向与视线计算，不保证照片最清楚。','','[三维覆盖审阅](review.html) · [完整统计与限制](summary.json) · [逐帧证据](frame-evidence.csv)']
    (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:summary[k] for k in ['surface_sample_count','saved_views','class_counts','support_count_quantiles','first_support_separation_deg_quantiles']}),flush=True)


if __name__=='__main__':main()

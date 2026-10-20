"""Check frozen fragment transforms using only the reserved source records.

Fitting, candidate ranking and ROI proposal have separate provenance. These
are correlated frame-block checks, not independent physical accuracy tests.
"""

import os
os.environ.setdefault("OMP_NUM_THREADS","4")

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d
from PIL import Image,ImageDraw

from analyze_piecewise_holdout import classes,describe,transform,PALETTE
from build_attribute_study_report import render,font
from reconstruct_scans import clean_depth_edges,optical_to_pose_axes,write_json
from experiment_color_seeded_roi import optical_points
from reconstruction_probe.visibility import depth_observation_deltas
from reconstruction_probe.offline import file_sha256


def read(path):return json.loads(path.read_text(encoding="utf-8"))


def evidence(points,groups,ordinals,views,index,transforms,*,self_control=False):
    n=len(points);observed=np.zeros(n,np.uint16);support=np.zeros((2,n),np.uint16);conflict=support.copy();occluded=support.copy()
    for high,ordinal,pose,depth in views:
        selected=(groups==high)&(np.abs(ordinals-ordinal)>8) if self_control else groups!=high
        candidates=np.flatnonzero(selected)
        if not len(candidates):continue
        target_pose=transforms[high]@pose
        ids,delta=depth_observation_deltas(points[candidates],target_pose,depth,index["intrinsics"]["Pl"],optical_to_pose_axes(index))
        ids=candidates[ids];observed[ids]+=1
        for j,tolerance in enumerate([2.,4.]):
            support[j,ids[np.abs(delta)<=tolerance]]+=1;conflict[j,ids[delta>tolerance]]+=1;occluded[j,ids[delta < -tolerance]]+=1
    return dict(support=support,conflict=conflict,occluded=occluded,observed=observed)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared",type=Path,required=True)
    parser.add_argument("--registration",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--points-per-frame",type=int,default=64)
    parser.add_argument("--view-stride",type=int,default=4)
    args=parser.parse_args();prepared=args.prepared.resolve();registration=args.registration.resolve();out=args.out.resolve()
    if args.points_per_frame<1 or args.view_stride<1:parser.error("Positive sampling sizes required")
    if out.exists() and any(out.iterdir()):parser.error("Use a new/empty output directory")
    out.mkdir(parents=True,exist_ok=True)
    split=read(prepared/"split.json");fit=read(registration/"summary.json")
    if str(prepared/"split.json") in fit["input_sha256"] and file_sha256(prepared/"split.json")!=fit["input_sha256"][str(prepared/"split.json")]:raise ValueError("Fitted split changed")
    root=Path(split["source_study"]);decoded=root/"decoded"/split["scan_id"];index=read(decoded/"index.json")
    lower,upper=np.array(split["roi_mm"]["min"]),np.array(split["roi_mm"]["max"])
    training_ids=set();heldout_ids=set();rng=np.random.default_rng(20261019)
    raw,highs,source_ids,pixels,ordinals,colors,views=[],[],[],[],[],[],[]
    for group in split["groups"]:
        high=group["id_high"];training_ids.update(group["training_ids"]);heldout_ids.update(group["heldout_ids"])
        view_ids=set(group["heldout_ids"][::args.view_stride]+[group["heldout_ids"][-1]])
        for rid in group["heldout_ids"]:
            folder=decoded/f"frame_{rid:010d}"
            with np.load(folder/"frame.npz",allow_pickle=False) as saved:depth=saved["depth_mm"];rgba=saved["rgba"]
            original_valid=np.flatnonzero(depth.ravel()>0)
            depth,_=clean_depth_edges(depth,3.)
            ids,xyz=optical_points(depth,index["intrinsics"]["Pl"])
            pose=np.load(folder/"pose_optimized.npy",allow_pickle=False)
            native=transform(xyz*optical_to_pose_axes(index),pose)
            inside=np.flatnonzero(np.all((native>=lower)&(native<=upper),axis=1))
            chosen=np.sort(rng.choice(inside,min(args.points_per_frame,len(inside)),replace=False))
            raw.append(native[chosen]);highs.append(np.full(len(chosen),high,np.int64));source_ids.append(np.full(len(chosen),rid,np.int64));pixels.append(ids[chosen])
            ordinals.append(np.full(len(chosen),group["saved_record_ordinals"][str(rid)],np.int64))
            colors.append(rgba[np.searchsorted(original_valid,ids[chosen]),:3])
            if rid in view_ids:views.append((high,group["saved_record_ordinals"][str(rid)],pose,depth))
    if training_ids&heldout_ids:raise ValueError("Train/evaluation frame overlap")
    raw,highs,source_ids,pixels,ordinals,colors=map(np.concatenate,(raw,highs,source_ids,pixels,ordinals,colors))
    identity={0:np.eye(4),1:np.eye(4)}
    self_counts=evidence(raw,highs,ordinals,views,index,identity,self_control=True)
    results=[];clouds=[];save_arrays=dict(xyz_original_mm=raw,id_high=highs,frame_ids=source_ids,pixel_ids=pixels,source_group_record_ordinals=ordinals,
        **{"self_"+k:v for k,v in self_counts.items()})
    reference_observed=None
    for candidate in fit["candidates"]:
        label=candidate["label"];matrices={0:np.eye(4),1:np.array(candidate["transform"])}
        xyz=raw.copy();xyz[highs==1]=transform(raw[highs==1],matrices[1])
        counts=evidence(xyz,highs,ordinals,views,index,matrices)
        if reference_observed is None:reference_observed=counts["observed"].copy()
        common=(reference_observed>=3)&(counts["observed"]>=3)
        row=dict(label=label,transform=candidate["transform"],sampled_points=len(raw),common_observed_with_identity=int(common.sum()),thresholds=[])
        for j,tolerance in enumerate([2.,4.]):
            values=describe(counts["support"][j],counts["conflict"][j],counts["observed"],np.ones(len(raw),bool))
            values["occluded_in_at_least_three_views"]=int((counts["occluded"][j]>=3).sum())
            values["common_observed_subset"]=describe(counts["support"][j],counts["conflict"][j],counts["observed"],common)
            values["by_source_id_high"]={str(high):describe(counts["support"][j],counts["conflict"][j],counts["observed"],highs==high) for high in [0,1]}
            values["tolerance_mm"]=tolerance;row["thresholds"].append(values)
        for key,value in counts.items():save_arrays[label+"_"+key]=value
        save_arrays[label+"_common_observed"]=common
        for kind,rgb in [("physical-rgb",colors.astype(float)/255),("evidence",PALETTE[classes(counts["support"][0],counts["conflict"][0])])]:
            pc=o3d.geometry.PointCloud();pc.points=o3d.utility.Vector3dVector(xyz);pc.colors=o3d.utility.Vector3dVector(rgb)
            path=out/(label+"-"+kind+"-mm.ply");o3d.io.write_point_cloud(str(path),pc)
            if kind=="evidence":clouds.append((label,pc,path))
        results.append(row)
        print(json.dumps(dict(label=label,at_2mm=row["thresholds"][0],at_4mm=row["thresholds"][1])),flush=True)
    self_summary=[]
    for j,tolerance in enumerate([2.,4.]):
        self_summary.append(dict(tolerance_mm=tolerance,by_source_id_high={str(high):describe(self_counts["support"][j],self_counts["conflict"][j],self_counts["observed"],highs==high) for high in [0,1]}))
    np.savez_compressed(out/"heldout-evidence.npz",**save_arrays)
    report=dict(scan_id=split["scan_id"],selection="All candidates frozen/ranked on training geometry; this file does not choose a new winner",
        external_reference_geometry_used=False,training_frame_ids=sorted(training_ids),heldout_frame_ids=sorted(heldout_ids),
        fitting_evaluation_overlap=[],source_sampled_points=len(raw),points_per_frame=args.points_per_frame,seed=20261019,
        target_views_by_id_high={str(g):sum(high==g for high,_,_,_ in views) for g in [0,1]},
        self_control_excludes_saved_record_radius=8,results=results,self_control=self_summary,
        input_sha256={str(p):file_sha256(p) for p in [prepared/"split.json",registration/"summary.json",decoded/"index.json"]},
        limitations=["The original ROI proposal used all source color observations, though fitting surfaces use only training IDs.",
          "Held-out saved-record blocks are correlated views, not independent trials or physical truth.",
          "Source samples use original ROI and 3 mm depth-edge filtering. Target views retain full measured depths for occlusion/free-space evidence.",
          "Opposite-group depths provide the cross check; within-group controls exclude the source and +/-8 original group index neighbors.",
          "Missing and occluded observations do not establish surface correctness; no single metric automatically promotes a candidate.",
          "A rigid fragment correction cannot repair drift or nonrigid errors within either fragment."])
    write_json(out/"summary.json",report)
    command=[sys.executable,"scripts/build_reconstruction_review.py","--unit","mm","--up-axis","x","--invert-up","--allow-overlay","--max-points",str(len(raw)),"--out",str(out/"review.html"),"--notes","仅使用未参与训练融合/配准的 172 帧深度。每个点由另一组的留出深度检查，2mm 着色。灰色未定不是正确证明。候选按训练数据预先固定，此页不自动选择胜者。"]
    for label,_,path in clouds:command += ["--cloud",label+"="+str(path)]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    width=500*len(clouds);picture=Image.new("RGB",(width,500),(24,33,47));draw=ImageDraw.Draw(picture)
    bounds=(np.min([pc.get_min_bound() for _,pc,_ in clouds],axis=0),np.max([pc.get_max_bound() for _,pc,_ in clouds],axis=0))
    for i,((label,pc,_),row) in enumerate(zip(clouds,results)):
        draw.text((i*500+12,10),label,font=font(17),fill="#edf3fa")
        picture.paste(render(pc,(490,350),gain=1.,bounds=bounds),(i*500+5,45))
        values=row["thresholds"][0];n=values["points"]
        draw.text((i*500+12,410),f"支持 {values['supported_in_at_least_two_views']/n:.1%} · 冲突 {values['conflicts_in_at_least_three_views']/n:.1%}",font=font(18),fill="#edf3fa")
    draw.text((12,463),"相同留出原始像素；绿支持、紫混合、红冲突、灰未定；阈值 2 mm。",font=font(16),fill="#adbed1")
    picture.save(out/"comparison.png")


if __name__=="__main__":main()

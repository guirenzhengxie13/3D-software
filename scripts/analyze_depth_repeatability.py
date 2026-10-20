"""Raw-depth internal controls for the frozen piecewise cross-check.

Exclude the source view and neighboring eight saved records. Saved-order
distance is not elapsed time. These controls measure internal consistency,
never instrument accuracy or a calibrated tolerance.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from analyze_piecewise_holdout import read, transform, describe
from reconstruct_scans import clean_depth_edges, optical_to_pose_axes
from experiment_color_seeded_roi import optical_points
from reconstruction_probe.visibility import depth_observation_deltas
from reconstruction_probe.offline import file_sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    parser.add_argument("--crosscheck",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    root,cross,out=args.study.resolve(),args.crosscheck.resolve(),args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error("Use a new/empty output directory")
    out.mkdir(parents=True,exist_ok=True)
    source_id="scan_20261018131359";reference_id="scan_20261018131019";validation_id="scan_20261018131127"
    old=read(root/"experiments/cup-piecewise-pose/summary.json")
    whole=np.array(old["whole_scan_transform"]);group={int(k):np.array(v) for k,v in old["group_transforms"].items()}
    with np.load(cross/(reference_id+"-paired-evidence.npz"),allow_pickle=False) as saved:
        original=saved["xyz_source_mm"];high=saved["frame_ids"]>>32
    candidates=np.empty_like(original)
    for g,matrix in group.items():candidates[high==g]=transform(original[high==g],matrix)
    both=np.concatenate([transform(original,whole),candidates]);lower=both.min(0);upper=both.max(0)
    alignment_path=root/"experiments/cup-registration"/(validation_id+"-registration.json")
    validation_to_reference=np.array(read(alignment_path)["transform_source_scan_to_reference_scan"])
    matrices={reference_id:np.eye(4),validation_id:validation_to_reference}
    projects={};rng=np.random.default_rng(20261019)
    for key,matrix in matrices.items():
        decoded=root/"decoded"/key;index=read(decoded/"index.json");xyz=[];frame_indices=[];views=[]
        for i,frame in enumerate(index["frames"]):
            folder=decoded/f"frame_{frame['id']:010d}"
            with np.load(folder/"frame.npz",allow_pickle=False) as saved:depth=saved["depth_mm"]
            depth,_=clean_depth_edges(depth,3.)
            pose=matrix@np.load(folder/"pose_optimized.npy",allow_pickle=False)
            ids,optical=optical_points(depth,index["intrinsics"]["Pl"])
            points=transform(optical*optical_to_pose_axes(index),pose)
            inside=np.flatnonzero(np.all((points>=lower)&(points<=upper),axis=1))
            selected=np.sort(rng.choice(inside,min(64,len(inside)),replace=False))
            xyz.append(points[selected]);frame_indices.append(np.full(len(selected),i,np.int64))
            if i%8==0 or i==len(index["frames"])-1:views.append((i,pose,depth))
        projects[key]=dict(index=index,xyz=np.concatenate(xyz),ordinal=np.concatenate(frame_indices),views=views)
    results=[]
    for source,entry in projects.items():
        for target,views in projects.items():
            n=len(entry["xyz"]);observed=np.zeros(n,np.uint16);support=np.zeros((2,n),np.uint16);conflict=support.copy();occluded=support.copy()
            for ordinal,pose,depth in views["views"]:
                ids,delta=depth_observation_deltas(entry["xyz"],pose,depth,views["index"]["intrinsics"]["Pl"],optical_to_pose_axes(views["index"]))
                if source==target:
                    keep=np.abs(entry["ordinal"][ids]-ordinal)>8
                    ids,delta=ids[keep],delta[keep]
                observed[ids]+=1
                for j,tolerance in enumerate([2.,4.]):
                    support[j,ids[np.abs(delta)<=tolerance]]+=1;conflict[j,ids[delta>tolerance]]+=1;occluded[j,ids[delta < -tolerance]]+=1
            row=dict(source_id=source,target_id=target,sampled_points=n,
                self_view_and_neighborhood_excluded=source==target,excluded_saved_order_radius=8 if source==target else None,
                target_view_count=len(views["views"]),thresholds=[])
            for j,tolerance in enumerate([2.,4.]):
                values=describe(support[j],conflict[j],observed,np.ones(n,bool))
                values.update(tolerance_mm=tolerance,occluded_in_at_least_three_views=int((occluded[j]>=3).sum()))
                row["thresholds"].append(values)
            np.savez_compressed(out/(source+"-into-"+target+".npz"),xyz_reference_mm=entry["xyz"],source_saved_record_ordinals=entry["ordinal"],support=support,conflict=conflict,occluded=occluded,observed=observed)
            results.append(row);print(json.dumps(row),flush=True)
    report=dict(method="Per-frame raw point samples checked against saved depths; self and +/-8 saved-record neighbors excluded for internal controls",
        record_order="Decoded index order: ORDER BY full frame ID, not capture time or physical persistence order",
        bounds_reference_mm=dict(min=lower.tolist(),max=upper.tolist(),rule="Union bounds of the frozen whole/group transformed source samples, before reading validation depths"),
        fixed_points_per_frame=64,fixed_seed=20261019,fixed_view_stride=8,
        input_sha256={str(p):file_sha256(p) for p in [cross/(reference_id+"-paired-evidence.npz"),alignment_path]},results=results,
        limitations=["Bounds limit different source samples to a shared spatial region; source point sets and weighting still differ.",
          "Internal controls exclude adjacent saved records but are neither independent trials nor physical ground truth.",
          "An internally consistent scan can still be distorted or globally misaligned.",
          "Reciprocal controls depend on the pre-existing rigid registration and possible object/scan differences.",
          "These diagnostics do not select a best tolerance or justify accepting the piecewise candidate."])
    (out/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# 深度重复观测对照","","每帧最多 64 个点、固定种子及相同参考空间盒，检查 2/4 mm 阈值。自己检查自己时排除源帧及前后 8 条索引记录。本批索引按完整帧 ID 升序；不能将索引距离理解为真实时间或文件写入顺序。","",
           "| 来源→目标 | 阈值 mm | 点数 | 至少两次支持 | 至少三次冲突 |","| --- | --- | --- | --- | --- |"]
    for row in results:
        for item in row["thresholds"]:
            n=row["sampled_points"]
            lines.append(f"| {row['source_id'].removeprefix('scan_20261018')}→{row['target_id'].removeprefix('scan_20261018')} | {item['tolerance_mm']:g} | {n:,} | {item['supported_in_at_least_two_views']/n:.1%} | {item['conflicts_in_at_least_three_views']/n:.1%} |")
    lines += ["","内部一致性、跨扫描对齐误差与物理误差是不同问题。不能用本对照自动校准毫米阈值或接受分组候选。详见 [summary.json](summary.json)。"]
    (out/"README.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__=="__main__":main()

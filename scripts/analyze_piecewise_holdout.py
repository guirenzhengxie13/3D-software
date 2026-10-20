"""Compare frozen whole-scan/group corrections on identical measured points.

13:10:19 is the fitting reference. 13:11:27 did not fit the two group transforms;
its pre-existing alignment to that reference is frozen for this diagnostic.
No reconstruction, fitting, parameter selection or input mutation occurs here.
"""

import os
os.environ.setdefault("OMP_NUM_THREADS", "4")

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d

from reconstruct_scans import clean_depth_edges, optical_to_pose_axes
from experiment_color_seeded_roi import optical_points
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.visibility import depth_observation_deltas


LABELS = ["supported_only", "mixed", "conflict_only", "inconclusive"]
PALETTE = np.array([[85,200,126], [186,108,226], [244,94,96], [130,144,160]], float) / 255


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def transform(points, matrix):
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def classes(support, conflict):
    """Four threshold classes; 'only' means no repeated opposing evidence.

    A supported_only point can have one/two conflict views; a conflict_only
    point can have one support view. These are not zero-error categories.
    """
    result = np.full(len(support), 3, np.uint8)
    yes, no = support >= 2, conflict >= 3
    result[yes & ~no] = 0
    result[yes & no] = 1
    result[~yes & no] = 2
    return result


def describe(support, conflict, observed, subset):
    count = int(subset.sum())
    return dict(points=count, observed_at_least_once=int(((observed >= 1) & subset).sum()),
        observed_in_at_least_three_views=int(((observed >= 3) & subset).sum()),
        supported_in_at_least_two_views=int(((support >= 2) & subset).sum()),
        conflicts_in_at_least_three_views=int(((conflict >= 3) & subset).sum()),
        class_counts={label:int(((classes(support,conflict)==i)&subset).sum()) for i,label in enumerate(LABELS)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--points-per-frame", type=int, default=64)
    parser.add_argument("--view-stride", type=int, default=8)
    args = parser.parse_args()
    if args.points_per_frame < 1 or args.view_stride < 1:
        parser.error("Positive sample sizes required")
    root, output = args.study.resolve(), args.out.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Use a new/empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    source_id, reference_id, validation_id = "scan_20261018131359", "scan_20261018131019", "scan_20261018131127"
    decoded = root / "decoded" / source_id
    index = read(decoded / "index.json")
    previous = read(root / "experiments/cup-piecewise-pose/summary.json")
    whole = np.array(previous["whole_scan_transform"])
    group_transforms = {int(g):np.array(matrix) for g,matrix in previous["group_transforms"].items()}
    roi = previous["original_roi_selection_mm"]
    lower, upper = np.array(roi["min"]), np.array(roi["max"])
    rng = np.random.default_rng(20261019)
    source_points, frame_ids, pixel_ids = [], [], []
    for frame in index["frames"]:
        rid = frame["id"]
        folder = decoded / f"frame_{rid:010d}"
        with np.load(folder / "frame.npz", allow_pickle=False) as saved:
            depth = saved["depth_mm"]
        depth, _ = clean_depth_edges(depth, 3.)
        ids, optical = optical_points(depth, index["intrinsics"]["Pl"])
        matrix = np.load(folder / "pose_optimized.npy", allow_pickle=False)
        native = transform(optical * optical_to_pose_axes(index), matrix)
        inside = np.flatnonzero(np.all((native >= lower) & (native <= upper), axis=1))
        chosen = np.sort(rng.choice(inside, min(args.points_per_frame, len(inside)), replace=False))
        source_points.append(native[chosen])
        frame_ids.append(np.full(len(chosen), rid, np.int64))
        pixel_ids.append(ids[chosen])
    source_points, frame_ids, pixel_ids = map(np.concatenate, (source_points, frame_ids, pixel_ids))
    high = frame_ids >> 32
    points = {"whole_scan_control":transform(source_points,whole), "piecewise_candidate":np.empty_like(source_points)}
    for group, matrix in group_transforms.items():
        selected = high == group
        points["piecewise_candidate"][selected] = transform(source_points[selected],matrix)
    if set(high.tolist()) - set(group_transforms):
        raise ValueError("Missing group transform")
    registration = read(root / "experiments/cup-registration" / (validation_id+"-registration.json"))
    validation_to_reference = np.array(registration["transform_source_scan_to_reference_scan"])
    tolerances = np.array([2.,4.])
    results, clouds, frame_rows = [], [], []
    input_paths = [decoded/"index.json",root/"experiments/cup-piecewise-pose/summary.json",
                   root/"experiments/cup-registration"/(validation_id+"-registration.json")]
    for target_id, target_to_reference in [(reference_id, np.eye(4)), (validation_id,validation_to_reference)]:
        target = root / "decoded" / target_id
        target_index = read(target / "index.json")
        input_paths.append(target / "index.json")
        available = target_index["frames"]
        selected_views = available[::args.view_stride]
        if selected_views[-1]["id"] != available[-1]["id"]:
            selected_views.append(available[-1])
        n = len(source_points)
        evidence = {arm:dict(support=np.zeros((2,n),np.uint16), conflict=np.zeros((2,n),np.uint16),
                            occluded=np.zeros((2,n),np.uint16), observed=np.zeros(n,np.uint16)) for arm in points}
        for frame in selected_views:
            folder = target / f"frame_{frame['id']:010d}"
            with np.load(folder / "frame.npz", allow_pickle=False) as saved:
                depth = saved["depth_mm"]
            depth, _ = clean_depth_edges(depth, 3.)
            # Move the target camera into the common 13:10:19 reference frame.
            matrix = target_to_reference @ np.load(folder / "pose_optimized.npy", allow_pickle=False)
            for arm, xyz in points.items():
                ids, delta = depth_observation_deltas(xyz,matrix,depth,target_index["intrinsics"]["Pl"],optical_to_pose_axes(target_index))
                e = evidence[arm]
                e["observed"][ids] += 1
                for j,tolerance in enumerate(tolerances):
                    e["support"][j,ids[np.abs(delta) <= tolerance]] += 1
                    e["conflict"][j,ids[delta > tolerance]] += 1
                    e["occluded"][j,ids[delta < -tolerance]] += 1
        control, candidate = evidence.values()
        both_seen = (control["observed"] >= 3) & (candidate["observed"] >= 3)
        row = dict(target_id=target_id, role="fitting_reference" if target_id==reference_id else "additional_scan_not_used_to_fit_group_transforms",
                   view_ids=[f["id"] for f in selected_views], points=n, paired_common_observed_at_least_three=int(both_seen.sum()), thresholds=[])
        for j,tolerance in enumerate(tolerances):
            threshold = dict(tolerance_mm=float(tolerance), arms={}, by_id_high={}, transitions={})
            for arm,e in evidence.items():
                threshold["arms"][arm] = describe(e["support"][j],e["conflict"][j],e["observed"],np.ones(n,bool))
                threshold["arms"][arm]["common_observed_subset"] = describe(e["support"][j],e["conflict"][j],e["observed"],both_seen)
            for g in sorted(group_transforms):
                threshold["by_id_high"][str(g)] = {arm:describe(e["support"][j],e["conflict"][j],e["observed"],high==g) for arm,e in evidence.items()}
            before, after = classes(control["support"][j],control["conflict"][j]),classes(candidate["support"][j],candidate["conflict"][j])
            for name, subset in [("all",np.ones(n,bool)),("common_observed",both_seen)]:
                matrix = np.bincount(before[subset]*4+after[subset],minlength=16).reshape(4,4)
                threshold["transitions"][name] = dict(order=LABELS, rows_before_columns_after=matrix.tolist())
            row["thresholds"].append(threshold)
            for rid in sorted(set(frame_ids.tolist())):
                chosen = frame_ids == rid
                c, p = control["conflict"][j,chosen] >= 3, candidate["conflict"][j,chosen] >= 3
                frame_rows.append(dict(target_id=target_id, frame_id=rid, id_high=rid>>32,tolerance_mm=float(tolerance),
                    points=int(chosen.sum()),control_conflicts=int(c.sum()),candidate_conflicts=int(p.sum()),
                    conflict_change=int(p.sum())-int(c.sum())))
        np.savez_compressed(output/(target_id+"-paired-evidence.npz"),frame_ids=frame_ids,pixel_ids=pixel_ids,
            xyz_source_mm=source_points,common_observed=both_seen,tolerances_mm=tolerances,
            **{arm+"_"+k:v for arm,e in evidence.items() for k,v in e.items()})
        for arm,xyz in points.items():
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector(xyz)
            cloud.colors = o3d.utility.Vector3dVector(PALETTE[classes(evidence[arm]["support"][0],evidence[arm]["conflict"][0])])
            path = output/(target_id+"-"+arm+"-evidence-mm.ply")
            o3d.io.write_point_cloud(str(path),cloud)
            clouds.append((target_id.removeprefix("scan_")+" · "+arm,path))
        results.append(row)
        print(json.dumps(dict(target=target_id, points=n, common_observed=row["paired_common_observed_at_least_three"],
                             at_2mm=row["thresholds"][0]["arms"])),flush=True)
    digest=hashlib.sha256(frame_ids.astype("<i8").tobytes()+pixel_ids.astype("<i8").tobytes()+source_points.astype("<f8").tobytes()).hexdigest()
    report = dict(method="Frozen rigid transforms applied to exactly the same source-frame/pixel observations; signed target depth evidence",source_id=source_id,
        seed=20261019, points_per_frame=args.points_per_frame, sampled_points=len(source_points),source_sample_sha256=digest,
        original_roi_mm=roi, transforms_refitted=False,view_stride=args.view_stride,
        input_sha256={str(p):file_sha256(p) for p in input_paths}, results=results,
        limitations=["The additional scan was not used to fit group transforms, but its alignment to the fitting reference is an algorithmic estimate, not physical truth.",
          "The green cup projects are visually similar; physical object identity has not been independently confirmed, so object differences can also affect comparisons.",
          "The additional scan was already inspected in earlier experiments; this is additional-data validation, not a preregistered blind test.",
          "Points are sampled per source frame, so repeatedly observed regions are weighted repeatedly; this is not area-weighted surface accuracy.",
        "Views and points are correlated; counts are descriptive, not independent probabilities or confidence intervals.",
          "Requiring both arms observed in at least three views helps expose visibility evasion, but does not prove correctness.",
          "Reference/target geometry, calibration, poses and symmetry ambiguity can all affect evidence.",
          "Tolerances and existing transforms are frozen; no automatic promotion, rejection of input frames or pose overwrite occurs."])
    (output/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    with (output/"per-frame.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(frame_rows[0]));writer.writeheader();writer.writerows(frame_rows)
    lines=["# 分组变换的相同像素交叉检查","","两种变换作用于完全相同的原始深度采样点，不重新融合、不重新配准。颜色：绿=支持、紫=支持与冲突并存、红=冲突、灰=证据不足。","",
           "13:10:19 用于此前配准，13:11:27 未参与分组变换拟合。后者到参考的既有配准保持固定，因此是有条件的额外扫描检查，仍不是物理精度测量或盲测。","",
           "| 深度目标 | 阈值 mm | 同样本点数 | 两者共同可观测点 | 全部点冲突：整段→分组 | 共同可观测点冲突：整段→分组 | 全部点支持：整段→分组 |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in results:
        for item in row["thresholds"]:
            a,b=item["arms"].values();c,d=a["common_observed_subset"],b["common_observed_subset"]
            lines.append(f"| {row['target_id']} | {item['tolerance_mm']:g} | {row['points']:,} | {row['paired_common_observed_at_least_three']:,} | {a['conflicts_in_at_least_three_views']:,} → {b['conflicts_in_at_least_three_views']:,} | {c['conflicts_in_at_least_three_views']:,} → {d['conflicts_in_at_least_three_views']:,} | {a['supported_in_at_least_two_views']:,} → {b['supported_in_at_least_two_views']:,} |")
    lines += ["", "不凭单个冲突比例认定修复成功；同时查看支持、共同可观测点、分组差异和逐帧变化。完整转移矩阵与限制见 [summary.json](summary.json)，逐帧统计见 [per-frame.csv](per-frame.csv)，[三维查看](review.html)。"]
    (output/"README.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    command=[sys.executable,"scripts/build_reconstruction_review.py","--unit","mm","--up-axis","x","--invert-up","--allow-overlay","--max-points",str(len(source_points)),"--out",str(output/"review.html"),"--notes","相同源帧/像素，固定既有整段与分组变换。13:10:19 是拟合参考，13:11:27 未拟合分组变换，但其既有配准也有误差。颜色阈值 2mm：绿支持、紫混合、红冲突、灰未定。不修改原始位姿。"]
    for label,path in clouds:command += ["--cloud",label+"="+str(path)]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()

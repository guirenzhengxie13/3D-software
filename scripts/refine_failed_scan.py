"""Bounded, explicitly reference-dependent repair experiment for scan_04.

The successful scan_03 TSDF is used as an alignment prior, never called
independent accuracy truth. Unsupported regions are excluded, not invented.
Baseline data and reconstructions remain unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import time

import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree

from reconstruct_scans import stored_pose, reconstruct, summarize_distances, write_json


def point_cloud(points):
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.asarray(points, float))
    return cloud


def project(depth, calibration):
    K = np.asarray(calibration["K"])
    h, w = depth.shape
    ids = np.flatnonzero(depth.ravel() > 0)
    v, u = np.divmod(ids, w)
    z = depth.ravel()[ids]
    x = (u * calibration["width"] / w - K[0, 2]) * z / K[0, 0]
    y = (v * calibration["height"] / h - K[1, 2]) * z / K[1, 1]
    return ids, np.column_stack((x, y, z))


def apply(points, matrix):
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def evaluate_frame(item, decoded, calibration, initial_cross_scan, reference, tree):
    rid = item["id"]
    folder = decoded / f"frame_{rid:010d}"
    matrix, _ = stored_pose(folder, rid, {}, False)
    path = folder / "frame.npz"
    if matrix is None or not path.exists():
        return {"id": rid, "accepted": False, "reasons": ["missing_depth_or_pose"]}, None
    with np.load(path, allow_pickle=False) as arrays:
        _, points = project(arrays["depth_mm"], calibration)
    source = point_cloud(points).voxel_down_sample(1.)
    local = np.asarray(source.points)
    initial = initial_cross_scan @ matrix @ np.diag([1., -1., -1., 1.])
    before_points = apply(local, initial)
    before = tree.query(before_points, workers=1)[0]
    before_summary = summarize_distances(before)
    base = {"id": rid, "sampled_points": len(local), "before": before_summary,
            "initial_within_5mm": float((before < 5).mean())}
    if len(local) < 500 or base["initial_within_5mm"] < .4:
        return {**base, "accepted": False, "reasons": ["insufficient_initial_reference_overlap"]}, None
    coarse = o3d.pipelines.registration.registration_icp(
        source, reference, 4., initial,
        o3d.pipelines.registration.TransformationEstimationPointToPlane(
            o3d.pipelines.registration.HuberLoss(k=1.5)),
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=35))
    fine = o3d.pipelines.registration.registration_icp(
        source, reference, 1.5, coarse.transformation,
        o3d.pipelines.registration.TransformationEstimationPointToPlane(
            o3d.pipelines.registration.HuberLoss(k=.65)),
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=25))
    corrected = np.asarray(fine.transformation)
    after_points = apply(local, corrected)
    after = tree.query(after_points, workers=1)[0]
    delta = corrected @ np.linalg.inv(initial)
    angle = float(np.degrees(np.arccos(np.clip((np.trace(delta[:3, :3]) - 1) / 2, -1, 1))))
    displacement = np.linalg.norm(after_points - before_points, axis=1)
    after_summary = summarize_distances(after)
    checks = {
        "at_least_65pct_reference_support_2mm": float((after < 2).mean()) >= .65,
        "median_residual_below_0_75mm": after_summary["median_mm"] <= .75,
        "not_worse": after_summary["median_mm"] <= before_summary["median_mm"] + .03,
        "rotation_correction_below_8deg": angle <= 8,
        "median_point_displacement_below_8mm": float(np.median(displacement)) <= 8,
        "camera_origin_displacement_below_35mm": float(np.linalg.norm(corrected[:3, 3] - initial[:3, 3])) <= 35,
    }
    accepted = all(checks.values())
    result = {**base, "after": after_summary, "accepted": accepted,
              "reasons": [key for key, value in checks.items() if not value], "checks": checks,
              "rotation_correction_deg": angle,
              "median_point_displacement_mm": float(np.median(displacement)),
              "camera_origin_displacement_mm": float(np.linalg.norm(corrected[:3, 3] - initial[:3, 3])),
              "corrected_optical_camera_to_scan03": corrected.tolist()}
    # Shared reconstruction applies the optical-to-geometry sign convention.
    return result, corrected @ np.diag([1., -1., -1., 1.]) if accepted else None


def summarize(records):
    accepted = [row for row in records if row["accepted"]]
    evaluated = [row for row in records if "after" in row]
    return {"attempted": len(records), "accepted": len(accepted), "rejected": len(records) - len(accepted),
            "rejection_reasons": dict(Counter(reason for row in records for reason in row.get("reasons", []))),
            "median_before_frame_median_mm": float(np.median([row["before"]["median_mm"] for row in evaluated])) if evaluated else None,
            "median_after_frame_median_mm": float(np.median([row["after"]["median_mm"] for row in evaluated])) if evaluated else None,
            "accepted_median_rotation_correction_deg": float(np.median([row["rotation_correction_deg"] for row in accepted])) if accepted else None,
            "accepted_p90_rotation_correction_deg": float(np.percentile([row["rotation_correction_deg"] for row in accepted], 90)) if accepted else None,
            "accepted_median_point_displacement_mm": float(np.median([row["median_point_displacement_mm"] for row in accepted])) if accepted else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", type=Path, default=Path("reports/four-scans/decoded/scan_04"))
    parser.add_argument("--reference", type=Path, default=Path("reports/four-scans/reconstruction/scan_03/tsdf_pointcloud_mm.ply"))
    parser.add_argument("--registration", type=Path, default=Path("reports/four-scans/registration/scan_04_registration.json"))
    parser.add_argument("--out", type=Path, default=Path("reports/four-scans/reconstruction/scan_04_reference_assisted"))
    parser.add_argument("--samples", type=int, default=48)
    parser.add_argument("--full-if-promising", action="store_true")
    args = parser.parse_args()
    started = time.time()
    args.out.mkdir(parents=True, exist_ok=True)
    index = json.loads((args.decoded / "index.json").read_text(encoding="utf-8"))
    calibration = index["intrinsics"]["Pl"]
    cross = json.loads(args.registration.read_text(encoding="utf-8"))
    initial_cross = np.asarray(cross["transform_source_to_reference"])
    reference = o3d.io.read_point_cloud(str(args.reference.resolve())).voxel_down_sample(.8)
    reference.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=3., max_nn=40))
    tree = cKDTree(np.asarray(reference.points))
    frames = [row for row in index["frames"] if row.get("depth_status") == "decoded"]
    sample_indices = np.linspace(0, len(frames) - 1, min(args.samples, len(frames)), dtype=int)
    subset = [frames[i] for i in sample_indices]
    records, overrides = [], {}
    for item in subset:
        result, pose = evaluate_frame(item, args.decoded, calibration, initial_cross, reference, tree)
        records.append(result)
        if pose is not None:
            overrides[item["id"]] = pose
    subset_summary = summarize(records)
    promising = (subset_summary["accepted"] >= .5 * subset_summary["attempted"]
                 and subset_summary["median_after_frame_median_mm"] is not None
                 and subset_summary["median_after_frame_median_mm"] < .8 * subset_summary["median_before_frame_median_mm"])
    report = {"classification": "reference_assisted_repair_experiment_not_independent_accuracy_validation",
              "reference": str(args.reference), "initial_cross_scan_registration_accepted": cross["accepted"],
              "initial_transform_is_only_a_starting_candidate": True,
              "subset": subset_summary, "subset_promising": promising, "subset_records": records,
              "limitations": ["Geometric agreement was optimized against scan_03 and is not independent accuracy evidence.",
                              "Symmetric or feature-poor local alignments still need visual review.",
                              "Depth pixels farther than 2.5mm from reference support are omitted from final TSDF; they may be novel or erroneous, not proven defects.",
                              "Rejected frames and the unmodified baseline are retained outside this result."]}
    write_json(args.out / "subset_experiment.json", report)
    print(json.dumps({"subset": subset_summary, "promising": promising}), flush=True)
    if args.full_if_promising and promising:
        done = {row["id"] for row in records}
        for index_number, item in enumerate(frames):
            if item["id"] not in done:
                result, pose = evaluate_frame(item, args.decoded, calibration, initial_cross, reference, tree)
                records.append(result)
                if pose is not None:
                    overrides[item["id"]] = pose
            if index_number % 100 == 0:
                print(f"reference-assisted ICP: {index_number + 1}/{len(frames)} frames", flush=True)
        report["full"] = summarize(records)
        report["full_records"] = sorted(records, key=lambda row: row["id"])
        np.savez_compressed(args.out / "accepted_pose_overrides.npz", **{f"pose_{rid}": value for rid, value in overrides.items()})

        def reference_depth_filter(depth, matrix):
            ids, points = project(depth, calibration)
            signed_world = apply(points * [1, -1, -1], matrix)
            supported = tree.query(signed_world, workers=1)[0] <= 2.5
            filtered = depth.copy()
            filtered.ravel()[ids[~supported]] = 0
            return filtered, int((~supported).sum())

        result = reconstruct(args.decoded, args.out, .65, 2.6, 3., 1, False,
            pose_overrides=overrides, depth_filter=reference_depth_filter, evaluate_vendor=False,
            coordinate_frame="scan_03_reference_frame",
            reconstruction_note="REFERENCE-ASSISTED: scan04 poses fitted to successful scan03 TSDF; unsupported depth omitted. Baseline remains separate.")
        report["reconstruction"] = {key: value for key, value in result.items() if key != "frames"}
    report["elapsed_seconds"] = time.time() - started
    write_json(args.out / "experiment.json", report)
    print(json.dumps({key: report[key] for key in ("subset_promising", "elapsed_seconds")}
                     | ({"full": report["full"]} if "full" in report else {})), flush=True)


if __name__ == "__main__":
    main()

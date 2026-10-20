"""Test marker-assisted poses for frames absent from the optimized pose table.

Even-index marker records fit each correction; odd-index records validate it.
The framework itself comes from the vendor project, so this is not independent
ground truth. Both controls reconstruct exactly the same accepted frame IDs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from reconstruct_scans import reconstruct, write_json, optical_to_pose_axes
from reconstruction_probe.marker_refinement import refine_marker_points


def summary(values):
    values = np.asarray(values, float)
    return {"n": len(values), "median_mm": float(np.median(values)),
            "p90_mm": float(np.percentile(values, 90)), "within_1mm": float(np.mean(values <= 1))} if len(values) else {"n": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reconstruct", action="store_true")
    parser.add_argument("--baseline-cloud", type=Path)
    args = parser.parse_args()
    scan, output = args.scan.resolve(), args.out.resolve()
    if scan == output or scan in output.parents or output in scan.parents:
        parser.error("Separate experimental outputs from decoded input")
    if output.exists() and any(output.iterdir()):
        parser.error("Use a new/empty experiment output")
    output.mkdir(parents=True, exist_ok=True)
    index = json.loads((scan / "index.json").read_text(encoding="utf-8"))
    signs = optical_to_pose_axes(index)
    with np.load(scan / "global_markers_1.npz", allow_pickle=False) as saved:
        framework = saved["xyz_scan_mm"].copy()
    tree = cKDTree(framework)
    control, candidate, records = {}, {}, []
    heldout_before, heldout_after = [], []
    depth_before, depth_after = [], []
    baseline_tree = None
    if args.baseline_cloud:
        import open3d as o3d
        cloud = o3d.io.read_point_cloud(str(args.baseline_cloud.resolve()))
        if cloud.is_empty():
            raise ValueError("Empty optimized-only baseline cloud")
        baseline_tree = cKDTree(np.asarray(cloud.points))
    calibration = index["intrinsics"]["Pl"]
    K = np.array(calibration["K"], float)
    for item in index["frames"]:
        rid = item["id"]
        folder = scan / f"frame_{rid:010d}"
        optimized = folder / "pose_optimized.npy"
        if optimized.exists():
            pose = np.load(optimized, allow_pickle=False)
            control[rid], candidate[rid] = pose, pose
            continue
        record = {"id": rid, "id_high_word": rid >> 32, "accepted": False}
        try:
            pose = np.load(folder / "pose_stored.npy", allow_pickle=False)
            with np.load(folder / "markers.npz", allow_pickle=False) as saved:
                local = saved["xyz_camera_mm"].copy()
            world = (local * signs) @ pose[:3, :3].T + pose[:3, 3]
            train, holdout = world[::2], world[1::2]
            delta = refine_marker_points(train, framework)
            corrected = world @ delta[:3, :3].T + delta[:3, 3]
            before_all = tree.query(holdout)[0]
            eligible = before_all <= 2.
            before = before_all[eligible]
            after = tree.query(holdout @ delta[:3, :3].T + delta[:3, 3])[0][eligible]
            rotation = float(np.rad2deg(Rotation.from_matrix(delta[:3, :3]).magnitude()))
            displacement = float(np.median(np.linalg.norm(corrected - world, axis=1)))
            new_pose = delta @ pose
            checks = {"at_least_three_heldout_initially_supported": len(before) >= 3,
                "rotation_below_2deg": rotation <= 2, "median_marker_displacement_below_3mm": displacement <= 3,
                "camera_origin_shift_below_30mm": np.linalg.norm(new_pose[:3, 3] - pose[:3, 3]) <= 30,
                "heldout_median_below_0_25mm": len(after) >= 3 and np.median(after) <= .25,
                "heldout_median_not_worse": len(after) >= 3 and np.median(after) <= np.median(before) + .03,
                "heldout_p90_not_worse": len(after) >= 3 and np.percentile(after, 90) <= np.percentile(before, 90) + .05}
            record.update(accepted=all(checks.values()), checks={k: bool(v) for k, v in checks.items()},
                heldout_total=len(holdout), heldout_eligible=len(before), heldout_before=summary(before), heldout_after=summary(after),
                correction_rotation_deg=rotation, marker_displacement_median_mm=displacement,
                delta=delta.tolist(), corrected_pose=new_pose.tolist())
            if record["accepted"]:
                control[rid], candidate[rid] = pose, new_pose
                heldout_before.extend(before.tolist())
                heldout_after.extend(after.tolist())
                if baseline_tree is not None:
                    with np.load(folder / "frame.npz", allow_pickle=False) as saved:
                        depth = saved["depth_mm"]
                    selected = np.flatnonzero(depth.ravel() > 0)[::max(1, int((depth > 0).sum()) // 1000)]
                    v, u = np.divmod(selected, depth.shape[1])
                    z = depth.ravel()[selected]
                    xyz = np.column_stack(((u * calibration["width"] / depth.shape[1] - K[0, 2]) * z / K[0, 0],
                        (v * calibration["height"] / depth.shape[0] - K[1, 2]) * z / K[1, 1], z)) * signs
                    raw_world = xyz @ pose[:3, :3].T + pose[:3, 3]
                    new_world = xyz @ new_pose[:3, :3].T + new_pose[:3, 3]
                    depth_before.extend(baseline_tree.query(raw_world)[0].tolist())
                    depth_after.extend(baseline_tree.query(new_world)[0].tolist())
        except (ValueError, OSError) as exc:
            record["error"] = str(exc)
        records.append(record)
    report = {"scan_id": index["scan_id"], "framework": str(scan / "global_markers_1.npz"),
        "optimized_baseline_frames": index["status"]["optimized_poses_parsed"],
        "attempted_missing_optimized": len(records), "accepted_extra_frames": sum(r["accepted"] for r in records),
        "control_and_candidate_same_frame_ids": sorted(control) == sorted(candidate),
        "control_frame_ids": sorted(control), "heldout_before": summary(heldout_before), "heldout_after": summary(heldout_after),
        "depth_to_optimized_baseline_before": summary(depth_before), "depth_to_optimized_baseline_after": summary(depth_after),
        "records": records,
        "limitations": ["Held-out marker records do not fit this correction, but the saved framework is vendor-derived and not independent truth.",
            "Held-out evaluation is restricted to initially supported markers within 2mm; eligibility counts are reported.",
            "Missing optimized poses do not prove frames were discarded for bad tracking; status semantics remain unknown.",
            "Control and candidate use the same accepted frame IDs; the optimized-only baseline has fewer inputs.",
            "Depth distances to the optimized-only TSDF test internal alignment, not physical surface accuracy.",
            "TSDF adaptive bounds can yield slightly different effective voxel sizes; both are recorded."]}
    np.savez_compressed(output / "control_poses.npz", **{f"pose_{rid}": value for rid, value in control.items()})
    np.savez_compressed(output / "candidate_poses.npz", **{f"pose_{rid}": value for rid, value in candidate.items()})
    write_json(output / "experiment.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("records", "control_frame_ids", "limitations")}), flush=True)
    if args.reconstruct and report["accepted_extra_frames"]:
        for name, poses in (("control", control), ("candidate", candidate)):
            result = reconstruct(scan, output / name, .6, 2.4, 3., 1, False, pose_overrides=poses,
                coordinate_frame="same_native_project_scan_frame", evaluate_vendor=False,
                reconstruction_note=f"{name}: same selected frames; optimized poses retained; missing-stage poses "
                    + ("unchanged" if name == "control" else "refined with even marker records and gated using odd records"))
            report[name + "_reconstruction"] = {k: v for k, v in result.items() if k != "frames"}
            write_json(output / "experiment.json", report)


if __name__ == "__main__":
    main()

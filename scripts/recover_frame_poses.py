"""Export stored FrameInfo poses from an already recovered offline scan.

This reads saved binary records, not an SDK or the source database. Applying
the matrices to optical point clouds requires an explicit axis convention.
The optional marker-framework reader is specific to the observed RANGE case.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reconstruction_probe.poses import parse_frame_info_blob
from reconstruction_probe.sources import _read_ply_cloud


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def marker_framework(path):
    data = path.read_bytes()
    if len(data) < 16:
        raise ValueError("Truncated marker framework")
    version, mode, reserved, count = struct.unpack_from("<4I", data)
    if (version, mode, reserved) != (1, 256, 0) or len(data) != 16 + 64 * count:
        raise ValueError("Unsupported marker framework layout")
    points = np.array([struct.unpack_from("<3d", data, 32 + 64 * i) for i in range(count)])
    if not count or not np.isfinite(points).all():
        raise ValueError("Empty or nonfinite marker framework")
    return points


def nearest_distances(points, reference, o3d):
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.array(points, dtype=float, copy=True))
    return np.asarray(cloud.compute_point_cloud_distance(reference))


def point_cloud(points, o3d):
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.array(points, dtype=float, copy=True))
    return cloud


def distance_summary(distances, unit):
    return {"count": len(distances), "unit": unit,
            "median": float(np.median(distances)),
            "p90": float(np.percentile(distances, 90)),
            "max": float(np.max(distances))}


def write_cloud(path, xyz, colors, unit):
    fields = [(axis, "<f4") for axis in ("x", "y", "z")]
    if colors is not None:
        fields += [(channel, "u1") for channel in ("red", "green", "blue")]
    records = np.empty(len(xyz), dtype=fields)
    for index, axis in enumerate(("x", "y", "z")):
        records[axis] = xyz[:, index]
    properties = ["property float " + axis for axis in ("x", "y", "z")]
    if colors is not None:
        for index, channel in enumerate(("red", "green", "blue")):
            records[channel] = np.rint(np.clip(colors[:, index], 0, 1) * 255).astype(np.uint8)
            properties.append("property uchar " + channel)
    header = ["ply", "format binary_little_endian 1.0", "comment units " + unit,
              "comment coordinates candidate_Revo_scan_frame",
              "comment derived_by_stored_matrix_with_explicit_optical_Z_sign",
              f"element vertex {len(xyz)}", *properties, "end_header"]
    path.write_bytes(("\n".join(header) + "\n").encode("ascii") + records.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recovered", type=Path, help="Directory containing frame_*/frame_info_bin.bin")
    parser.add_argument("--out", type=Path, required=True, help="New, separate output directory")
    parser.add_argument("--unit", choices=("mm", "m"), required=True,
                        help="Independently established common unit for matrices and optional PLYs")
    parser.add_argument("--transform-clouds", action="store_true")
    parser.add_argument("--optical-z-sign", type=int, choices=(-1, 1),
                        help="Explicit convention; -1 is the candidate observed for this RANGE sample")
    parser.add_argument("--reference", type=Path, help="Optional vendor PLY for one-way distance checks")
    parser.add_argument("--marker-framework", type=Path, help="Observed RANGE marker framework for checks")
    args = parser.parse_args()
    source, out = args.recovered.resolve(), args.out.resolve()
    if source == out or source in out.parents or out in source.parents:
        parser.error("Output must be separate from the recovered input directory")
    if out.exists() and any(out.iterdir()):
        parser.error("Output directory must be new or empty")
    if args.transform_clouds and args.optical_z_sign is None:
        parser.error("--transform-clouds needs an explicit --optical-z-sign")
    if args.reference and not args.transform_clouds:
        parser.error("--reference requires --transform-clouds")
    files = sorted(source.glob("frame_*/frame_info_bin.bin"))
    if not files:
        parser.error("No saved FrameInfo binary records found")

    # Parse every record before creating outputs. Unknown layouts fail explicitly.
    parsed = [(path, parse_frame_info_blob(path.read_bytes(), translation_unit=args.unit)) for path in files]
    inputs = set(files)
    if args.transform_clouds:
        inputs.update(path.parent / "cloud_camera.ply" for path in files)
    inputs.update(path.resolve() for path in (args.reference, args.marker_framework) if path)
    before = {str(path): sha256(path) for path in sorted(inputs)}

    o3d = None
    reference = markers = None
    if args.transform_clouds or args.marker_framework:
        from reconstruction_probe._open3d import require_open3d
        o3d = require_open3d()
    if args.reference:
        reference = _read_ply_cloud(o3d, args.reference.resolve())
        if reference.is_empty():
            raise ValueError("Empty reference point cloud")
    if args.marker_framework:
        markers = point_cloud(marker_framework(args.marker_framework), o3d)

    out.mkdir(parents=True, exist_ok=True)
    rows, marker_candidates, cloud_candidates, merged, colors_merged = [], {}, {}, [], []
    for path, info in parsed:
        matrix = info.matrix_at_16
        rid = int(path.parent.name.removeprefix("frame_"))
        folder = out / path.parent.name
        folder.mkdir()
        np.save(folder / "stored_matrix_at_16.npy", matrix)
        np.save(folder / "stored_second_matrix.npy", info.second_matrix)
        rotation = matrix[:3, :3]
        row = {"id": rid, "bytes": path.stat().st_size, "record_counts": info.counts,
               "second_matrix_offset": info.second_matrix_offset,
               "matrix_at_16": matrix.tolist(), "second_matrix": info.second_matrix.tolist(),
               "translation_unit": args.unit, "source": "serialized_FrameInfo_bin",
               "rotation_orthogonality_max_error": float(np.max(np.abs(rotation.T @ rotation - np.eye(3)))),
               "rotation_determinant": float(np.linalg.det(rotation)),
               "camera_origin_in_scan_candidate": matrix[:3, 3].tolist(),
               "pose_stage": "unknown", "capture_timestamp": None}
        if markers is not None and info.records_24:
            local = np.frombuffer(info.records_24, "<f8").reshape(-1, 3)
            if not np.isfinite(local).all():
                raise ValueError(f"Nonfinite candidate marker coordinates in {path.parent.name}")
            inverse = np.linalg.inv(matrix)
            candidates = {"untransformed": local, "matrix_at_16": local @ rotation.T + matrix[:3, 3],
                          "inverse_matrix": local @ inverse[:3, :3].T + inverse[:3, 3]}
            for name, points in candidates.items():
                marker_candidates.setdefault(name, []).append(nearest_distances(points, markers, o3d))
        if args.transform_clouds:
            cloud = _read_ply_cloud(o3d, (path.parent / "cloud_camera.ply").resolve())
            points = np.asarray(cloud.points)
            if not len(points) or not np.isfinite(points).all():
                raise ValueError("Empty or nonfinite camera point cloud")
            sign = np.array([1, 1, args.optical_z_sign])
            world = (points * sign) @ rotation.T + matrix[:3, 3]
            colors = np.asarray(cloud.colors) if cloud.has_colors() else None
            write_cloud(folder / "cloud_scan_candidate.ply", world, colors, args.unit)
            merged.append(world)
            colors_merged.append(colors)
            row["cloud_points"] = len(points)
            row["optical_to_scan_candidate"] = (matrix @ np.diag([*sign, 1])).tolist()
            if reference is not None:
                inverse = np.linalg.inv(matrix)
                candidates = {"selected": world, "no_pose": points * sign,
                              "opposite_Z": (points * [1, 1, -args.optical_z_sign]) @ rotation.T + matrix[:3, 3],
                              "inverse_matrix": (points * sign) @ inverse[:3, :3].T + inverse[:3, 3]}
                for name, q in candidates.items():
                    cloud_candidates.setdefault(name, []).append(nearest_distances(q, reference, o3d))
        write_json(folder / "pose.json", row)
        rows.append(row)

    if merged:
        colors = np.concatenate(colors_merged) if all(x is not None for x in colors_merged) else None
        write_cloud(out / "combined_scan_candidate.ply", np.concatenate(merged), colors, args.unit)
    with (out / "poses.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["id", "unit", "camera_x", "camera_y", "camera_z"] + [f"m{r}{c}" for r in range(4) for c in range(4)])
        for row in rows:
            writer.writerow([row["id"], args.unit, *row["camera_origin_in_scan_candidate"],
                             *np.asarray(row["matrix_at_16"]).ravel()])
    report = {"frames": len(rows), "translation_unit": args.unit,
              "poses": rows, "marker_framework_check": {}, "reference_cloud_check": {},
              "limitations": ["Pose timestamps and tracking/optimization stage are unknown.",
                              "Camera origin is relative to the scan; turntable/object motion may affect its physical interpretation.",
                              "Optical Z reflection changes handedness; optical_to_scan_candidate is not an SO(3) rotation.",
                              "Candidate combined PLY concatenates transformed frames; it is not an independently fused or accuracy-validated surface.",
                              "Nearest-neighbour checks against vendor outputs are consistency checks, not independent geometric ground truth."]}
    for key, candidates in (("marker_framework_check", marker_candidates), ("reference_cloud_check", cloud_candidates)):
        for name, parts in candidates.items():
            distances = np.concatenate(parts)
            report[key][name] = distance_summary(distances, args.unit)
            if key == "marker_framework_check":
                threshold = 1 if args.unit == "mm" else .001
                report[key][name]["within_1mm"] = int((distances < threshold).sum())
    after = {path: sha256(Path(path)) for path in before}
    report["source_sha256"] = before
    report["source_unchanged"] = before == after
    write_json(out / "report.json", report)
    if before != after:
        raise RuntimeError("An input file changed during export")
    print(json.dumps({"frames": len(rows), "source_unchanged": True,
                      "marker_framework_check": report["marker_framework_check"],
                      "reference_cloud_check": report["reference_cloud_check"]}, indent=2))


if __name__ == "__main__":
    main()

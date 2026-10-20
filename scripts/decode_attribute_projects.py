"""Decode observed manifest-version 6.1 attribute tables to the frame contract.

The source app directory is read-only. Original JPEGs, opaque frame metadata,
local marker records and both saved pose stages are preserved separately.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reconstruction_probe.attribute_frames import (
    decode_attribute_depth, parse_attribute_markers, parse_attribute_pose, split_jpeg_attribute)
from reconstruction_probe.offline import file_sha256, open_scan_database


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def intrinsics_file(path):
    data = path.read_bytes()
    if len(data) != 40:
        raise ValueError("Unsupported camera matrix file")
    width, height = struct.unpack_from("<2H", data)
    K = np.frombuffer(data, "<f4", 9, 4).reshape(3, 3)
    if (not width or not height or not np.isfinite(K).all() or K[0, 0] <= 0 or K[1, 1] <= 0
            or not np.allclose(K[2], [0, 0, 1], rtol=0, atol=1e-6)):
        raise ValueError("Invalid camera matrix")
    return {"width": width, "height": height, "K": K.tolist()}


def decode_project(project, output, *, save_rgb=True):
    started = time.time()
    manifests = list(project.glob("*.revox"))
    if len(manifests) != 1:
        raise ValueError("Expected one native project manifest")
    manifest_path = manifests[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scan_id = "scan_" + manifest_path.stem
    target = output / scan_id
    target.mkdir(parents=True, exist_ok=False)
    files = sorted(p for p in project.rglob("*") if p.is_file())
    hashes = {str(p.resolve()): file_sha256(p) for p in files}
    calibration = {}
    for name in ("Pl", "Prgb"):
        path = project / "param" / (name + ".bin")
        if path.exists():
            calibration[name] = intrinsics_file(path)
    frames, errors, csv_rows = [], [], []
    marker_observations = 0
    marker_norms = []
    with open_scan_database(project / "cache/frames.dataset") as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError("Database integrity check: " + str(integrity))
        names = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        tables = {name: connection.execute('SELECT count(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
                  for name in names}
        if "FrameRGBD" in tables:
            raise ValueError("Legacy database: use decode_scan_projects.py")
        info = {r["id"]: bytes(r["data"]) for r in connection.execute("SELECT id,data FROM Frame_Attr_info")} if "Frame_Attr_info" in tables else {}
        stored = {r["id"]: bytes(r["data"]) for r in connection.execute("SELECT id,data FROM Frame_Attr_pose")} if "Frame_Attr_pose" in tables else {}
        optimized = {r["id"]: bytes(r["data"]) for r in connection.execute("SELECT id,data FROM table_pose_optimized")} if "table_pose_optimized" in tables else {}
        depth_ids = set()
        for row in connection.execute("SELECT id,version,data FROM Frame_Attr_rgbd ORDER BY id") if "Frame_Attr_rgbd" in tables else []:
            rid = row["id"]
            depth_ids.add(rid)
            folder = target / f"frame_{rid:010d}"
            folder.mkdir()
            item = {"id": rid, "unit": "mm", "depth_status": "error", "pose_status": "missing",
                    "pose_stage": "saved_attribute_stage_not_physically_verified", "capture_timestamp": None,
                    "optimized_pose_available": rid in optimized}
            try:
                if row["version"] != 1:
                    raise ValueError("Unsupported depth attribute row version")
                decoded = decode_attribute_depth(row["data"])
                arrays = {"depth_mm": decoded.depth_mm}
                if decoded.rgba is not None:
                    arrays["rgba"] = decoded.rgba
                    arrays["color_layout_version"] = np.array(2, np.uint32)
                np.savez_compressed(folder / "frame.npz", **arrays)
                z = decoded.depth_mm[decoded.depth_mm > 0]
                item.update(depth_status="decoded", width=decoded.depth_mm.shape[1], height=decoded.depth_mm.shape[0],
                            points=len(z), embedded_rgba=decoded.rgba is not None,
                            depth_min_mm=float(z.min()) if len(z) else None,
                            depth_max_mm=float(z.max()) if len(z) else None,
                            attribute_depth_header_hex=bytes(row["data"][:20]).hex())
            except ValueError as exc:
                (folder / "unrecognized_depth_attribute.bin").write_bytes(row["data"])
                item["depth_error"] = str(exc)
                errors.append({"id": rid, "stage": "depth", "error": str(exc)})
            if rid in info:
                (folder / "frame_info_attribute.bin").write_bytes(info[rid])
            for name, rows, basename in (("stored", stored, "frame_pose_attribute.bin"),
                                          ("optimized", optimized, "frame_pose_optimized_attribute.bin")):
                if rid not in rows:
                    continue
                blob = rows[rid]
                (folder / basename).write_bytes(blob)
                try:
                    pose = parse_attribute_pose(blob)
                    np.save(folder / f"pose_{name}.npy", pose)
                    csv_rows.append([rid, name, "mm", *pose.ravel()])
                    if name == "stored":
                        item.update(pose_status="parsed", pose_layout="attribute_132")
                    else:
                        item["optimized_pose_status"] = "parsed"
                except ValueError as exc:
                    item[f"{name}_pose_error"] = str(exc)
                    errors.append({"id": rid, "stage": name + "_pose", "error": str(exc)})
            if "Frame_Attr_rgb" in tables:
                color = connection.execute("SELECT version,data FROM Frame_Attr_rgb WHERE id=?", (rid,)).fetchone()
                if color is not None:
                    blob = bytes(color["data"])
                    try:
                        if color["version"] != 1:
                            raise ValueError("Unsupported RGB attribute row version")
                        jpeg = split_jpeg_attribute(blob)
                        with Image.open(io.BytesIO(jpeg)) as image:
                            rgb_size = list(image.size)
                            image.verify()
                        if save_rgb:
                            (folder / "rgb_original.jpg").write_bytes(jpeg)
                        item.update(rgb_status="jpeg_container_verified", rgb_size=rgb_size,
                                    rgb_original_saved=save_rgb, rgb_original_sha256=hashlib.sha256(jpeg).hexdigest())
                    except (ValueError, OSError) as exc:
                        (folder / "rgb_attribute_unrecognized.bin").write_bytes(blob)
                        item["rgb_status"] = "unrecognized"
                        errors.append({"id": rid, "stage": "rgb", "error": str(exc)})
            if "Frame_Attr_marker" in tables:
                marker = connection.execute("SELECT version,data FROM Frame_Attr_marker WHERE id=?", (rid,)).fetchone()
                if marker is not None:
                    blob = bytes(marker["data"])
                    (folder / "marker_attribute.bin").write_bytes(blob)
                    try:
                        if marker["version"] != 1:
                            raise ValueError("Unsupported marker attribute row version")
                        parsed = parse_attribute_markers(blob)
                        np.savez_compressed(folder / "markers.npz", xyz_camera_mm=parsed.xyz,
                            direction_candidate=parsed.direction_candidate, raw_records=parsed.raw_records)
                        item.update(marker_status="parsed", marker_count=len(parsed.xyz))
                        marker_observations += len(parsed.xyz)
                        marker_norms.extend(np.linalg.norm(parsed.direction_candidate, axis=1).tolist())
                    except ValueError as exc:
                        item["marker_status"] = "unrecognized"
                        errors.append({"id": rid, "stage": "markers", "error": str(exc)})
            write_json(folder / "frame.json", item)
            frames.append(item)
            if len(frames) % 100 == 0:
                print(f"{scan_id}: {len(frames)}/{tables['Frame_Attr_rgbd']} frames", flush=True)
        # Keep pose records without a depth record, if a future project has any.
        for name, rows in (("stored", stored), ("optimized", optimized)):
            for rid in sorted(set(rows) - depth_ids):
                folder = target / "pose_only" / f"frame_{rid:010d}"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"pose_{name}_attribute.bin").write_bytes(rows[rid])
                try:
                    matrix = parse_attribute_pose(rows[rid])
                    np.save(folder / f"pose_{name}.npy", matrix)
                    csv_rows.append([rid, name + "_pose_only", "mm", *matrix.ravel()])
                except ValueError as exc:
                    errors.append({"id": rid, "stage": name + "_pose_only", "error": str(exc)})
        global_records = []
        if "table_global_markers" in tables:
            for row in connection.execute("SELECT * FROM table_global_markers ORDER BY id"):
                blob = bytes(row["data"])
                path = target / f"global_markers_{row['id']}"
                path.with_suffix(".bin").write_bytes(blob)
                parsed = parse_attribute_markers(blob, global_frame=True)
                if len(parsed.xyz) != row["count"]:
                    raise ValueError("Global marker count mismatch")
                np.savez_compressed(path.with_suffix(".npz"), xyz_scan_mm=parsed.xyz,
                    direction_candidate=parsed.direction_candidate, raw_records=parsed.raw_records)
                mkf = project / "marker_framework.mkf"
                global_records.append({"row_id": row["id"], "count": len(parsed.xyz),
                    "framework_file_equal": mkf.read_bytes() == blob if mkf.exists() else None})
        framework = project / "marker_framework.mkf"
        if framework.exists():
            blob = framework.read_bytes()
            parsed = parse_attribute_markers(blob, global_frame=True)
            (target / "marker_framework_original.mkf").write_bytes(blob)
            np.savez_compressed(target / "marker_framework.npz", xyz_scan_mm=parsed.xyz,
                direction_candidate=parsed.direction_candidate, raw_records=parsed.raw_records)
    with (target / "poses.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["id", "kind", "unit"] + [f"m{r}{c}" for r in range(4) for c in range(4)])
        writer.writerows(csv_rows)
    unchanged = all(file_sha256(Path(p)) == value for p, value in hashes.items())
    if not unchanged:
        raise RuntimeError("Source project changed during read; do not treat this as a stable snapshot")
    safe_scan = {k: v for k, v in manifest.get("scan", {}).items()
                 if not any(word in k.lower() for word in ("serial", "sn"))}
    report = {"scan_id": scan_id, "source_directory": str(project.resolve()), "source_manifest": manifest_path.name,
        "manifest_version": manifest.get("version"), "database_layout": "attribute_tables_FrameVersion_2",
        "manifest_scan": safe_scan, "intrinsics": calibration, "table_counts": tables,
        "integrity_check": integrity, "optical_to_pose_axes": [1, 1, 1],
        "coordinate_convention_evidence": "Validated sample projections against native raw_preview and local markers against saved global marker coordinates; no Y/Z flip for this observed format.",
        "color_layout_version": 2,
        "color_convention": {"embedded_bytes": "A,B,G,R", "decoded_array": "R,G,B,A",
            "original_jpeg": "Preserved verbatim; standard RGB decoding requires an R/B swap for physical color in this cohort.",
            "evidence": "Native PLY colors plus user-confirmed blue bow on 12:26:07 figure. JPEG agreement alone was insufficient."},
        "frames": frames, "errors": errors, "source_hashes_before": hashes, "source_unchanged": unchanged,
        "global_marker_records": global_records, "status": {
            "depth_decoded": sum(f["depth_status"] == "decoded" for f in frames),
            "poses_parsed": sum(f["pose_status"] == "parsed" for f in frames),
            "optimized_poses_parsed": sum(f.get("optimized_pose_status") == "parsed" for f in frames),
            "valid_depth_points": sum(f.get("points", 0) for f in frames),
            "colored_depth_frames": sum(f.get("embedded_rgba", False) for f in frames),
            "jpeg_frames": sum(f.get("rgb_status") == "jpeg_container_verified" for f in frames),
            "marker_observations": marker_observations},
        "marker_direction_length_range": [float(min(marker_norms)), float(max(marker_norms))] if marker_norms else None,
        "elapsed_seconds": time.time() - started,
        "limitations": ["Only stored records are recovered; physical frame completeness is unknown.",
            "Optimized-table membership is preserved; missing entries are not labeled invalid without documented semantics.",
            "Opaque 75-byte frame-info attributes are preserved without inventing status flags or timestamps.",
            "Marker record tails are retained without assigning IDs, confidence or radius semantics.",
            "JPEG container verification is not full pixel decoding of every image.",
            "Source camera/object motion remains relative, especially with turntable capture."]}
    write_json(target / "index.json", report)
    print(json.dumps({"scan": scan_id, "status": report["status"], "errors": len(errors), "source_unchanged": unchanged}, ensure_ascii=False), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prefix", default="20261018", help="Native manifest filename stem prefix")
    parser.add_argument("--projects", nargs="+", help="Selected native manifest stems")
    parser.add_argument("--no-rgb-files", action="store_true", help="Keep aligned color, verify JPEG containers, omit separate JPEG copies")
    args = parser.parse_args()
    source, output = args.input.resolve(), args.out.resolve()
    if source == output or source in output.parents or output in source.parents:
        parser.error("Write outputs outside the original source directory tree")
    if output.exists() and any(output.iterdir()):
        parser.error("Use a new or empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    manifests = sorted(source.glob("*/*.revox"), key=lambda p: p.stem)
    manifests = [p for p in manifests if p.stem.startswith(args.prefix) and (not args.projects or p.stem in args.projects)]
    if not manifests:
        parser.error("No selected native project manifests")
    summaries = []
    for path in manifests:
        report = decode_project(path.parent, output, save_rgb=not args.no_rgb_files)
        summaries.append({k: report[k] for k in ("scan_id", "source_directory", "status", "errors", "source_unchanged", "table_counts", "elapsed_seconds")})
        write_json(output / "summary.json", summaries)


if __name__ == "__main__":
    main()

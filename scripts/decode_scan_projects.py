"""Recover every stored frame from the local offline projects, without SDKs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reconstruction_probe.offline import decode_sparse_depth, file_sha256, open_scan_database, read_global_registration_poses
from reconstruction_probe.poses import parse_compact_frame_pose, parse_frame_info_blob


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def decode_project(scan, out, scan_id):
    db = scan / "cache" / "frames.dataset"
    manifest_path = next(scan.glob("*.revox"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = [p for p in scan.rglob("*") if p.is_file()]
    before = {str(p.resolve()): file_sha256(p) for p in paths}
    global_file = scan / "cache" / "global_register_pose.pose"
    global_poses = read_global_registration_poses(global_file) if global_file.exists() else {}
    out.mkdir(parents=True, exist_ok=False)
    intrinsics = {}
    for name in ("Pl", "Prgb"):
        data = (scan / "param" / (name + ".bin")).read_bytes()
        if len(data) != 40:
            raise ValueError("Unsupported camera matrix layout")
        w, h = struct.unpack_from("<2H", data)
        intrinsics[name] = {"width": w, "height": h, "K": np.frombuffer(data, "<f4", 9, 4).reshape(3, 3).tolist()}
    frames, errors = [], []
    with open_scan_database(db) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError("Database integrity check failed: " + integrity)
        info_rows = {r["id"]: dict(r) for r in connection.execute("SELECT * FROM FrameInfo")}
        table_counts = {name: connection.execute("SELECT count(*) FROM " + name).fetchone()[0]
                        for name in ("FrameRGBD", "FrameInfo", "FrameColor")}
        for row in connection.execute("SELECT * FROM FrameRGBD ORDER BY id"):
            rid = row["id"]
            folder = out / f"frame_{rid:010d}"
            folder.mkdir()
            item = {"id": rid, "unit": "mm", "width": row["width"], "height": row["height"],
                    "depth_version": row["version"], "depth_type": row["type"],
                    "pose_status": "missing", "pose_stage": "unknown",
                    "capture_timestamp": None, "global_pose_available": rid in global_poses}
            try:
                if row["version"] != 0:
                    raise ValueError("Unsupported RGBD version")
                decoded = decode_sparse_depth(row["data"], row["width"], row["height"])
                arrays = {"depth_mm": decoded.depth_mm}
                if decoded.rgba is not None:
                    arrays["rgba"] = decoded.rgba
                np.savez_compressed(folder / "frame.npz", **arrays)
                depth = decoded.depth_mm[decoded.depth_mm > 0]
                item.update(depth_status="decoded", points=len(depth), embedded_rgba=decoded.rgba is not None,
                            depth_min_mm=float(depth.min()) if len(depth) else None,
                            depth_max_mm=float(depth.max()) if len(depth) else None,
                            depth_median_mm=float(np.median(depth)) if len(depth) else None)
            except Exception as exc:
                item["depth_status"] = "error"
                item["depth_error"] = str(exc)
                errors.append({"id": rid, "stage": "depth", "error": str(exc)})
            info = info_rows.get(rid)
            if info:
                blob = info.get("bin") or b""
                (folder / "frame_info_bin.bin").write_bytes(blob)
                item["frame_info_bytes"] = len(blob)
                item["opaque_header_hex"] = blob[:16].hex()
                item["opaque_tail_hex"] = blob[144:].hex() if len(blob) == 164 else None
                item["source_columns"] = {k: v for k, v in info.items() if not isinstance(v, bytes)}
                try:
                    pose = parse_compact_frame_pose(blob) if len(blob) == 164 else parse_frame_info_blob(blob)
                    np.save(folder / "pose_stored.npy", pose.matrix_at_16)
                    item["pose_status"] = "parsed"
                    item["pose_layout"] = "compact_164" if len(blob) == 164 else "counted_arrays"
                except Exception as exc:
                    item["pose_status"] = "unsupported_or_invalid"
                    item["pose_error"] = str(exc)
                    errors.append({"id": rid, "stage": "pose", "error": str(exc)})
            if rid in global_poses:
                np.save(folder / "pose_global_registration.npy", global_poses[rid])
            write_json(folder / "frame.json", item)
            frames.append(item)
            if len(frames) % 100 == 0:
                print(f"{scan_id}: {len(frames)}/{table_counts['FrameRGBD']} frames", flush=True)
    # Preserve pose-only rows explicitly rather than silently dropping them.
    depth_ids = {item["id"] for item in frames}
    extra_info = []
    for rid, row in sorted(info_rows.items()):
        if rid in depth_ids:
            continue
        blob = row.get("bin") or b""
        folder = out / "pose_only" / f"frame_{rid:010d}"
        folder.mkdir(parents=True)
        (folder / "frame_info_bin.bin").write_bytes(blob)
        item = {"id": rid, "bytes": len(blob)}
        try:
            parsed = parse_compact_frame_pose(blob) if len(blob) == 164 else parse_frame_info_blob(blob)
            np.save(folder / "pose_stored.npy", parsed.matrix_at_16)
            item["pose_status"] = "parsed"
        except Exception as exc:
            item.update(pose_status="unsupported_or_invalid", error=str(exc))
        extra_info.append(item)
    with (out / "poses.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["id", "kind", "unit"] + [f"m{r}{c}" for r in range(4) for c in range(4)])
        for item in frames:
            for kind, name in (("stored", "pose_stored.npy"), ("global_registration_file", "pose_global_registration.npy")):
                file = out / f"frame_{item['id']:010d}" / name
                if file.exists():
                    writer.writerow([item["id"], kind, "mm", *np.load(file).ravel()])
        for item in extra_info:
            file = out / "pose_only" / f"frame_{item['id']:010d}" / "pose_stored.npy"
            if file.exists():
                writer.writerow([item["id"], "stored_pose_only", "mm", *np.load(file).ravel()])
    after = {path: file_sha256(Path(path)) for path in before}
    if before != after:
        raise RuntimeError("Source files changed during recovery")
    scan_values = {k: v for k, v in manifest.get("scan", {}).items() if "sn" not in k.lower() and "serial" not in k.lower()}
    result = {"scan_id": scan_id, "source_directory": str(scan.resolve()), "source_manifest": manifest_path.name,
              "manifest_version": manifest.get("version"), "manifest_scan": scan_values,
              "table_counts": table_counts, "integrity_check": integrity, "intrinsics": intrinsics,
              "frames": frames, "pose_only_rows": extra_info,
              "status": {"depth_decoded": sum(r["depth_status"] == "decoded" for r in frames),
                         "poses_parsed": sum(r["pose_status"] == "parsed" for r in frames),
                         "pose_only_parsed": sum(r["pose_status"] == "parsed" for r in extra_info),
                         "total_stored_poses_parsed": sum(r["pose_status"] == "parsed" for r in frames + extra_info),
                         "global_registration_poses": len(global_poses),
                         "valid_depth_points": sum(r.get("points", 0) for r in frames)},
              "errors": errors, "source_hashes_before": before, "source_unchanged": True,
              "limitations": ["Only stored database records are recovered; physical frame retention is not established.",
                              "FrameInfo flags, timestamps and pose optimization stage are not inferred from opaque fields.",
                              "Embedded color is preserved bytewise; no separate original RGB images exist in FrameColor.",
                              "Projection and world-coordinate conventions require geometric validation before reconstruction."]}
    write_json(out / "index.json", result)
    print(scan_id + ": " + json.dumps(result["status"]), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("item"))
    parser.add_argument("--out", type=Path, default=Path("reports/four-scans/decoded"))
    args = parser.parse_args()
    source, out = args.input.resolve(), args.out.resolve()
    if source == out or source in out.parents or out in source.parents:
        parser.error("Output must be separate from the original input tree")
    if out.exists() and any(out.iterdir()):
        parser.error("Output must be new or empty")
    projects = []
    for directory in sorted(source.iterdir(), key=lambda p: (p.name != "share", p.name)):
        if directory.is_dir():
            projects.extend(sorted(p.parent.parent for p in directory.rglob("frames.dataset")))
    if not projects:
        parser.error("No original scan database found")
    out.mkdir(parents=True, exist_ok=True)
    summaries = []
    for number, scan in enumerate(projects, 1):
        key = f"scan_{number:02d}"
        report = decode_project(scan, out / key, key)
        summaries.append({"scan_id": key, "source": str(scan), "status": report["status"],
                          "table_counts": report["table_counts"], "errors": report["errors"],
                          "source_unchanged": report["source_unchanged"]})
    write_json(out / "summary.json", summaries)


if __name__ == "__main__":
    main()

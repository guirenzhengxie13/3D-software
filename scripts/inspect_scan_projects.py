"""Inventory offline Revo Scan projects without modifying their source files.

Only a temporary database copy receives the SQLite signature restoration.
The observed global-registration pose format is validated structurally and
against FrameInfo IDs; its coordinate meaning remains a geometry concern.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile

import numpy as np


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


@contextmanager
def database(source):
    with tempfile.TemporaryDirectory(prefix="revo_metadata_") as folder:
        target = Path(folder) / "frames.sqlite"
        shutil.copyfile(source, target)
        with target.open("r+b") as stream:
            signature = stream.read(16)
            if signature == b"RPAlgo_file_sys\0":
                stream.seek(0)
                stream.write(b"SQLite format 3\0")
            elif signature != b"SQLite format 3\0":
                raise ValueError("Unsupported database signature")
        con = sqlite3.connect(target.as_uri() + "?mode=ro&immutable=1", uri=True)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


def scalar(value):
    if isinstance(value, bytes):
        return {"blob_bytes": len(value), "head_hex": value[:16].hex()}
    return value


def rigid_stats(matrix):
    if not np.isfinite(matrix).all():
        return {"valid_rigid": False, "reason": "nonfinite"}
    rotation = matrix[:3, :3]
    error = float(np.max(np.abs(rotation.T @ rotation - np.eye(3))))
    determinant = float(np.linalg.det(rotation))
    row_error = float(np.max(np.abs(matrix[3] - [0, 0, 0, 1])))
    return {"valid_rigid": error <= 1e-4 and abs(determinant - 1) <= 1e-4 and row_error <= 1e-4,
            "orthogonality_max_error": error, "determinant": determinant,
            "homogeneous_row_max_error": row_error}


def id_summary(ids):
    groups = {}
    for value in sorted(ids):
        groups.setdefault(value >> 32, []).append(value & 0xFFFFFFFF)
    return {"count": len(ids), "high_word_groups": [
        {"high_word": high, "count": len(low), "low_min": min(low), "low_max": max(low),
         "low_consecutive_difference_counts": dict(Counter(b - a for a, b in zip(low, low[1:])))}
        for high, low in groups.items()]}


def global_poses(path, frame_info):
    data = path.read_bytes()
    if len(data) < 4:
        raise ValueError("Truncated global registration pose header")
    count = struct.unpack_from("<I", data)[0]
    if count > 1_000_000 or len(data) != 4 + count * 136:
        raise ValueError("Unsupported global registration pose record length")
    rows, translation_differences, rotation_differences = [], [], []
    seen = set()
    for index in range(count):
        offset = 4 + 136 * index
        high, low = struct.unpack_from("<2I", data, offset)
        rid = (high << 32) | low
        if rid in seen:
            raise ValueError("Duplicate global registration pose ID")
        seen.add(rid)
        matrix = np.frombuffer(data, "<f8", count=16, offset=offset + 8).reshape(4, 4)
        stats = rigid_stats(matrix)
        if not stats["valid_rigid"]:
            raise ValueError(f"Invalid global registration matrix for ID {rid}")
        row = {"id": rid, "id_high_word": high, "id_low_word": low,
               "matrix": matrix.tolist(), **stats}
        if rid in frame_info:
            stored = frame_info[rid]
            difference = float(np.linalg.norm(matrix[:3, 3] - stored[:3, 3]))
            relative_rotation = matrix[:3, :3] @ stored[:3, :3].T
            angle = float(np.degrees(np.arccos(np.clip((np.trace(relative_rotation) - 1) / 2, -1, 1))))
            translation_differences.append(difference)
            rotation_differences.append(angle)
            row["stored_translation_difference_source_units"] = difference
            row["stored_rotation_difference_degrees"] = angle
        rows.append(row)
    return {"bytes": len(data), "count": count, "ids_match_FrameInfo": seen == set(frame_info),
            "layout": "u32 count; records: u32 high-word, u32 low-word, 16 little-endian float64 row-major",
            "translation_units": "unchanged source units; not inferred by inventory",
            "stage": "separate global-registration candidate inferred from filename; no documented optimization flag",
            "max_rotation_orthogonality_error": max((r["orthogonality_max_error"] for r in rows), default=0),
            "stored_translation_difference_median": float(np.median(translation_differences)) if translation_differences else None,
            "stored_translation_difference_max": max(translation_differences, default=None),
            "stored_rotation_difference_degrees_median": float(np.median(rotation_differences)) if rotation_differences else None,
            "stored_rotation_difference_degrees_max": max(rotation_differences, default=None),
            "poses": rows}


def inspect_project(db, scan_id):
    project = db.parent.parent
    manifests = list(project.glob("*.revox"))
    manifest_path = manifests[0] if len(manifests) == 1 else None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path else {}
    scan = manifest.get("scan", {})
    serial = scan.pop("scanner_sn", None)
    if serial:
        scan["scanner_sn_sha256"] = hashlib.sha256(serial.encode()).hexdigest()
    watched = [db, *manifests, *project.glob("process.log"), *project.glob("cache/*.pose")]
    before = {str(p): digest(p) for p in watched}
    report = {"scan_id": scan_id, "project": str(project), "manifest": manifest,
              "manifest_file": str(manifest_path) if manifest_path else None,
              "source_sha256": before, "tables": {}, "FrameInfo_bin": {}, "global_registration": None}
    if (project / "process.log").exists():
        report["process_log"] = {"bytes": (project / "process.log").stat().st_size,
                                 "content": (project / "process.log").read_text(encoding="utf-8", errors="replace")}
    matrices, all_ids, headers, tails, lengths, rigid_errors = {}, {}, Counter(), Counter(), Counter(), []
    with database(db) as con:
        for table in con.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"):
            name = table["name"]
            table_id = identifier(name)
            columns = [row[1] for row in con.execute(f"PRAGMA table_info({table_id})")]
            count = con.execute(f"SELECT count(*) FROM {table_id}").fetchone()[0]
            entry = {"schema": table["sql"], "count": count, "columns": columns,
                     "nonnull": {col: con.execute(f"SELECT count({identifier(col)}) FROM {table_id}").fetchone()[0] for col in columns}}
            if "id" in columns:
                ids = {row[0] for row in con.execute(f"SELECT id FROM {table_id}")}
                all_ids[name] = ids
                entry["ids"] = id_summary(ids)
            if name == "FrameRGBD":
                entry["groups"] = [dict(row) for row in con.execute(
                    "SELECT version,type,width,height,count(*) AS count,min(length(data)) AS min_bytes,max(length(data)) AS max_bytes FROM FrameRGBD GROUP BY version,type,width,height")]
            if name == "FrameInfo":
                entry["flag_values"] = {col: [{"value": scalar(row[0]), "count": row[1]} for row in con.execute(
                    f"SELECT {identifier(col)},count(*) FROM {table_id} GROUP BY {identifier(col)}")]
                    for col in ("version", "seqId", "droped", "gapRGB", "optimized", "markerCount") if col in columns}
                for row in con.execute("SELECT id,bin FROM FrameInfo"):
                    data = row["bin"] or b""
                    lengths[len(data)] += 1
                    headers[data[:16].hex()] += 1
                    tails[data[144:].hex()] += 1
                    if len(data) >= 144:
                        matrix = np.frombuffer(data, "<f8", count=16, offset=16).reshape(4, 4)
                        stats = rigid_stats(matrix)
                        if stats["valid_rigid"]:
                            matrices[row["id"]] = matrix.copy()
                            rigid_errors.append(stats["orthogonality_max_error"])
            report["tables"][name] = entry
    rgbd_ids, info_ids = all_ids.get("FrameRGBD", set()), all_ids.get("FrameInfo", set())
    report["FrameInfo_bin"] = {"length_counts": dict(lengths), "header_counts": dict(headers),
                               "tail_after_matrix_counts": dict(tails), "rigid_matrices_at_16": len(matrices),
                               "max_rotation_orthogonality_error": max(rigid_errors, default=None),
                               "geometry_semantics": "matrix present; transform direction/axes need geometric validation"}
    report["frame_alignment"] = {"FrameInfo_without_RGBD": sorted(info_ids - rgbd_ids),
                                 "RGBD_without_FrameInfo": sorted(rgbd_ids - info_ids),
                                 "manifest_vf_count": scan.get("vf_count"),
                                 "note": "Manifest vf_count differs from saved frame counts. This does not establish which physical sensor frames were retained or dropped."}
    global_path = project / "cache" / "global_register_pose.pose"
    if global_path.exists():
        report["global_registration"] = global_poses(global_path, matrices)
    after = {str(p): digest(p) for p in watched}
    report["source_unchanged"] = before == after
    if before != after:
        raise RuntimeError("A source input changed during inspection")
    return report


def share_order(path):
    name = path.parents[2].name
    return 0 if name == "share" else int(name.removeprefix("share(").removesuffix(")"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", type=Path, default=Path("item"))
    parser.add_argument("--out", type=Path, default=Path("reports/four-scans"))
    args = parser.parse_args()
    item, out = args.item.resolve(), args.out.resolve()
    if item == out or item in out.parents or out in item.parents:
        parser.error("Output must be separate from source item directory")
    files = sorted(item.glob("share*/*/cache/frames.dataset"), key=share_order)
    if not files:
        parser.error("No scan project databases found")
    out.mkdir(parents=True, exist_ok=True)
    summaries = []
    for index, db in enumerate(files, start=1):
        report = inspect_project(db, f"scan_{index:02d}")
        write_json(out / f"metadata_{index:02d}.json", report)
        summary = {"scan_id": report["scan_id"], "project": report["project"],
                   "manifest_vf_count": report["frame_alignment"]["manifest_vf_count"],
                   "table_counts": {name: entry["count"] for name, entry in report["tables"].items()},
                   "matrix_at_16_count": report["FrameInfo_bin"]["rigid_matrices_at_16"],
                   "global_registration_count": report["global_registration"]["count"] if report["global_registration"] else 0,
                   "FrameInfo_without_RGBD": report["frame_alignment"]["FrameInfo_without_RGBD"],
                   "source_unchanged": report["source_unchanged"]}
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=True))
    write_json(out / "metadata_summary.json", summaries)


if __name__ == "__main__":
    main()

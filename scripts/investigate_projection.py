"""Read-only calibration consistency experiment for the supplied four scans.

Reference PLYs are only used to compare coordinate conventions. They are not
used as reconstruction inputs or independent geometric ground truth.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import sqlite3
import struct
import sys
import tempfile

import numpy as np
import open3d as o3d

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reconstruction_probe.sources import _read_ply_cloud


@contextmanager
def database(path):
    with tempfile.TemporaryDirectory(prefix="revo_projection_") as directory:
        copied = Path(directory) / "frames.sqlite"
        shutil.copyfile(path, copied)
        with copied.open("r+b") as stream:
            magic = stream.read(16)
            if magic == b"RPAlgo_file_sys\x00":
                stream.seek(0)
                stream.write(b"SQLite format 3\x00")
            elif magic != b"SQLite format 3\x00":
                raise ValueError("Unsupported signature")
        con = sqlite3.connect(copied.as_uri() + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()


def camera_models(scan):
    blob = (scan / "param" / "Pl.bin").read_bytes()
    width, height = struct.unpack_from("<2H", blob)
    K = np.frombuffer(blob, "<f4", 9, 4).reshape(3, 3).astype(float)
    map_blob = (scan / "param" / "mapparamL.bin").read_bytes()
    values = np.frombuffer(map_blob, "<f4", offset=12)
    raw_K = np.array([[values[11], 0, values[9]], [0, values[12], values[10]], [0, 0, 1]])
    ray_matrix = values[25:34].reshape(3, 3).astype(float)
    rotation = ray_matrix @ K
    return {
        "calibration_size": [width, height], "Pl_K": K.tolist(), "raw_K": raw_K.tolist(),
        "map_ray_matrix": ray_matrix.tolist(), "map_rotation_from_rectified": rotation.tolist(),
        "map_rotation_orthogonality_error": float(np.max(np.abs(rotation.T @ rotation - np.eye(3)))),
        "map_rotation_determinant": float(np.linalg.det(rotation)),
    }


def decode_samples(blob, max_points=5000):
    width, height, count, kind = struct.unpack_from("<4I", blob)
    bitmap_bytes = (width * height + 7) // 8
    if len(blob) != 16 + bitmap_bytes + count * (8 if kind else 4):
        raise ValueError("Unknown sparse layout")
    bitmap = np.unpackbits(np.frombuffer(blob, np.uint8, bitmap_bytes, 16), bitorder="little")
    ids = np.flatnonzero(bitmap[:width * height])
    if len(ids) != count:
        raise ValueError("Bitmap mismatch")
    depth = np.frombuffer(blob, "<f4", count, 16 + bitmap_bytes)
    selected = np.linspace(0, count - 1, min(count, max_points), dtype=int)
    return width, height, ids[selected], depth[selected]


def point_candidates(width, height, ids, depth, calibration):
    v, u = np.divmod(ids, width)
    cw, ch = calibration["calibration_size"]
    pixels = np.column_stack((u * cw / width, v * ch / height, np.ones(len(u))))
    matrices = {
        "Pl": np.linalg.inv(calibration["Pl_K"]),
        "raw_K": np.linalg.inv(calibration["raw_K"]),
        "map_ray_normalized": np.array(calibration["map_ray_matrix"]),
        "map_ray_unnormalized": np.array(calibration["map_ray_matrix"]),
    }
    candidates = {}
    for name, matrix in matrices.items():
        rays = pixels @ matrix.T
        if name != "map_ray_unnormalized":
            rays = rays / rays[:, 2:3]
        candidates[name] = rays * depth[:, None]
    return candidates


def global_poses(path):
    if not path.exists():
        return {}
    blob = path.read_bytes()
    count = struct.unpack_from("<I", blob)[0]
    if len(blob) != 4 + 136 * count:
        raise ValueError("Unsupported global pose layout")
    result = {}
    for index in range(count):
        offset = 4 + 136 * index
        high, low = struct.unpack_from("<2I", blob, offset)
        result[(high << 32) | low] = np.frombuffer(blob, "<f8", 16, offset + 8).reshape(4, 4).copy()
    return result


def cloud(points):
    result = o3d.geometry.PointCloud()
    result.points = o3d.utility.Vector3dVector(np.asarray(points, dtype=float))
    return result


def stats(values):
    return {"median_mm": float(np.median(values)), "p90_mm": float(np.percentile(values, 90)),
            "mean_mm": float(values.mean()), "within_1mm": float((values <= 1).mean()),
            "within_2mm": float((values <= 2).mean())}


def investigate(scan, frame_samples=9):
    calibration = camera_models(scan)
    references = {}
    for name, path in (("fuse", scan / "pointclouds" / "fuse.ply"), ("raw_preview", scan / "raw_preview.ply")):
        if path.exists():
            reference = _read_ply_cloud(o3d, path.resolve()).voxel_down_sample(0.5)
            references[name] = reference
    candidates = {}
    with database(scan / "cache" / "frames.dataset") as con:
        ids = [row[0] for row in con.execute("SELECT id FROM FrameRGBD ORDER BY id")]
        selected = [ids[i] for i in np.linspace(0, len(ids) - 1, min(len(ids), frame_samples), dtype=int)]
        for rid in selected:
            rgbd = con.execute("SELECT * FROM FrameRGBD WHERE id=?", (rid,)).fetchone()
            frame_info = con.execute("SELECT bin FROM FrameInfo WHERE id=?", (rid,)).fetchone()
            if frame_info is None:
                continue
            pose = np.frombuffer(frame_info[0], "<f8", 16, 16).reshape(4, 4)
            for name, points in point_candidates(*decode_samples(rgbd["data"]), calibration).items():
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        for sz in (-1, 1):
                            signed = points * [sx, sy, sz]
                            for direction, matrix in (("forward", pose), ("inverse", np.linalg.inv(pose))):
                                world = signed @ matrix[:3, :3].T + matrix[:3, 3]
                                key = f"{name}:sign{sx},{sy},{sz}:{direction}"
                                candidates.setdefault(key, []).append(world)
    scores = {}
    for name, parts in candidates.items():
        merged = cloud(np.concatenate(parts))
        scores[name] = {ref: stats(np.asarray(merged.compute_point_cloud_distance(reference)))
                        for ref, reference in references.items()}
    ranked = sorted(scores, key=lambda key: scores[key]["fuse" if "fuse" in references else "raw_preview"]["median_mm"])
    return {"source_scan": str(scan), "sampled_frame_ids": selected, "calibration": calibration,
            "reference_points": {name: len(value.points) for name, value in references.items()},
            "ranked_candidates": [{"candidate": name, "scores": scores[name]} for name in ranked],
            "limitations": ["Vendor PLY agreement only tests internal consistency, not absolute accuracy.",
                            "The sampled-frame search does not establish support for other devices or encodings."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", type=Path, default=Path("item"))
    parser.add_argument("--out", type=Path, default=Path("reports/four-scans/reconstruction"))
    parser.add_argument("--samples", type=int, default=9)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for index, path in enumerate(sorted(args.item.glob("share*/*/cache/frames.dataset")), 1):
        result = investigate(path.parent.parent, args.samples)
        (args.out / f"scan_{index:02d}_projection.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"scan": index, "best": result["ranked_candidates"][:3]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

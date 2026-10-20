"""Analyze saved relative poses without treating them as physical camera paths."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reconstruction_probe.turntable import diagnose_fixed_axis


def load_poses(scan, mode):
    index = json.loads((scan / "index.json").read_text(encoding="utf-8"))
    ids, matrices, sources, missing = [], [], [], []
    digest = hashlib.sha256()
    for record in sorted(index["frames"], key=lambda row: row["id"]):
        folder = scan / f"frame_{record['id']:010d}"
        global_path = folder / "pose_global_registration.npy"
        if not global_path.exists() and (folder / "pose_optimized.npy").exists():
            global_path = folder / "pose_optimized.npy"
        stored_path = folder / "pose_stored.npy"
        path = global_path if mode == "global" or (mode == "auto" and global_path.is_file()) else stored_path
        if not path.is_file():
            missing.append(record["id"])
            continue
        matrix = np.load(path, allow_pickle=False)
        digest.update(str(record["id"]).encode("ascii") + b"\0" + matrix.astype("<f8").tobytes())
        ids.append(record["id"])
        matrices.append(matrix)
        sources.append(path.name)
    return index, ids, matrices, sources, missing, digest.hexdigest()


def render(arrays, scan_id, output):
    canvas = Image.new("RGB", (1500, 920), (19, 27, 38))
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 16), f"{scan_id}: relative camera origins in scan/object coordinates", fill=(240, 240, 240))
    draw.text((20, 42), "NOT a measured physical camera path. Model fit is diagnostic only.", fill=(255, 194, 112))
    points, model = arrays["camera_origins_mm"], arrays["model_camera_origins_mm"]
    colors = [(int(75 + 170 * f), int(180 - 60 * f), int(235 - 125 * f))
              for f in np.linspace(0, 1, len(points))]
    for k, (a, b) in enumerate(((0, 1), (0, 2), (1, 2))):
        x0, y0, w, h = k * 500 + 20, 105, 455, 385
        draw.rectangle((x0, y0, x0 + w, y0 + h), outline=(65, 85, 105))
        draw.text((x0, y0 - 22), ("XY", "XZ", "YZ")[k] + " mm (gray=model; color=saved)", fill=(220, 225, 235))
        both = np.concatenate((points[:, [a, b]], model[:, [a, b]]))
        center = (both.min(0) + both.max(0)) / 2
        span = max(float(np.ptp(both, axis=0).max()), 1.) * 1.1

        def project(values):
            uv = (values[:, [a, b]] - center) / span * min(w, h)
            return np.column_stack((uv[:, 0] + x0 + w / 2, y0 + h / 2 - uv[:, 1]))

        projected_model = project(model)
        if len(projected_model) > 1:
            draw.line([tuple(p) for p in projected_model], fill=(110, 117, 128), width=1)
        for point, color in zip(project(points), colors):
            u, v = point
            draw.ellipse((u - 2, v - 2, u + 2, v + 2), fill=color)
    panels = [("unwrapped_angles_deg", "Angle by record order (deg)"),
              ("camera_origin_model_residual_mm", "Origin residual (mm)"),
              ("rotation_residual_deg", "Rotation residual (deg)")]
    for k, (key, title) in enumerate(panels):
        x0, y0, w, h = k * 500 + 20, 570, 455, 290
        draw.text((x0, y0 - 25), title, fill=(220, 225, 235))
        draw.rectangle((x0, y0, x0 + w, y0 + h), outline=(65, 85, 105))
        values = arrays[key]
        low, high = min(float(values.min()), 0.), max(float(values.max()), 1e-8)
        px = np.linspace(x0 + 8, x0 + w - 8, len(values))
        py = y0 + h - 8 - (values - low) / max(high - low, 1e-8) * (h - 16)
        draw.line(list(zip(px, py)), fill=(100, 203, 235), width=2)
        draw.text((x0 + 5, y0 + 5), f"min={values.min():.4f}, max={values.max():.4f}", fill=(220, 225, 235))
    canvas.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", type=Path, default=Path("reports/four-scans/decoded"))
    parser.add_argument("--out", type=Path, default=Path("reports/turntable-study-20261018"))
    parser.add_argument("--scans", nargs="+")
    parser.add_argument("--pose-source", choices=("auto", "stored", "global"), default="auto")
    parser.add_argument("--split-id-high-word", action="store_true", help="Also fit each high-word ID group separately, without assuming what the group means")
    args = parser.parse_args()
    source, output = args.decoded.resolve(), args.out.resolve()
    if source == output or source in output.parents or output in source.parents:
        parser.error("Output must be separate from decoded inputs")
    if output.exists() and any(output.iterdir()):
        parser.error("Use a new or empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    scans = [source / name for name in args.scans] if args.scans else sorted(p.parent for p in source.glob("*/index.json"))
    results = []
    for scan in scans:
        index, ids, matrices, sources, missing, digest = load_poses(scan, args.pose_source)
        scan_id = index["scan_id"]
        result = {"scan_id": scan_id, "index": str(scan / "index.json"),
                  "pose_source_selection": args.pose_source, "missing_pose_ids": missing,
                  "matrix_sequence_sha256": digest, "input_capture_setup": "not_inferred_from_pose_data"}
        target = output / scan_id
        target.mkdir()
        try:
            summary, arrays = diagnose_fixed_axis(matrices)
            result.update(status="analyzed", analysis=summary)
            np.savez_compressed(target / "relative_pose_diagnostics.npz", ids=np.asarray(ids, np.int64), **arrays)
            render(arrays, scan_id, target / "relative_motion.png")
            with (target / "pose_diagnostics.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["id", "pose_source", "angle_deg", "origin_residual_mm", "rotation_residual_deg"])
                writer.writerows(zip(ids, sources, arrays["unwrapped_angles_deg"],
                                     arrays["camera_origin_model_residual_mm"], arrays["rotation_residual_deg"]))
        except ValueError as exc:
            result.update(status="insufficient_or_unsupported", reason=str(exc))
        if args.split_id_high_word:
            grouped = {}
            for position, rid in enumerate(ids):
                grouped.setdefault(rid >> 32, []).append(position)
            result["id_high_word_groups"] = []
            for group, positions in sorted(grouped.items()):
                row = {"id_high_word": group, "poses": len(positions)}
                subfolder = target / f"id_high_{group}"
                subfolder.mkdir()
                try:
                    sub_summary, sub_arrays = diagnose_fixed_axis(np.asarray(matrices)[positions])
                    row.update(status="analyzed", analysis=sub_summary)
                    np.savez_compressed(subfolder / "relative_pose_diagnostics.npz",
                        ids=np.asarray(ids, np.int64)[positions], **sub_arrays)
                    render(sub_arrays, scan_id + f" id_high={group}", subfolder / "relative_motion.png")
                except ValueError as exc:
                    row.update(status="insufficient_or_unsupported", reason=str(exc))
                (subfolder / "report.json").write_text(json.dumps(row, indent=2, allow_nan=False), encoding="utf-8")
                result["id_high_word_groups"].append(row)
        (target / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        results.append(result)
        print(json.dumps({"scan": scan_id, "status": result["status"], **result.get("analysis", {})}, ensure_ascii=False), flush=True)
    (output / "summary.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()

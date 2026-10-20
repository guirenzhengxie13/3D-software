"""Migrate our initial attribute-color caches, leaving source files untouched.

Only the initial v6.1 decoder's unversioned RGBA arrays need this correction.
An explicit per-array version makes an interrupted migration safe to resume.
Rebuild colored TSDF outputs after running; this tool does not edit models.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", required=True, type=Path)
    args = parser.parse_args()
    root = args.decoded.resolve()
    reports = []
    for p in sorted(root.glob("*/index.json")):
        index = json.loads(p.read_text(encoding="utf-8"))
        if index.get("database_layout") != "attribute_tables_FrameVersion_2":
            raise ValueError("This migration only handles observed attribute-table caches")
        source = Path(index["source_directory"]).resolve()
        if root == source or source in root.parents or root in source.parents:
            raise ValueError("Never edit original project folders")
        if not index["status"]["colored_depth_frames"]:
            continue
        depth_before, depth_after = hashlib.sha256(), hashlib.sha256()
        changed, current = 0, 0
        for item in index["frames"]:
            if not item.get("embedded_rgba"):
                continue
            frame = p.parent / f"frame_{item['id']:010d}" / "frame.npz"
            with np.load(frame, allow_pickle=False) as saved:
                arrays = {k: saved[k].copy() for k in saved.files}
            depth_before.update(arrays["depth_mm"].tobytes())
            version = int(arrays.get("color_layout_version", 1))
            if version == 1:
                arrays["rgba"] = arrays["rgba"][:, [2, 1, 0, 3]].copy()
                arrays["color_layout_version"] = np.array(2, np.uint32)
                temporary = frame.with_suffix(".npz.tmp")
                with temporary.open("wb") as stream:
                    np.savez_compressed(stream, **arrays)
                temporary.replace(frame)
                changed += 1
            elif version == 2:
                current += 1
            else:
                raise ValueError("Unknown cached color version")
            with np.load(frame, allow_pickle=False) as saved:
                depth_after.update(saved["depth_mm"].tobytes())
        if depth_before.digest() != depth_after.digest():
            raise RuntimeError("Depth array changed during color migration")
        index["color_layout_version"] = 2
        index["color_convention"] = {
            "embedded_bytes": "A,B,G,R", "decoded_array": "R,G,B,A",
            "original_jpeg": "Preserved verbatim; standard RGB decoding requires an R/B swap for physical color in this cohort.",
            "evidence": "Native PLY colors plus user-confirmed blue bow on 12:26:07 figure. JPEG agreement alone was insufficient."}
        p.write_text(json.dumps(index, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        row = {"scan_id": index["scan_id"], "changed_frames": changed,
            "already_current_frames": current, "depth_sha256_before": depth_before.hexdigest(),
            "depth_sha256_after": depth_after.hexdigest(), "depth_arrays_unchanged": True}
        reports.append(row)
        print(json.dumps(row), flush=True)
    (root.parent / "color-cache-correction.json").write_text(
        json.dumps(reports, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

"""Describe uninterpreted marker bytes without assigning IDs or confidence."""

import argparse
import json
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    local, global_records = [], []
    for p in args.decoded.glob("*/frame_*/markers.npz"):
        with np.load(p, allow_pickle=False) as saved:
            raw = saved["raw_records"].copy()
        if raw.shape[1] != 36: raise ValueError("Unexpected local record width")
        local.append(np.frombuffer(raw.tobytes(), "<u4").reshape(-1, 9)[:, 6:])
    for p in args.decoded.glob("*/global_markers_*.npz"):
        with np.load(p, allow_pickle=False) as saved:
            raw = saved["raw_records"].copy()
        if raw.shape[1] != 104: raise ValueError("Unexpected global record width")
        global_records.append(raw[:, 48:])
    words = np.concatenate(local)
    fields = []
    for i in range(3):
        unique, count = np.unique(words[:, i], return_counts=True)
        top = np.argsort(count)[::-1][:8]
        values = words[:, i].copy().view("<f4")
        finite = values[np.isfinite(values)]
        fields.append({"record_byte_offset": 24+4*i, "distinct_u32_patterns": len(unique),
            "top_patterns": [{"hex_le": int(unique[k]).to_bytes(4, "little").hex(), "count": int(count[k])} for k in top],
            "interpret_as_f32_only": {"finite_count": len(finite), "min": float(finite.min()),
                "median": float(np.median(finite)), "max": float(finite.max())},
            "meaning": "unknown; do not use as marker identity, radius or quality without separate validation"})
    tail = np.concatenate(global_records)
    global_byte_patterns = []
    for i in range(tail.shape[1]):
        unique, count = np.unique(tail[:, i], return_counts=True)
        if len(unique) == 1:
            global_byte_patterns.append({"record_byte_offset": i+48, "constant_byte_value": int(unique[0]), "records": len(tail)})
    report = {"local_records": len(words), "local_uninterpreted_words": fields,
        "global_records": len(tail), "global_tail_constant_bytes": global_byte_patterns,
        "conclusion": "No stable per-marker identity has been established in the inspected tail fields. Raw records remain the authority; nearest-framework array indices are not decoded IDs.",
        "scope": "Distributional evidence only. Values resembling a size or confidence are deliberately left unnamed."}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

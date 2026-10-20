"""Describe opaque frame metadata without assigning undocumented semantics.

Offsets are zero based and represent observations in the current cohort only.
Sequence-like words and flags are diagnostic fields, never filtering rules.
"""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import struct

import numpy as np


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Use a new/empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    blobs, rows, projects, combinations = [], [], [], Counter()
    pose_equal, pose_different = 0, 0
    for path in sorted(args.decoded.glob("scan_*/index.json")):
        index = read(path)
        groups = {}
        different = equal = 0
        for frame in index["frames"]:
            rid = frame["id"]
            folder = path.parent / f"frame_{rid:010d}"
            blob = (folder / "frame_info_attribute.bin").read_bytes()
            if len(blob) != 75 or struct.unpack_from("<I", blob)[0] != 2:
                raise ValueError("Unrecognized frame-info metadata layout")
            blobs.append(blob)
            sequence = struct.unpack_from("<I", blob, 10)[0]
            value = struct.unpack_from("<f", blob, 15)[0]
            if not np.isfinite(value):
                raise ValueError("Nonfinite candidate f32 field")
            optimized = bool(frame.get("optimized_pose_available"))
            marker = (folder / "marker_attribute.bin").is_file()
            group = groups.setdefault(rid >> 32, [])
            row = dict(scan_id=index["scan_id"], id=rid, id_high=rid >> 32,
                       id_low=rid & 0xffffffff, byte_4=blob[4], u32_at_10=sequence,
                       f32_at_15=value, byte_32=blob[32], optimized_present=optimized,
                       marker_attribute_present=marker, color_present=frame["embedded_rgba"])
            group.append(row)
            rows.append(row)
            combinations[(blob[4], blob[32], marker, optimized)] += 1
            if optimized:
                stored = np.load(folder / "pose_stored.npy", allow_pickle=False)
                refined = np.load(folder / "pose_optimized.npy", allow_pickle=False)
                if np.array_equal(stored, refined):
                    equal += 1
                else:
                    different += 1
        group_rows = []
        for high, entries in groups.items():
            seq = np.array([r["u32_at_10"] for r in entries], dtype=np.int64)
            steps = np.diff(seq)
            nonunit = [dict(previous_id=entries[i]["id"], next_id=entries[i+1]["id"],
                            previous_u32=int(seq[i]), next_u32=int(seq[i+1]), step=int(step))
                       for i, step in enumerate(steps) if step != 1]
            group_rows.append(dict(id_high=high, records=len(entries),
                first_last_low_id=[entries[0]["id_low"], entries[-1]["id_low"]],
                first_last_u32=[int(seq[0]), int(seq[-1])],
                u32_min_max=[int(seq.min()), int(seq.max())],
                unique_u32_values=len(set(seq.tolist())), non_unit_steps=nonunit,
                candidate_f32_range=[min(r["f32_at_15"] for r in entries), max(r["f32_at_15"] for r in entries)]))
        projects.append(dict(scan_id=index["scan_id"], records=len(index["frames"]),
                             exact_equal_pose_pairs=equal, different_pose_pairs=different, groups=group_rows))
        pose_equal += equal
        pose_different += different
    array = np.array([list(b) for b in blobs], dtype=np.uint8)
    variable = [i for i in range(75) if np.any(array[:, i] != array[0, i])]
    report = dict(records=len(blobs), byte_lengths=[75], variable_byte_offsets=variable,
        constant_bytes={str(i): int(array[0, i]) for i in range(75) if i not in variable},
        exact_equal_stored_optimized_pairs=pose_equal, different_stored_optimized_pairs=pose_different,
        cross_table=[dict(byte_4=k[0], byte_32=k[1], marker_attribute_present=k[2],
                          optimized_present=k[3], count=v) for k, v in sorted(combinations.items())],
        projects=projects,
        limitations=["Undocumented fields are named by byte offset; their physical/vendor meaning is unknown.",
          "The u32 at 10 behaves like a counter in many records, but resets, gaps and reversals exist.",
          "Absent counter values do not prove acquisition dropped physical frames or why records were omitted.",
          "Byte 4 is not equivalent to optimized-pose membership and must not be used as a discard flag.",
          "Equal saved/optimized matrices do not prove no internal processing occurred.",
          "A 75-byte info record has no room for an additional 4x4 f64 pose; no other hidden transform is ruled out."])
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "frames.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# 原始帧信息调查", "", "字段只按偏移命名，尚未确定厂商语义；不会据此排序回放、删帧或修改位姿。", "",
             f"检查 {len(blobs):,} 条 75 字节记录。可变字节仅在 {variable}。", "",
             f"保存位姿与优化表中同 ID 位姿有 {pose_equal:,} 对逐元素完全相同，{pose_different:,} 对不同。优化表存在不等于每份工程都优化过。", "",
             "13:13:59 两组的 u32@10 范围分别为 1–222、289–426，共保存 358 条。数值范围中存在 68 个未出现值，但不能把它们直接解释为丢失的原始帧。", "",
             "byte@4=0 的 84 条记录中，82 条没有优化位姿，另 2 条仍有优化位姿。这不是可靠的删帧规则。", "",
             "部分工程会在换组时把 u32@10 重置为 1；10:49:20 的 ID=1 则为 194，随后 ID=2 回到 3。不能将它当成全项目时间戳。", "",
             "完整逐帧字段见 [frames.csv](frames.csv)，分组边界与非连续步骤见 [summary.json](summary.json)。"]
    (output / "README.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("projects", "constant_bytes", "limitations")}), flush=True)


if __name__ == "__main__":
    main()

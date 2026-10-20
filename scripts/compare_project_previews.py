"""Generic same-project TSDF versus saved native point-cloud comparisons.

Native previews are explicitly not official final fusion or ground truth.
No additional registration or scale fitting is used for these comparisons.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from compare_fusion_results import PALETTE, display_data, read_points, write_json
from reconstruction_probe._open3d import require_open3d
from reconstruction_probe.comparison import compare_point_sets, voxel_representatives
from reconstruction_probe.offline import file_sha256


def reference_clouds(index, kind):
    source = Path(index["source_directory"]).resolve()
    if kind == "preview":
        return [("", source / "raw_preview.ply", "原工程预览")]
    manifest = json.loads((source / index["source_manifest"]).read_text(encoding="utf-8"))
    result = []
    for i, entry in enumerate(manifest.get("point_clouds", [])):
        # Only entries explicitly carrying fusion settings are treated as saved
        # fusion. Do not silently ignore user alignment transforms.
        if not entry.get("fuse_param"):
            continue
        if any(float(entry.get(f"model_align_{action}_{axis}", 0)) != 0
               for action in ("rotate", "translate") for axis in "xyz"):
            raise ValueError("Saved cloud has an alignment transform; explicit handling required")
        path = (source / entry["file"]).resolve()
        if source not in path.parents or path.suffix.lower() != ".ply":
            raise ValueError("Unexpected saved fusion path")
        result.append((f"_fused_{i}", path, "官方保存融合点云"))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", type=Path, required=True)
    parser.add_argument("--reconstruction", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--voxel-mm", type=float, default=.5)
    parser.add_argument("--display-points", type=int, default=10000)
    parser.add_argument("--reference-kind", choices=("preview", "saved-fusion"), default="preview")
    args = parser.parse_args()
    output = args.out.resolve()
    if not 1 <= args.display_points <= 50000:
        parser.error("Display sample count must be 1..50000")
    output.mkdir(parents=True, exist_ok=True)
    o3d = require_open3d()
    pairs, reports, omitted = [], [], []
    inputs = []
    for index_path in sorted(args.decoded.glob("*/index.json")):
        index = json.loads(index_path.read_text(encoding="utf-8"))
        references = reference_clouds(index, args.reference_kind)
        if not references:
            omitted.append({"scan_id": index["scan_id"], "reason": "no_saved_fusion_entry"})
        inputs.extend((index, *reference) for reference in references)
    for index, suffix, native_path, reference_label in inputs:
        scan_id = index["scan_id"]
        case_id = scan_id + suffix
        source = Path(index["source_directory"]).resolve()
        if output == source or source in output.parents:
            raise ValueError("Never write inside an original project")
        own_path = args.reconstruction / scan_id / "tsdf_pointcloud_mm.ply"
        if not own_path.is_file() or not native_path.is_file():
            omitted.append({"scan_id": scan_id, "reason": "missing_reconstruction_or_reference"})
            continue
        hashes = {str(p.resolve()): file_sha256(p) for p in (own_path, native_path)}
        own_raw, native_raw = read_points(own_path, o3d), read_points(native_path, o3d)
        own, own_keys, own_counts = voxel_representatives(own_raw, args.voxel_mm)
        native, native_keys, native_counts = voxel_representatives(native_raw, args.voxel_mm)
        distances = compare_point_sets(own, native)
        folder = output / case_id
        folder.mkdir(exist_ok=True)
        np.savez_compressed(folder / "analysis_points.npz", own_xyz=own, official_xyz=native,
            own_voxel_keys=own_keys, official_voxel_keys=native_keys,
            own_input_counts=own_counts, official_input_counts=native_counts,
            own_distances=distances["own_distances"], official_distances=distances["official_distances"],
            own_nearest_indices=distances["own_nearest_indices"], official_nearest_indices=distances["official_nearest_indices"])
        is_preview = args.reference_kind == "preview"
        metadata = {"kind": "preview_comparison" if is_preview else "saved_fusion_comparison",
            "referenceKind": args.reference_kind, "distanceMethod": "point_nearest_neighbor",
            "coordinate": scan_id + " saved scan frame, mm",
            "analysisDescription": f"同一固定原点的 {args.voxel_mm:g} mm 体素代表点，双向查询完整分析云",
            "fairness": ("官方一侧是工程 raw_preview，不是最终融合结果；不用于判定谁更准确。" if is_preview else
                "官方一侧是工程清单中具有 fuse_param 的保存融合点云。双方均非独立真值，距离不能直接判定谁更准确。") + "未经额外配准或缩放。",
            "notes": [("本项使用 raw_preview；工程中另存的融合结果需在独立对比页查看。" if is_preview else
                "本项使用官方保存融合点云；融合参数及输出身份以原工程清单为准。"),
                "蓝色可能包含新增观测、噪声、跟踪偏差或 TSDF 插值，不能自动解释为成功补全。",
                "橙色可能来自预览保留、TSDF 筛选或分辨率差异，不是已知真实缺损。",
                "点颜色在此是支持分类；原始彩色 TSDF 请查看单独的彩色三维审阅页。",
                f"本案例采用光学到位姿轴约定 {index.get('optical_to_pose_axes')}。"]}
        pair = {"id": case_id, "label": index["source_manifest"].removesuffix(".revox") + f"｜{reference_label} vs 自研 TSDF",
            "own": display_data(own, distances["own_distances"], distances["own_nearest_indices"], native,
                                own_path, args.display_points, "保存深度＋可用优化位姿重新 TSDF；完整参数见 reconstruction.json"),
            "official": display_data(native, distances["official_distances"], distances["official_nearest_indices"], own,
                                     native_path, args.display_points, reference_label + "；非独立真值"),
            "stats": distances["stats"], "metadata": metadata,
            "bounds": {"min": np.minimum(own.min(0), native.min(0)).tolist(),
                       "max": np.maximum(own.max(0), native.max(0)).tolist()}}
        pairs.append(pair)
        reference_key = "native_preview" if is_preview else "official_fusion"
        report = {"scan_id": scan_id, "case_id": case_id,
            "raw_points": {"own": len(own_raw), reference_key: len(native_raw)},
            "analysis_points": {"own": len(own), reference_key: len(native)}, "stats": distances["stats"],
            "metadata": metadata, "source_sha256": hashes,
            "inputs_unchanged": all(file_sha256(Path(p)) == value for p, value in hashes.items())}
        if not report["inputs_unchanged"]:
            raise RuntimeError("A comparison input changed while reading")
        reports.append(report)
        write_json(folder / "comparison.json", report)
        row = distances["stats"]["1"]
        print(json.dumps({"scan": scan_id, "own_median_mm": row["medianOwn"], "preview_median_mm": row["medianOfficial"],
                          "own_supported": row["own"]["commonFraction"], "preview_supported": row["official"]["commonFraction"]}), flush=True)
    if not pairs:
        raise ValueError("No completed reconstruction/native-preview pairs")
    initial = next((p["id"] for p in pairs if p["id"].startswith("scan_20261018122607")), pairs[0]["id"])
    payload = {"unit": "mm", "voxelMm": args.voxel_mm, "thresholds": [.5, 1, 2], "palette": PALETTE,
               "initialPair": initial, "pairs": pairs}
    (output / "comparison-data.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    write_json(output / "summary.json", {"pairs": reports, "omitted": omitted,
        "interpretation": ("Native raw-preview consistency only; saved fusion entries are compared separately." if args.reference_kind == "preview" else
            "Saved official fused cloud versus own TSDF; no independent ground truth. Point-neighbor distances depend on surface sampling.")})


if __name__ == "__main__":
    main()

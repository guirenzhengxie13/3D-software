"""Compare official and independently integrated results in the same coordinates.

No ICP or similarity fit is performed here. Reference-assisted scan04 is
mapped back with the inverse of its already documented cross-scan transform.
All original input files are read-only, and colors denote support rather than
texture, accuracy, or a semantic verdict about holes.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reconstruction_probe._open3d import require_open3d
from reconstruction_probe.comparison import compare_point_sets, voxel_representatives
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.sources import _read_ply_cloud


PALETTE = {"common": [103, 211, 145], "own_only": [84, 168, 255], "official_only": [255, 173, 92]}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def encoded(values, dtype):
    return base64.b64encode(np.ascontiguousarray(values, dtype=dtype).tobytes()).decode("ascii")


def read_points(path, o3d):
    cloud = _read_ply_cloud(o3d, path.resolve())
    points = np.asarray(cloud.points)
    if not len(points) or not np.isfinite(points).all():
        raise ValueError(f"Empty or nonfinite input cloud: {path}")
    return points.copy()


def write_colored_ply(path, points, distances, source, threshold):
    records = np.empty(len(points), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                           ("red", "u1"), ("green", "u1"), ("blue", "u1"),
                                           ("other_distance_mm", "<f8"), ("source_id", "u1")])
    common = distances <= threshold
    colors = np.tile(PALETTE["own_only" if source == 0 else "official_only"], (len(points), 1))
    colors[common] = PALETTE["common"]
    for axis, name in enumerate(("x", "y", "z")):
        records[name] = points[:, axis]
    for axis, name in enumerate(("red", "green", "blue")):
        records[name] = colors[:, axis]
    records["other_distance_mm"], records["source_id"] = distances, source
    header = ["ply", "format binary_little_endian 1.0", "comment units mm",
              "comment support_classification_not_measurement_accuracy",
              f"comment threshold_mm {threshold:g}", "comment source_id_0_own_1_official",
              f"element vertex {len(points)}", "property float x", "property float y", "property float z",
              "property uchar red", "property uchar green", "property uchar blue",
              "property double other_distance_mm", "property uchar source_id", "end_header"]
    path.write_bytes(("\n".join(header) + "\n").encode("ascii") + records.tobytes())


def display_data(points, distances, nearest_indices, other, path, limit, provenance):
    # Uniform deterministic source indices, keeping analytical statistics full.
    # Categories are not reweighted to make discrepancy areas look larger.
    indices = np.linspace(0, len(points) - 1, min(limit, len(points)), dtype=np.int64)
    return {"xyz": encoded(points[indices], "<f4"), "distances": encoded(distances[indices], "<f8"),
            "distanceEncoding": "float64-le", "nearest": encoded(other[nearest_indices[indices]], "<f4"),
            "displayCount": len(indices), "analysisCount": len(points), "path": str(path.resolve()),
            "provenance": provenance,
            "sampling": "uniform deterministic analysis indices; full-cloud distances, no class reweighting",
            "coordinatePrecision": "display XYZ quantized to float32; classification distance preserved as float64"}


def append_mesh_comparisons(root, out, pairs, reports, limit):
    """Add equal-area samples with exact triangle-surface distances.

    Unlike point-cloud pairs, these samples are not voxelized. Distances use
    the opposite complete triangle surface, avoiding vertex-density bias.
    """
    labels = {"scan_01": "标准样例", "scan_03": "成功扫描", "scan_04": "失败扫描"}
    specs = [("scan_04", "baseline"), ("scan_04", "reference_assisted"),
             ("scan_03", "baseline"), ("scan_01", "baseline")]
    for scan, variant in specs:
        path = out / f"analysis_mesh_{scan}_{variant}.npz"
        analysis_file = out / f"analysis_{scan}_{variant}.json"
        if not path.exists() or not analysis_file.exists():
            continue
        with np.load(path, allow_pickle=False) as saved:
            arrays = {key: saved[key] for key in saved.files}
        analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
        assisted = variant == "reference_assisted"
        pair_id = f"{scan}_mesh_{variant}"
        own_path = root / "reconstruction" / scan / "tsdf_mesh_mm.ply"
        if assisted:
            own_path = root / "reconstruction/scan_04_reference_assisted/scan_04/tsdf_mesh_mm.ply"
        official_path = root / "registration/staged_inputs" / f"{scan}_mesh.ply"
        own, official = arrays["own_xyz"], arrays["official_xyz"]
        stats = {}
        for threshold in (.5, 1., 2.):
            row = {"medianOwn": float(np.median(arrays["own_distances"])),
                   "medianOfficial": float(np.median(arrays["official_distances"])),
                   "p90Own": float(np.percentile(arrays["own_distances"], 90)),
                   "p90Official": float(np.percentile(arrays["official_distances"], 90))}
            for side in ("own", "official"):
                distances = arrays[f"{side}_distances"]
                common = int((distances <= threshold).sum())
                row[side] = {"total": len(distances), "common": common, "unique": len(distances) - common,
                             "commonFraction": common / len(distances), "uniqueFraction": 1 - common / len(distances)}
            stats[f"{threshold:g}"] = row

        def display(side, source_path, provenance):
            points, distances, nearest = [arrays[f"{side}_{name}"] for name in ("xyz", "distances", "nearest_xyz")]
            indices = np.linspace(0, len(points) - 1, min(limit, len(points)), dtype=np.int64)
            return {"xyz": encoded(points[indices], "<f4"), "distances": encoded(distances[indices], "<f8"),
                    "distanceEncoding": "float64-le", "nearest": encoded(nearest[indices], "<f4"),
                    "displayCount": len(indices), "analysisCount": len(points), "path": str(source_path.resolve()),
                    "provenance": provenance, "sampling": "deterministic subset of area-uniform surface samples",
                    "coordinatePrecision": "display XYZ float32; classification distance float64"}

        notes = ["本项对比两个最终三角网格。每侧20万个等面积表面样本，计算到对侧完整三角面的最近距离，不按顶点数量判定缺失。",
                 "绿色为对侧表面在当前容差内提供支持；蓝色与橙色不直接等于补洞成功或几何错误。",
                 "两者沿用同工程坐标，未额外做ICP或缩放来缩小差异。",
                 "边界数量受孔洞、开放底面、三角网格分辨率和细碎组件影响，不能单凭数量判定实物准确度。"]
        if scan == "scan_01":
            notes.append("官方最终网格已经去掉了融合点云中的背景平面，不能把点云阶段的背景差异算作优于官方最终模型。")
        if scan == "scan_03":
            notes.append("官方工程的网格参数启用了填洞；本项目基线未做封闭填洞。")
        if assisted:
            notes.append("该候选额外使用成功扫描修正位姿，并用已记录的跨扫描变换逆映射回失败工程坐标；属于参考辅助方案，不是同输入条件的纯基线。")
        metadata = {"kind": "mesh_surface_comparison", "distanceMethod": "triangle_surface",
                    "analysisDescription": f"双方各 {len(own):,} 个等面积表面样本；距离对侧完整三角面",
                    "coordinate": f"{scan} 原扫描参考系，毫米",
                    "fairness": "额外使用成功扫描作为参考，请与未经修正基线分开判断" if assisted else "同一份原始工程的最终网格对照，无新增配准或缩放",
                    "notes": notes}
        pair = {"id": pair_id,
                "label": labels[scan] + ("｜最终网格：官方 vs 参考辅助候选" if assisted else "｜最终网格：官方 vs 自研基线"),
                "own": display("own", own_path, "参考辅助 TSDF 网格" if assisted else "原始深度独立 TSDF 网格"),
                "official": display("official", official_path, "官方保存的最终三角网格"),
                "stats": stats, "metadata": metadata,
                "bounds": {"min": np.minimum(own.min(0), official.min(0)).tolist(),
                           "max": np.maximum(own.max(0), official.max(0)).tolist()}}
        pairs.append(pair)
        reports.append({"id": pair_id, "label": pair["label"], "stats": stats, "metadata": metadata,
                        "source_sha256": {str(p.resolve()): file_sha256(p) for p in (path, own_path, official_path)},
                        "analysis_file": str(analysis_file), "inputs_unchanged": True})
        for threshold in (.5, 1., 2.):
            folder = out / pair_id
            folder.mkdir(exist_ok=True)
            write_colored_ply(folder / f"own_{threshold:g}mm.ply", own, arrays["own_distances"], 0, threshold)
            write_colored_ply(folder / f"official_{threshold:g}mm.ply", official, arrays["official_distances"], 1, threshold)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", type=Path, default=Path("item"))
    parser.add_argument("--results", type=Path, default=Path("reports/four-scans"))
    parser.add_argument("--out", type=Path, default=Path("reports/four-scans/comparison"))
    parser.add_argument("--voxel-mm", type=float, default=.5)
    parser.add_argument("--display-points", type=int, default=25_000)
    parser.add_argument("--skip-mesh", action="store_true", help="Exclude precomputed final-mesh surface comparisons")
    args = parser.parse_args()
    if args.out.resolve().is_relative_to(args.item.resolve()):
        parser.error("Write comparison outputs outside original inputs")
    if not 1 <= args.display_points <= 50_000:
        parser.error("Display sample limit must be 1..50000 per input")
    o3d = require_open3d()
    sources = {f"scan_{i:02d}": next((args.item / folder).glob("*/cache/frames.dataset")).parent.parent
               for i, folder in enumerate(("share", "share(1)", "share(2)", "share(3)"), 1)}
    specs = [
        ("scan_04_baseline", "失败扫描｜官方融合点云 vs 自研原位姿 TSDF 点云", "scan_04", False, False),
        ("scan_04_reference_assisted", "失败扫描｜官方融合点云 vs 参考辅助点云（额外使用成功扫描）", "scan_04", True, False),
        ("scan_03_baseline", "成功扫描｜官方融合点云 vs 自研 TSDF 点云", "scan_03", False, False),
        ("scan_01_baseline", "标准样例｜同工程官方融合点云 vs 自研 TSDF 点云", "scan_01", False, False),
        ("scan_02_preview", "局部扫描：官方预览 vs 自研 TSDF（未保存官方融合）", "scan_02", False, True),
    ]
    args.out.mkdir(parents=True, exist_ok=True)
    pairs, report_pairs = [], []
    for pair_id, label, scan, assisted, preview in specs:
        own_path = args.results / "reconstruction" / scan / "tsdf_pointcloud_mm.ply"
        if assisted:
            own_path = args.results / "reconstruction/scan_04_reference_assisted/scan_04/tsdf_pointcloud_mm.ply"
        official_path = sources[scan] / ("raw_preview.ply" if preview else "pointclouds/fuse.ply")
        watched = [own_path, official_path]
        if assisted:
            watched.append(args.results / "registration/scan_04_registration.json")
        before = {str(path.resolve()): file_sha256(path) for path in watched}
        own_raw, official_raw = read_points(own_path, o3d), read_points(official_path, o3d)
        transform = np.eye(4)
        if assisted:
            registration = json.loads(watched[-1].read_text(encoding="utf-8"))
            transform = np.linalg.inv(np.asarray(registration["transform_source_to_reference"], dtype=float))
            own_raw = own_raw @ transform[:3, :3].T + transform[:3, 3]
        own, own_keys, own_counts = voxel_representatives(own_raw, args.voxel_mm)
        official, official_keys, official_counts = voxel_representatives(official_raw, args.voxel_mm)
        result = compare_point_sets(own, official)
        folder = args.out / pair_id
        folder.mkdir(exist_ok=True)
        np.savez_compressed(folder / "analysis_points.npz", own_xyz=own, official_xyz=official,
                            own_voxel_keys=own_keys, official_voxel_keys=official_keys,
                            own_input_counts=own_counts, official_input_counts=official_counts,
                            own_distances=result["own_distances"], official_distances=result["official_distances"],
                            own_nearest_indices=result["own_nearest_indices"], official_nearest_indices=result["official_nearest_indices"])
        for threshold in (.5, 1., 2.):
            write_colored_ply(folder / f"own_{threshold:g}mm.ply", own, result["own_distances"], 0, threshold)
            write_colored_ply(folder / f"official_{threshold:g}mm.ply", official, result["official_distances"], 1, threshold)
        own_provenance = "reference_assisted_raw_depth_TSDF_using_scan03_prior" if assisted else "independent_raw_depth_TSDF_using_saved_poses"
        metadata = {"kind": "preview_comparison" if preview else "official_fusion_comparison",
                    "distanceMethod": "point_nearest_neighbor",
                    "analysisDescription": f"固定共享原点，{args.voxel_mm:g} mm 体素代表点；距离对侧完整分析点云",
                    "coordinate": f"original {scan} saved scan coordinates, mm",
                    "fairness": "extra reference scan03 used; compare as an assisted workflow, not the same-input baseline" if assisted else "same saved project, no post-hoc ICP or scale adjustment",
                    "notes": ["共同支持是另一侧在阈值内存在近邻，不是顶点完全相同，也不是精度认证。",
                              "蓝色/橙色表示该阈值下缺少另一结果支持；可能来自噪声、孔洞、裁剪或采样差异。",
                              f"统计在共同原点0、{args.voxel_mm:g}mm体素代表点上进行；显示抽样只影响画面，不影响距离和比例。",
                              "显示坐标为float32近似，分类距离保持float64；颜色是诊断配色，不是纹理。"]}
        if preview:
            metadata["notes"].append("此工程没有保存官方最终融合模型，此项仅与官方原始预览比较。")
        if assisted:
            metadata["notes"].append("辅助候选以成功扫描修正位姿并排除无参考支持的像素；不是完全相同输入条件，也未恢复所有缺失区域。")
        pair = {"id": pair_id, "label": label,
                "own": display_data(own, result["own_distances"], result["own_nearest_indices"], official, own_path, args.display_points, own_provenance),
                "official": display_data(official, result["official_distances"], result["official_nearest_indices"], own, official_path, args.display_points,
                                         "vendor_raw_preview" if preview else "vendor_saved_final_fusion"),
                "stats": result["stats"], "metadata": metadata,
                "bounds": {"min": np.minimum(own.min(0), official.min(0)).tolist(),
                           "max": np.maximum(own.max(0), official.max(0)).tolist()}}
        report = {"id": pair_id, "label": label, "scan": scan, "input_points": {"own": len(own_raw), "official": len(official_raw)},
                  "analysis_points": {"own": len(own), "official": len(official)},
                  "voxel_mm": args.voxel_mm, "lattice_origin": [0, 0, 0],
                  "own_to_project_transform": transform.tolist(), "stats": result["stats"], "metadata": metadata,
                  "source_sha256": before, "inputs_unchanged": all(file_sha256(Path(path)) == digest for path, digest in before.items())}
        if not report["inputs_unchanged"]:
            raise RuntimeError("A comparison input changed during processing")
        write_json(folder / "comparison.json", report)
        pairs.append(pair)
        report_pairs.append(report)
        print(pair_id + ": " + json.dumps(result["stats"]["1"]), flush=True)
    if not args.skip_mesh:
        append_mesh_comparisons(args.results, args.out, pairs, report_pairs, args.display_points)
    # Keep the directly comparable failed-scan final surfaces at the front.
    order = {"scan_04_mesh_baseline": 0, "scan_04_baseline": 1, "scan_04_mesh_reference_assisted": 2,
             "scan_04_reference_assisted": 3, "scan_03_mesh_baseline": 4, "scan_03_baseline": 5,
             "scan_01_mesh_baseline": 6, "scan_01_baseline": 7, "scan_02_preview": 8}
    pairs.sort(key=lambda item: order.get(item["id"], 99))
    payload = {"unit": "mm", "voxelMm": args.voxel_mm, "thresholds": [.5, 1, 2], "palette": PALETTE,
               "initialPair": "scan_04_mesh_baseline" if any(p["id"] == "scan_04_mesh_baseline" for p in pairs) else "scan_04_baseline",
               "pairs": pairs}
    # Compact JSON keeps a standalone WebGL artifact reasonably small.
    (args.out / "comparison-data.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    write_json(args.out / "summary.json", {"pairs": report_pairs, "palette": PALETTE,
                                          "classification": "bidirectional nearest-neighbour support, not exact point intersection or independent accuracy"})


if __name__ == "__main__":
    main()

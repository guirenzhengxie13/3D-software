"""Bounded rigid/similarity shape check; object identity remains unconfirmed.

This never merges scans. It compares dominant mesh components reconstructed
from saved depth frames, avoiding separated background geometry.
"""
from __future__ import annotations

import argparse
import copy
import itertools
import json
import os
from pathlib import Path
import time

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

import numpy as np
import open3d as o3d

from register_scans import nearest_neighbors, render_projection, sha256


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def dominant_cloud(path):
    mesh = o3d.io.read_triangle_mesh(str(path))
    labels, counts, areas = mesh.cluster_connected_triangles()
    counts = np.asarray(counts)
    chosen = int(np.argmax(counts))
    mesh.remove_triangles_by_mask(np.asarray(labels) != chosen)
    mesh.remove_unreferenced_vertices()
    mesh.compute_vertex_normals()
    cloud = o3d.geometry.PointCloud()
    cloud.points = mesh.vertices
    cloud.normals = mesh.vertex_normals
    cloud = cloud.voxel_down_sample(1.)
    cloud, _ = cloud.remove_statistical_outlier(nb_neighbors=25, std_ratio=2.5)
    cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=3., max_nn=40))
    cloud.normalize_normals()
    a = np.asarray(cloud.points)
    return cloud, {"input": str(path.resolve()), "input_sha256": sha256(path),
                   "component_count": len(counts), "selected_component": chosen,
                   "selected_component_triangles": int(counts[chosen]),
                   "selected_component_area": float(areas[chosen]),
                   "component_triangle_counts_largest5": sorted(map(int, counts), reverse=True)[:5],
                   "sample_points_after_1mm_voxel_and_outlier_filter": len(a),
                   "extent_mm": np.ptp(a, axis=0).tolist()}


def pca(cloud):
    a = np.asarray(cloud.points)
    center = a.mean(axis=0)
    values, vectors = np.linalg.eigh(np.cov((a - center).T))
    return center, values[::-1], vectors[:, ::-1]


def pca_rotations(source, target):
    ca, eva, va = pca(source)
    cb, evb, vb = pca(target)
    rotations = []
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product([-1, 1], repeat=3):
            r = vb @ np.eye(3)[:, permutation] @ np.diag(signs) @ va.T
            if np.linalg.det(r) > .99:
                rotations.append(r)
    ratios = np.sqrt(evb / eva)
    scales = [1., float(np.median(ratios)), float(np.exp(np.log(ratios).mean())),
              float(np.sqrt(evb.sum() / eva.sum()))]
    scales += [float(np.median(ratios)) * .8, float(np.median(ratios)) * 1.2]
    scales = sorted({round(float(np.clip(s, .3, 3.)), 5) for s in scales})
    return ca, cb, rotations, scales, ratios.tolist()


def uniform_scale(transform):
    singular = np.linalg.svd(transform[:3, :3], compute_uv=False)
    return float(singular.mean()), float(np.ptp(singular))


def distances(values):
    return {"median_mm": float(np.median(values)), "p90_mm": float(np.percentile(values, 90)),
            "p95_mm": float(np.percentile(values, 95)), "mean_mm": float(np.mean(values)),
            "within_1mm": float((values <= 1).mean()), "within_2mm": float((values <= 2).mean()),
            "within_5mm": float((values <= 5).mean())}


def evaluate(source, target, transform):
    a = np.asarray(source.points) @ transform[:3, :3].T + transform[:3, 3]
    b = np.asarray(target.points)
    da, ia = nearest_neighbors(b, a)
    db, _ = nearest_neighbors(a, b)
    scale, anisotropy = uniform_scale(transform)
    rotation = transform[:3, :3] / scale
    na = np.asarray(source.normals) @ rotation.T
    nb = np.asarray(target.normals)
    overlap = da <= 2
    dot = np.abs((na[overlap] * nb[ia[overlap]]).sum(axis=1)).clip(0, 1)
    ca = float((da <= 2).mean())
    cb = float((db <= 2).mean())
    harmonic = 2 * ca * cb / max(1e-12, ca + cb)
    median_pair = (float(np.median(da)) + float(np.median(db))) * .5
    return {"uniform_scale_source01_to_reference03": scale, "singular_value_spread": anisotropy,
            "source_to_reference": distances(da), "reference_to_source": distances(db),
            "symmetric_chamfer_mean_mm": float((da.mean() + db.mean()) * .5),
            "symmetric_2mm_coverage_harmonic": harmonic,
            "overlap_abs_normal_dot_median": float(np.median(dot)) if len(dot) else None,
            "balanced_selection_score": harmonic - min(median_pair, 20) * .015}


def fit(source, target, initial, allow_scale, max_distance=8., iterations=15):
    result = o3d.pipelines.registration.registration_icp(
        source, target, max_distance, initial,
        o3d.pipelines.registration.TransformationEstimationPointToPoint(allow_scale),
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=iterations))
    return result.transformation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("reports/four-scans/reconstruction"))
    parser.add_argument("--output", type=Path, default=Path("reports/four-scans/registration/standard_identity_check"))
    parser.add_argument("--seconds", type=float, default=55.)
    args = parser.parse_args()
    started = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    source, source_info = dominant_cloud(args.root / "scan_01" / "tsdf_mesh_mm.ply")
    target, target_info = dominant_cloud(args.root / "scan_03" / "tsdf_mesh_mm.ply")
    coarse_source, coarse_target = source.voxel_down_sample(3.), target.voxel_down_sample(3.)
    ca, cb, rotations, scales, axis_ratios = pca_rotations(coarse_source, coarse_target)
    candidates = []
    # Equal opportunity to rigid and similarity objectives. No fixed identity
    # exclusions are applied. Balanced two-way overlap resists shrinking a bust
    # into a locally convenient surface patch.
    initial_cases = [(False, 1., i, r) for i, r in enumerate(rotations)]
    initial_cases += [(True, s, i, r) for s in scales for i, r in enumerate(rotations)]
    for allow_scale, initial_scale, rid, rotation in initial_cases:
        if time.monotonic() - started > args.seconds * .72 and any(c["allow_scaling"] for c in candidates):
            break
        initial = np.eye(4)
        initial[:3, :3] = rotation * initial_scale
        initial[:3, 3] = cb - initial[:3, :3] @ ca
        transform = fit(coarse_source, coarse_target, initial, allow_scale)
        scale, spread = uniform_scale(transform)
        if not .3 <= scale <= 3 or spread > 1e-6 or np.linalg.det(transform[:3, :3]) <= 0:
            continue
        m = evaluate(coarse_source, coarse_target, transform)
        candidates.append({"allow_scaling": allow_scale, "initial_scale": initial_scale,
                           "pca_rotation_index": rid, "transform": transform.tolist(), "coarse_metrics": m})
    best = {}
    for allow_scale, label in [(False, "rigid"), (True, "similarity")]:
        group = sorted([c for c in candidates if c["allow_scaling"] == allow_scale],
                       key=lambda c: c["coarse_metrics"]["balanced_selection_score"], reverse=True)
        if not group:
            raise RuntimeError("Bounded search did not produce both rigid and similarity candidates")
        refined = []
        for c in group[:5]:
            transform = np.array(c["transform"])
            for threshold in [5., 2.5]:
                transform = fit(source, target, transform, allow_scale, threshold, 30)
            scale, spread = uniform_scale(transform)
            if not .3 <= scale <= 3 or spread > 1e-6:
                continue
            m = evaluate(source, target, transform)
            refined.append({"initial_candidate": c, "transform": transform.tolist(), "metrics": m})
        best[label] = max(refined, key=lambda c: c["metrics"]["balanced_selection_score"])
        transformed = copy.deepcopy(source).transform(np.array(best[label]["transform"]))
        transformed.normalize_normals()
        transformed.paint_uniform_color([.95, .4, .25])
        o3d.io.write_point_cloud(str(args.output / f"scan_01_{label}_candidate_only.ply"), transformed)
        render_projection([("scan_03", target), ("scan_01", transformed)], args.output / f"{label}_comparison.png",
                          f"01 vs 03 {label}: diagnostic only; identity unconfirmed; no merge")
    result = {"object_identity": "unconfirmed", "input_type": "dominant components of independent raw-depth TSDF meshes",
              "source": source_info, "reference": target_info,
              "allowed_uniform_scale_range": [.3, 3.], "pca_axis_spread_ratios_target_over_source": axis_ratios,
              "initial_scale_hypotheses": scales, "candidates_tested": len(candidates),
              "coarse_point_counts": [len(coarse_source.points), len(coarse_target.points)],
              "best": best, "elapsed_seconds": time.monotonic() - started,
              "merged": False,
              "limitations": ["This is a bounded local/global PCA-hypothesis search, not a proof of global optimality.",
                              "Partial coverage, per-scan tracking artifacts and different acquisition scales can change the optimum.",
                              "Neither visual nor geometric mismatch establishes whether a project is an official demo or a different physical object.",
                              "No source data or previous registration results were modified."],
              "candidates": candidates}
    save_json(args.output / "report.json", result)
    lines = ["# 标准工程01与扫描03：尺度补充诊断", "", "身份和来源均未确认。本实验只检查均匀缩放能否显著解释已有几何差异，不合并任何数据。", "",
             "输入为各自独立深度 TSDF 网格最大三角连通片，1mm体素采样及离群过滤；初值包括24种PCA轴对应和多种尺度，随后以可选均匀尺度ICP细化。", "",
             "| 模式 | 01→03尺度 | 源→参考中位mm | 参考→源中位mm | 源2mm覆盖 | 参考2mm覆盖 | 双向2mm覆盖调和均值 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for label in ["rigid", "similarity"]:
        m = best[label]["metrics"]
        lines.append(f"| {label} | {m['uniform_scale_source01_to_reference03']:.5f} | {m['source_to_reference']['median_mm']:.3f} | {m['reference_to_source']['median_mm']:.3f} | {m['source_to_reference']['within_2mm']:.2%} | {m['reference_to_source']['within_2mm']:.2%} | {m['symmetric_2mm_coverage_harmonic']:.2%} |")
    lines += ["", "距离只衡量两份重建几何的一致性，不代表实物精度。有限搜索可能错过更好的解；若缩放后仍有明显双向残差，应表述为当前几何尚不能仅用均匀尺度解释，不能据此推断工程来源或物体身份。", ""]
    (args.output / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"candidates": len(candidates), "seconds": result["elapsed_seconds"],
                      "best": {k: v["metrics"] for k, v in best.items()}}), flush=True)


if __name__ == "__main__":
    main()

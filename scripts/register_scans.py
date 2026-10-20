"""Read-only registration experiments on saved point clouds.

The vendor files are inputs, never evidence of independently recovering frames.
All generated geometry and reports stay under --output. Distances are in the
input coordinate units (these projects are treated as millimetres).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import time

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

import numpy as np
import open3d as o3d


PALETTE = [[0.95, 0.40, 0.25], [0.15, 0.75, 0.95], [0.30, 0.80, 0.35], [0.80, 0.35, 0.95]]


def sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def pc_stats(pc) -> dict:
    a = np.asarray(pc.points)
    if not len(a):
        return {"points": 0}
    return {"points": len(a), "finite_points": int(np.isfinite(a).all(axis=1).sum()),
            "min": a.min(axis=0).tolist(), "max": a.max(axis=0).tolist(),
            "extent": np.ptp(a, axis=0).tolist(),
            "percentile_01": np.percentile(a, 1, axis=0).tolist(),
            "percentile_99": np.percentile(a, 99, axis=0).tolist(),
            "normals_available": bool(pc.has_normals()), "colors_available": bool(pc.has_colors())}


def mesh_stats(mesh) -> dict:
    verts = np.asarray(mesh.vertices)
    faces = np.asarray(mesh.triangles)
    if not len(faces):
        return {"vertices": len(verts), "triangles": 0}
    edges = np.sort(np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    _, comp_counts, areas = mesh.cluster_connected_triangles()
    return {"vertices": len(verts), "triangles": len(faces),
            "extent": np.ptp(verts, axis=0).tolist(),
            "boundary_edges": int((counts == 1).sum()),
            "nonmanifold_edges": int((counts > 2).sum()),
            "connected_components": len(comp_counts),
            "largest_component_triangles": max(comp_counts) if comp_counts else 0,
            "surface_area": float(mesh.get_surface_area()),
            "edge_closed": bool(not (counts == 1).any()),
            "watertight": None,
            "watertight_note": "Self-intersection testing is intentionally not run; zero boundary edges alone does not prove watertightness.",
            "component_areas_largest_5": sorted([float(x) for x in areas], reverse=True)[:5]}


def stage_input(src: Path, dst: Path) -> dict:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    source_hash = sha256(src)
    return {"source": str(src.resolve()), "staged": str(dst.resolve()),
            "source_sha256": source_hash, "staged_sha256": sha256(dst),
            "bytes": src.stat().st_size, "copy_verified": source_hash == sha256(dst)}


def inventory(item: Path, out: Path) -> list[dict]:
    scans = []
    for i, folder in enumerate(["share", "share(1)", "share(2)", "share(3)"], 1):
        roots = [p.parent for p in (item / folder).glob("*/raw_preview.ply")]
        if len(roots) != 1:
            raise RuntimeError(f"Expected exactly one project in {folder}, found {len(roots)}")
        root = roots[0]
        scan_id = f"scan_{i:02}"
        row = {"scan": scan_id, "project": str(root.resolve()), "files": {}}
        for kind, rel in {"fuse": "pointclouds/fuse.ply", "raw_preview": "raw_preview.ply", "mesh": "meshs/fuse_mesh.ply"}.items():
            p = root / rel
            if not p.is_file():
                row["files"][kind] = {"available": False}
                continue
            dst = out / "staged_inputs" / f"{scan_id}_{kind}.ply"
            info = {"available": True, "provenance": "vendor_original", **stage_input(p, dst)}
            if kind == "mesh":
                info["geometry"] = mesh_stats(o3d.io.read_triangle_mesh(str(dst)))
            else:
                info["geometry"] = pc_stats(o3d.io.read_point_cloud(str(dst)))
            row["files"][kind] = info
        row["selected_kind"] = "fuse" if row["files"]["fuse"]["available"] else "raw_preview"
        scans.append(row)
    save_json(out / "inventory.json", scans)
    return scans


def preprocess(pc, voxel: float):
    pc = copy.deepcopy(pc).remove_non_finite_points().remove_duplicated_points()
    down = pc.voxel_down_sample(voxel)
    clean, ids = down.remove_statistical_outlier(nb_neighbors=25, std_ratio=2.5)
    clean.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 3, max_nn=40))
    clean.normalize_normals()
    return clean, {"deduplicated_points": len(pc.points), "downsampled_points": len(down.points),
                   "retained_points": len(clean.points), "outlier_removed": len(down.points) - len(clean.points),
                   "voxel": voxel, "statistical_filter": {"neighbors": 25, "std_ratio": 2.5}}


def transform_points(a, transform):
    return a @ transform[:3, :3].T + transform[:3, 3]


def distance_summary(d, thresholds):
    d = np.asarray(d)
    return {"count": len(d), "median": float(np.median(d)), "p90": float(np.percentile(d, 90)),
            "p95": float(np.percentile(d, 95)), "mean": float(d.mean()),
            "trimmed_80_rmse": float(np.sqrt(np.mean(np.sort(d)[:max(1, int(len(d) * .8))] ** 2))),
            "coverage": {str(round(t, 6)): float(np.mean(d <= t)) for t in thresholds}}


def nearest_neighbors(target, query):
    # Batched Open3D CPU search avoids importing the optional scipy/ML stack.
    search = o3d.core.nns.NearestNeighborSearch(o3d.core.Tensor(np.ascontiguousarray(target, dtype=np.float64)))
    search.knn_index()
    indices, squared = search.knn_search(o3d.core.Tensor(np.ascontiguousarray(query, dtype=np.float64)), 1)
    return np.sqrt(squared.numpy().reshape(-1)), indices.numpy().reshape(-1)


def metrics(source, target, transform, thresholds):
    a = transform_points(np.asarray(source.points), transform)
    b = np.asarray(target.points)
    da, ia = nearest_neighbors(b, a)
    db, _ = nearest_neighbors(a, b)
    result = {"source_to_reference": distance_summary(da, thresholds),
              "reference_to_source": distance_summary(db, thresholds),
              "symmetric_chamfer_mean": float((da.mean() + db.mean()) / 2)}
    normals_a = np.asarray(source.normals) @ transform[:3, :3].T
    normals_b = np.asarray(target.normals)
    inlier = da <= thresholds[1]
    if inlier.any() and len(normals_a) == len(a) and len(normals_b) == len(b):
        dots = np.abs((normals_a[inlier] * normals_b[ia[inlier]]).sum(axis=1)).clip(0, 1)
        result["overlap_abs_normal_dot_median"] = float(np.median(dots))
        result["overlap_normal_fraction_within_30deg"] = float((dots >= np.cos(np.pi / 6)).mean())
    else:
        result["overlap_abs_normal_dot_median"] = None
        result["overlap_normal_fraction_within_30deg"] = None
    return result


def score(m, thresholds):
    a = m["source_to_reference"]
    b = m["reference_to_source"]
    narrow, broad = map(lambda t: str(round(t, 6)), thresholds[:2])
    # Source overlap is primary because a partial scan can legitimately cover a
    # small fraction of the complete reference. Reference coverage remains reported.
    return float(a["coverage"][narrow] * .65 + a["coverage"][broad] * .25
                 + b["coverage"][broad] * .10 - min(3, a["median"] / thresholds[0]) * .08)


def pca_transforms(source, target):
    a = np.asarray(source.points)
    b = np.asarray(target.points)
    ca, cb = np.median(a, axis=0), np.median(b, axis=0)
    _, va = np.linalg.eigh(np.cov((a - ca).T))
    _, vb = np.linalg.eigh(np.cov((b - cb).T))
    va, vb = va[:, ::-1], vb[:, ::-1]
    for perm in itertools.permutations(range(3)):
        p = np.eye(3)[:, perm]
        for signs in itertools.product([-1, 1], repeat=3):
            r = vb @ p @ np.diag(signs) @ va.T
            if np.linalg.det(r) < .99:
                continue
            transform = np.eye(4)
            transform[:3, :3] = r
            transform[:3, 3] = cb - r @ ca
            yield f"pca_{''.join(map(str, perm))}_{''.join('p' if x > 0 else 'm' for x in signs)}", transform


def refine(source, target, initial, distances, iterations=40):
    transform = initial.copy()
    last = None
    for d in distances:
        last = o3d.pipelines.registration.registration_icp(
            source, target, d, transform,
            o3d.pipelines.registration.TransformationEstimationPointToPlane(
                o3d.pipelines.registration.TukeyLoss(k=d)),
            o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=iterations))
        transform = last.transformation
    return transform, {"icp_fitness": float(last.fitness), "icp_inlier_rmse": float(last.inlier_rmse)}


def global_candidates(source, target, voxel):
    search = o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 5, max_nn=100)
    sf = o3d.pipelines.registration.compute_fpfh_feature(source, search)
    tf = o3d.pipelines.registration.compute_fpfh_feature(target, search)
    reg = o3d.pipelines.registration
    results = []
    for seed in [7, 29]:
        o3d.utility.random.seed(seed)
        result = reg.registration_ransac_based_on_feature_matching(
            source, target, sf, tf, True, voxel * 2,
            reg.TransformationEstimationPointToPoint(False), 3,
            [reg.CorrespondenceCheckerBasedOnEdgeLength(.9),
             reg.CorrespondenceCheckerBasedOnDistance(voxel * 2)],
            reg.RANSACConvergenceCriteria(45000, .999))
        results.append((f"fpfh_ransac_seed_{seed}", result.transformation,
                        {"global_fitness": float(result.fitness), "global_rmse": float(result.inlier_rmse)}))
    try:
        result = reg.registration_fgr_based_on_feature_matching(
            source, target, sf, tf, reg.FastGlobalRegistrationOption(maximum_correspondence_distance=voxel * 2))
        results.append(("fpfh_fast_global", result.transformation,
                        {"global_fitness": float(result.fitness), "global_rmse": float(result.inlier_rmse)}))
    except RuntimeError as exc:
        print(json.dumps({"method": "fpfh_fast_global", "error": str(exc)}), flush=True)
    return results


def acceptance(m, transform, thresholds):
    a = m["source_to_reference"]
    narrow, broad = map(lambda t: str(round(t, 6)), thresholds[:2])
    checks = {"rigid_transform": bool(np.isfinite(transform).all() and
              abs(np.linalg.det(transform[:3, :3]) - 1) < 1e-3 and
              np.linalg.norm(transform[:3, :3].T @ transform[:3, :3] - np.eye(3)) < 1e-3),
              "source_narrow_coverage_ge_60pct": a["coverage"][narrow] >= .60,
              "source_broad_coverage_ge_85pct": a["coverage"][broad] >= .85,
              "source_median_le_narrow_threshold": a["median"] <= thresholds[0],
              "overlap_normal_median_ge_0_85": (m["overlap_abs_normal_dot_median"] or 0) >= .85}
    return all(checks.values()), checks


def register_one(scan_id, source, reference, voxel, out):
    coarse_s, _ = preprocess(source, voxel * 2)
    coarse_t, _ = preprocess(reference, voxel * 2)
    fine_s, ps = preprocess(source, voxel * .5)
    fine_t, pt = preprocess(reference, voxel * .5)
    thresholds = [voxel, voxel * 2.5, voxel * 5]
    candidates = []
    identity = np.eye(4)
    identity[:3, 3] = coarse_t.get_center() - coarse_s.get_center()
    initial = [("centroid_translation", identity, {})]
    initial += [(name, t, {}) for name, t in pca_transforms(coarse_s, coarse_t)]
    initial += global_candidates(coarse_s, coarse_t, voxel * 2)
    for name, transform, more in initial:
        t, icp = refine(coarse_s, coarse_t, transform, [voxel * 7, voxel * 4], iterations=30)
        m = metrics(coarse_s, coarse_t, t, thresholds)
        candidates.append({"method": name, "initial_transform": transform.tolist(),
                           "transform": t.tolist(), "coarse_metrics": m,
                           "coarse_score": score(m, thresholds), **more, **icp})
    candidates.sort(key=lambda x: x["coarse_score"], reverse=True)
    for candidate in candidates[:8]:
        t, icp = refine(fine_s, fine_t, np.array(candidate["transform"]),
                        [voxel * 3, voxel * 1.5, voxel], iterations=55)
        m = metrics(fine_s, fine_t, t, thresholds)
        candidate.update({"transform": t.tolist(), "metrics": m, "score": score(m, thresholds), **icp})
    refined = sorted([c for c in candidates if "score" in c], key=lambda x: x["score"], reverse=True)
    best = refined[0]
    t = np.array(best["transform"])
    accepted, checks = acceptance(best["metrics"], t, thresholds)
    result = {"scan": scan_id, "units": "input_units_assumed_mm", "voxel": voxel,
              "distance_thresholds": thresholds, "preprocess_source": ps,
              "preprocess_reference": pt, "accepted": accepted, "acceptance_checks": checks,
              "best_method": best["method"], "transform_source_to_reference": t.tolist(),
              "metrics": best["metrics"], "candidate_count": len(candidates), "candidates": candidates,
              "caveat": "Automatic geometric gate; this is not proof of object identity or metrological accuracy."}
    save_json(out / f"{scan_id}_registration.json", result)
    aligned = copy.deepcopy(source).transform(t)
    aligned.paint_uniform_color(PALETTE[int(scan_id[-2:]) - 1])
    o3d.io.write_point_cloud(str(out / f"{scan_id}_aligned_candidate.ply"), aligned)
    return result, aligned


def render_projection(pcs, path, title):
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError:
        import sys
        # The app's bundled base runtime includes Pillow; no package install or
        # environment mutation is required for this optional plotting step.
        sys.path.append(str(Path(sys.base_prefix) / "Lib" / "site-packages"))
        from PIL import Image, ImageDraw
    canvas = Image.new("RGB", (1500, 560), (23, 28, 36))
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 15), title, fill=(240, 244, 250))
    samples = []
    for scan_id, pc in pcs:
        p = pc.voxel_down_sample(.9)
        samples.append((scan_id, np.asarray(p.points)))
    allpts = np.vstack([p for _, p in samples])
    center = (allpts.max(axis=0) + allpts.min(axis=0)) * .5
    bound = max(np.ptp(allpts, axis=0)) * 1.08
    for view, (ax, ay) in enumerate([(0, 1), (0, 2), (1, 2)]):
        x0 = view * 500
        draw.text((x0 + 20, 44), ["XY", "XZ", "YZ"][view], fill=(220, 225, 235))
        draw.rectangle((x0 + 10, 70, x0 + 490, 550), outline=(60, 70, 90))
        for scan_id, pts in samples:
            color = tuple(int(x * 255) for x in PALETTE[int(scan_id[-2:]) - 1])
            uv = (pts[:, [ax, ay]] - center[[ax, ay]]) / bound * 440
            uv[:, 0] += x0 + 250
            uv[:, 1] = 310 - uv[:, 1]
            for x, y in uv.astype(int):
                if x0 + 10 <= x < x0 + 490 and 70 <= y < 550:
                    draw.point((int(x), int(y)), fill=color)
    canvas.save(path)


def reconstruct(pcs, out, voxel, *, source_type="vendor_pointclouds", method="poisson"):
    combined = o3d.geometry.PointCloud()
    for _, pc in pcs:
        combined += pc
    input_points = len(combined.points)
    surface = combined.voxel_down_sample(voxel * .45)
    surface, _ = surface.remove_statistical_outlier(nb_neighbors=25, std_ratio=2.5)
    surface.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 2.5, max_nn=45))
    surface.orient_normals_consistent_tangent_plane(35)
    xyz, normals = np.asarray(surface.points), np.asarray(surface.normals)
    if np.median(np.sum((xyz - np.median(xyz, axis=0)) * normals, axis=1)) < 0:
        surface.normals = o3d.utility.Vector3dVector(-normals)
    o3d.io.write_point_cloud(str(out / "combined_voxel_surface_samples.ply"), surface)
    started = time.monotonic()
    if method == "ball_pivoting":
        mesh = o3d.geometry.TriangleMesh.create_from_point_cloud_ball_pivoting(
            surface, o3d.utility.DoubleVector([voxel * 1.2, voxel * 2.4]))
        untrimmed = len(mesh.vertices)
        remove = np.zeros(untrimmed, dtype=bool)
        faces = np.asarray(mesh.triangles)
        vertices = np.asarray(mesh.vertices)
        edge_max = np.maximum.reduce([np.linalg.norm(vertices[faces[:, j]] - vertices[faces[:, (j + 1) % 3]], axis=1) for j in range(3)])
        mesh.remove_triangles_by_mask(edge_max > voxel * 5)
        filename = "combined_ball_pivoting_supported_mesh.ply"
        method_description = "Rigid registration, voxel averaging, normal orientation, ball pivoting with radii 1.2/2.4 voxels and maximum triangle edge 5 voxels"
    else:
        mesh, density = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(surface, depth=8, n_threads=4)
        untrimmed = len(mesh.vertices)
        density = np.asarray(density)
        distances, _ = nearest_neighbors(np.asarray(surface.points), np.asarray(mesh.vertices))
        remove = (density < np.quantile(density, .02)) | (distances > voxel * 2.5)
        mesh.remove_vertices_by_mask(remove)
        filename = "combined_poisson_supported_mesh.ply"
        method_description = "Rigid registration, voxel averaging, normal orientation, Poisson depth 8, density/support trimming"
    mesh.remove_degenerate_triangles().remove_duplicated_triangles().remove_duplicated_vertices().remove_unreferenced_vertices()
    mesh.compute_vertex_normals()
    o3d.io.write_triangle_mesh(str(out / filename), mesh)
    final_d, _ = nearest_neighbors(np.asarray(surface.points), np.asarray(mesh.vertices))
    result = {"input_scans": [s for s, _ in pcs], "input_points_before_averaging": input_points,
              "surface_samples": len(surface.points), "surface_voxel": voxel * .45,
              "method": method_description, "mesh_file": filename,
              "not_cross_scan_raw_frame_reintegration": True, "source_type": source_type,
              "surface_reconstruction_seconds": time.monotonic() - started, "vertices_before_trim": untrimmed,
              "removed_vertices": int(remove.sum()), "support_trim_distance": voxel * 2.5,
              "mesh": mesh_stats(mesh),
              "vertex_distance_to_input_samples": distance_summary(final_d, [voxel, voxel * 2.5]),
              "limitations": ["Surface reconstruction may bridge gaps; triangles are not additional measurements. Ball pivoting constrains edge lengths and does not infer a watertight solid.",
                              "Distances to input samples are self-consistency metrics, not ground-truth accuracy.",
                              "Input acquisition or per-scan integration errors cannot be undone by one cross-scan rigid transform."]}
    save_json(out / "reconstruction.json", result)
    return result


def compare_raw_tsdf(registration_out, reconstruction_root, skip_mesh=False):
    """Evaluate independently integrated frames separately from vendor clouds."""
    inventory_rows = json.loads((registration_out / "inventory.json").read_text(encoding="utf-8"))
    vendor_summary = json.loads((registration_out / "summary.json").read_text(encoding="utf-8"))
    vendor_rows = {s["scan"]: s for s in inventory_rows}
    reg_by_id = {s["scan"]: s for s in vendor_summary["registrations"]}
    out = registration_out / "decoded_compare"
    out.mkdir(exist_ok=True)
    voxel = vendor_summary["voxel"]
    thresholds = [voxel, voxel * 2.5, voxel * 5]
    ref_id = vendor_summary["reference"]
    ref_row = vendor_rows[ref_id]
    vendor_reference = o3d.io.read_point_cloud(ref_row["files"][ref_row["selected_kind"]]["staged"])
    vendor_reference, _ = preprocess(vendor_reference, voxel * .5)
    results = []
    accepted = []
    for scan_id in ["scan_01", "scan_02", "scan_03", "scan_04"]:
        source_file = reconstruction_root / scan_id / "tsdf_pointcloud_mm.ply"
        if not source_file.is_file():
            results.append({"scan": scan_id, "available": False})
            continue
        source = o3d.io.read_point_cloud(str(source_file))
        clean, filtering = preprocess(source, voxel * .5)
        row = vendor_rows[scan_id]
        own_vendor = o3d.io.read_point_cloud(row["files"][row["selected_kind"]]["staged"])
        own_vendor, _ = preprocess(own_vendor, voxel * .5)
        own_metrics = metrics(clean, own_vendor, np.eye(4), thresholds)
        is_reference = scan_id == ref_id
        transform = np.eye(4) if is_reference else np.array(reg_by_id[scan_id]["transform_source_to_reference"])
        cross_metrics = metrics(clean, vendor_reference, transform, thresholds)
        own_a = own_metrics["source_to_reference"]
        own_coordinates_consistent = own_a["median"] <= voxel * 1.5 and own_a["coverage"][str(round(voxel * 2.5, 6))] >= .70
        cross_ok, checks = acceptance(cross_metrics, transform, thresholds)
        # Geometry gates do not establish object identity or sample provenance.
        # Do not hardcode a scan ID as a different object based on its name.
        include = bool(own_coordinates_consistent and cross_ok)
        aligned = copy.deepcopy(clean).transform(transform)
        aligned.paint_uniform_color(PALETTE[int(scan_id[-2:]) - 1])
        o3d.io.write_point_cloud(str(out / f"{scan_id}_raw_tsdf_aligned_candidate.ply"), aligned)
        item = {"scan": scan_id, "available": True, "input": str(source_file.resolve()),
                "input_sha256": sha256(source_file), "provenance": "independent_per_scan_raw_depth_tsdf",
                "stats": pc_stats(source), "preprocess": filtering,
                "identity_comparison_against_own_vendor": own_metrics,
                "same_coordinate_consistency_gate": own_coordinates_consistent,
                "comparison_against_vendor_reference_after_transform": cross_metrics,
                "transform_to_reference": transform.tolist(),
                "transform_provenance": "identity for reference, otherwise rigid transform estimated from vendor clouds",
                "cross_geometric_gate": checks, "object_identity": "not_established_by_registration",
                "accepted_for_combined_candidate": include,
                "warning": "Agreement against vendor output is self-consistency, not independent measurement ground truth; tracking pose validity is not established by a parsable matrix."}
        results.append(item)
        save_json(out / f"{scan_id}_comparison.json", item)
        render_projection([(ref_id, vendor_reference), (scan_id, aligned)], out / f"{scan_id}_raw_vs_vendor_reference.png",
                          f"{scan_id}: independent raw TSDF vs vendor reference; include={include}")
        if include:
            accepted.append((scan_id, aligned))
        print(json.dumps({"event": "raw_comparison", "scan": scan_id, "own_vendor_median": own_a["median"],
                          "coordinates_consistent": own_coordinates_consistent,
                          "cross_median": cross_metrics["source_to_reference"]["median"], "include": include}), flush=True)
    combined = None
    if len(accepted) >= 2 and not skip_mesh:
        combined = reconstruct(accepted, out, voxel, source_type="independent_per_scan_raw_depth_tsdf", method="ball_pivoting")
        render_projection(accepted, out / "raw_tsdf_combined_views.png", "Registered independent raw-depth TSDF clouds; source colors")
    save_json(out / "summary.json", {"reference": ref_id, "results": results,
              "accepted_for_combined_candidate": [s for s, _ in accepted], "combined_reconstruction": combined,
              "limitations": ["This stage combines already independently integrated per-scan TSDF surfaces; it does not jointly reintegrate all original depth frames.",
                              "Cross-scan transforms come from vendor cloud registration and are validated against raw candidates before inclusion.",
                              "Rejected entire scans remain available; proximity cropping is not treated as independent correctness."]})
    write_raw_readme(out)


def write_raw_readme(out):
    report = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    lines = ["# 独立逐帧 TSDF 结果的跨扫描比较与组合", "", "本目录与上一层厂商点云实验分开。输入是各工程通过深度帧及保存位姿独立重积分得到的 TSDF 表面点云；不是复制厂商融合结果。", "",
             "跨扫描刚体变换沿用上一层从厂商点云估计的变换，再用独立结果验证，因此不能称为完全不依赖厂商数据的跨扫描配准。", "",
             "距离单位按输入毫米约定。所有距离是与已有几何的自洽性比较，不是实物真值误差。", "",
             "| 扫描 | 对自身厂商点云中位差 mm | 对参考03中位差 mm | 对参考03的1mm覆盖 | 参考03对该扫描的1mm覆盖 | 纳入组合 |",
             "|---|---:|---:|---:|---:|---|"]
    for row in report["results"]:
        if not row.get("available"):
            lines.append(f"| {row['scan']} | 缺输入 | — | — | — | 否 |")
            continue
        own = row["identity_comparison_against_own_vendor"]["source_to_reference"]
        m = row["comparison_against_vendor_reference_after_transform"]
        a, b = m["source_to_reference"], m["reference_to_source"]
        lines.append(f"| {row['scan']} | {own['median']:.3f} | {a['median']:.3f} | {a['coverage']['1.0']:.2%} | {b['coverage']['1.0']:.2%} | {'是' if row['accepted_for_combined_candidate'] else '否'} |")
    lines += ["", "01当前几何匹配未通过，其是否官方样例及与另外三份的物体身份关系尚未确认，因此独立保留。02只有局部表面，单向源覆盖高、参考反向覆盖低符合局部扫描；不能由此声称补全了03。04可以找到大体对齐，但残差尾部较大，整体未通过一致性门限，因此保留候选供检查，没有整份强行加入。", "",
              "## 组合候选", "", "组合的是：" + ", ".join(report["accepted_for_combined_candidate"]) + "。"]
    reconstruction = report.get("combined_reconstruction")
    if reconstruction:
        mesh = reconstruction["mesh"]
        lines += ["", "- `combined_voxel_surface_samples.ply`：变换后按0.45mm体素平均并过滤的表面采样；不是简单拼接，也不是把所有原始深度帧联合重积分。",
                  "- `combined_ball_pivoting_supported_mesh.ply`：对组合采样重新做球枢轴三角化，半径1.2/2.4mm，最长三角边5mm。此方法保留大洞，不推断完整实体。",
                  f"- 实际结果：{reconstruction['surface_samples']:,}个表面采样，网格{mesh['vertices']:,}顶点、{mesh['triangles']:,}三角，{mesh['boundary_edges']:,}条边界边、{mesh['nonmanifold_edges']}条非流形边、{mesh['connected_components']}个连通片。",
                  "- 球枢轴网格顶点取自输入采样，所以顶点到采样距离为0是算法结构使然，不是零误差精度验证。",
                  "- 未完成自相交检测，不宣称水密、缺损已真实修复或相比厂商模型精度更高。"]
    lines += ["", "逐扫描变换、输入哈希、双向距离、覆盖率、法线一致性及门限判断见 `summary.json` 与 `scan_XX_comparison.json`。", ""]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")


def write_overlap_diagnostics(out):
    """Retain rejected geometry and show the near/far regions without merging it."""
    scans = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    by_id = {s["scan"]: s for s in scans}
    ref_id = summary["reference"]
    ref_item = by_id[ref_id]
    reference = o3d.io.read_point_cloud(ref_item["files"][ref_item["selected_kind"]]["staged"])
    reference, _ = preprocess(reference, summary["voxel"] * .5)
    diag = out / "overlap_diagnostics"
    diag.mkdir(exist_ok=True)
    rows = []
    for reg in summary["registrations"]:
        scan_id = reg["scan"]
        item = by_id[scan_id]
        source = o3d.io.read_point_cloud(item["files"][item["selected_kind"]]["staged"])
        source, _ = preprocess(source, summary["voxel"] * .5)
        aligned = source.transform(np.array(reg["transform_source_to_reference"]))
        distances, _ = nearest_neighbors(np.asarray(reference.points), np.asarray(aligned.points))
        threshold = summary["voxel"] * 2.5
        near = np.flatnonzero(distances <= threshold)
        far = np.flatnonzero(distances > threshold)
        inside = aligned.select_by_index(near.tolist())
        outside = aligned.select_by_index(far.tolist())
        inside.paint_uniform_color(PALETTE[int(scan_id[-2:]) - 1])
        outside.paint_uniform_color([1, .2, .15])
        o3d.io.write_point_cloud(str(diag / f"{scan_id}_near_reference_diagnostic.ply"), inside)
        o3d.io.write_point_cloud(str(diag / f"{scan_id}_far_reference_diagnostic.ply"), outside)
        if len(inside.points):
            render_projection([(ref_id, reference), (scan_id, inside)],
                              diag / f"{scan_id}_near_reference_views.png",
                              f"{scan_id}: near-reference subset only; diagnostic, not an accepted merge")
        rows.append({"scan": scan_id, "whole_scan_accepted": reg["accepted"],
                     "preprocessed_points": len(aligned.points), "distance_threshold": threshold,
                     "near_points": len(near), "far_points": len(far),
                     "near_fraction": len(near) / len(aligned.points),
                     "interpretation": "Filtering by proximity to a reference cannot establish independent correctness or justify merging a rejected scan."})
    save_json(diag / "diagnostics.json", rows)
    print(json.dumps({"event": "diagnostics_complete", "rows": rows}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--item", type=Path, default=Path("item"))
    parser.add_argument("--output", type=Path, default=Path("reports/four-scans/registration"))
    parser.add_argument("--reference", default="scan_03")
    parser.add_argument("--voxel", type=float, default=1.0)
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--skip-mesh", action="store_true")
    parser.add_argument("--diagnostics-only", action="store_true")
    parser.add_argument("--raw-tsdf-root", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    # Never allow an output directory inside an original project.
    if out.is_relative_to(args.item.resolve()):
        raise ValueError("Output must not be under original item directory")
    out.mkdir(parents=True, exist_ok=True)
    if args.raw_tsdf_root:
        compare_raw_tsdf(out, args.raw_tsdf_root.resolve(), skip_mesh=args.skip_mesh)
        return
    if args.diagnostics_only:
        write_overlap_diagnostics(out)
        return
    started = time.monotonic()
    scans = inventory(args.item.resolve(), out)
    print(json.dumps({"event": "inventory", "scans": [{"scan": x["scan"], "kind": x["selected_kind"],
                     "geometry": x["files"][x["selected_kind"]]["geometry"]} for x in scans]}), flush=True)
    if args.inventory_only:
        return
    clouds = {x["scan"]: o3d.io.read_point_cloud(x["files"][x["selected_kind"]]["staged"]) for x in scans}
    for scan_id, cloud in clouds.items():
        render_projection([(scan_id, cloud)], out / f"{scan_id}_input_views.png", f"{scan_id}: original vendor geometry")
    reference = clouds[args.reference]
    results = []
    accepted_pcs = [(args.reference, copy.deepcopy(reference).paint_uniform_color(PALETTE[int(args.reference[-2:]) - 1]))]
    for scan in scans:
        scan_id = scan["scan"]
        if scan_id == args.reference:
            continue
        print(json.dumps({"event": "register_start", "scan": scan_id}), flush=True)
        result, aligned = register_one(scan_id, clouds[scan_id], reference, args.voxel, out)
        results.append(result)
        render_projection([(args.reference, reference), (scan_id, aligned)], out / f"{scan_id}_candidate_views.png",
                          f"{scan_id} vs {args.reference}; accepted={result['accepted']}; vendor-derived")
        if result["accepted"]:
            accepted_pcs.append((scan_id, aligned))
        print(json.dumps({"event": "register_done", "scan": scan_id, "accepted": result["accepted"],
                          "method": result["best_method"], "checks": result["acceptance_checks"],
                          "metrics": result["metrics"]}), flush=True)
    render_projection(accepted_pcs, out / "accepted_combined_views.png", "Accepted registered vendor inputs; source colors")
    reconstruction = None
    if not args.skip_mesh and len(accepted_pcs) > 1:
        print(json.dumps({"event": "mesh_start", "scans": [s for s, _ in accepted_pcs]}), flush=True)
        reconstruction = reconstruct(accepted_pcs, out, args.voxel)
    inputs_unchanged = all(sha256(Path(info["source"])) == info["source_sha256"]
                           for s in scans for info in s["files"].values() if info["available"])
    summary = {"reference": args.reference, "input_type": "vendor_outputs",
               "units": "input_units_assumed_mm", "voxel": args.voxel,
               "accepted": [s for s, _ in accepted_pcs], "rejected": [r["scan"] for r in results if not r["accepted"]],
               "registrations": [{k: v for k, v in r.items() if k != "candidates"} for r in results],
               "reconstruction": reconstruction, "all_original_ply_sha256_unchanged": inputs_unchanged,
               "elapsed_seconds": time.monotonic() - started,
               "limitations": ["scan_01 identity and whether it is an official demo remain unresolved; geometric matching does not prove object identity.",
                               "A partial source can cover less of the reference; both directional metrics are retained.",
                               "Geometric acceptance is heuristic and requires visual review; no ground truth is supplied.",
                               "These results use saved vendor clouds; they do not establish raw frame pose recovery or proprietary fusion reproduction."]}
    save_json(out / "summary.json", summary)
    report = ["# Four-project cross-scan registration experiment", "", f"Reference: {args.reference}. Distance units assumed mm.",
              "", "Inputs are original vendor fuse/raw_preview point clouds. Their hashes and mesh quality are in inventory.json.",
              "No source item files were changed. Alignment candidates and rejected attempts are retained.", "",
              "| Scan | Decision | Method | Source median | Source p95 | Reference median |", "|---|---|---|---:|---:|---:|"]
    for r in results:
        a = r["metrics"]["source_to_reference"]
        b = r["metrics"]["reference_to_source"]
        report.append(f"| {r['scan']} | {'accept' if r['accepted'] else 'reject'} | {r['best_method']} | {a['median']:.4f} | {a['p95']:.4f} | {b['median']:.4f} |")
    report += ["", "Accepted scans: " + ", ".join(summary["accepted"]), "", "## Interpretation limits", ""]
    report += ["- " + s for s in summary["limitations"]]
    if reconstruction:
        report += ["", "## Generated surface", "", "combined_voxel_surface_samples.ply averages registered samples by voxel; this is not TSDF/raw-depth fusion.",
                   "combined_poisson_supported_mesh.ply is independently computed from those samples with Poisson and support trimming.",
                   "It remains derived from vendor point clouds. Filled or interpolated surfaces are not measured geometry."]
    (out / "README.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"event": "complete", "accepted": summary["accepted"], "rejected": summary["rejected"],
                      "input_hashes_unchanged": inputs_unchanged, "seconds": summary["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    main()

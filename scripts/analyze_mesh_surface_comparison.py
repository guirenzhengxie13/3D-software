"""Same-project mesh surface comparison, without any additional registration.

Uses area-uniform samples and closest points on triangles so differing vertex
density does not masquerade as geometric improvement or loss. Distances are
between processing results, never certified physical accuracy or defect area.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np
import open3d as o3d


def load_mesh(path):
    with tempfile.TemporaryDirectory(prefix="mesh-analysis-") as directory:
        temporary = Path(directory) / "input.ply"
        shutil.copyfile(path, temporary)
        mesh = o3d.io.read_triangle_mesh(str(temporary))
    if not len(mesh.vertices) or not len(mesh.triangles):
        raise ValueError(f"No triangle surface in {path}")
    mesh.compute_triangle_normals()
    return mesh


def transform_points(points, matrix):
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def region_masks(points, diagnostic_transform):
    q = transform_points(points, diagnostic_transform)
    return {"all": np.ones(len(q), bool), "head_box_y_ge_0": q[:, 1] >= 0,
            "middle_box_y_minus95_to_0": (q[:, 1] < 0) & (q[:, 1] >= -95),
            "base_box_y_lt_minus95": q[:, 1] < -95}


def mesh_stats(mesh, diagnostic_transform):
    xyz, faces = np.asarray(mesh.vertices), np.asarray(mesh.triangles)
    edges = np.sort(np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]])), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    boundary = unique[counts == 1]
    lengths = np.linalg.norm(xyz[boundary[:, 0]] - xyz[boundary[:, 1]], axis=1)
    midpoints = xyz[boundary].mean(axis=1)
    boundaries = {name: {"edges": int(mask.sum()), "length_mm": float(lengths[mask].sum())}
                  for name, mask in region_masks(midpoints, diagnostic_transform).items()}
    labels, tri_counts, areas = mesh.cluster_connected_triangles()
    tri_counts = np.asarray(tri_counts)
    return {"vertices": len(xyz), "triangles": len(faces), "surface_area_mm2": mesh.get_surface_area(),
            "components": len(tri_counts), "largest_component_triangle_fraction": float(tri_counts.max() / tri_counts.sum()),
            "nonmanifold_edges": int((counts > 2).sum()), "boundary": boundaries,
            "bounds_min_mm": xyz.min(0).tolist(), "bounds_max_mm": xyz.max(0).tolist()}


def sample_surface(mesh, count, seed):
    o3d.utility.random.seed(seed)
    cloud = mesh.sample_points_uniformly(count, use_triangle_normal=True)
    return np.asarray(cloud.points), np.asarray(cloud.normals)


def closest_surface(mesh, points, normals):
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
    result = scene.compute_closest_points(o3d.core.Tensor(points.astype(np.float32)))
    nearest = result["points"].numpy()
    target_normals = result["primitive_normals"].numpy()
    distances = np.linalg.norm(points - nearest, axis=1)
    agreement = np.abs(np.einsum("ij,ij->i", normals, target_normals))
    normal_angles = np.degrees(np.arccos(np.clip(agreement, -1, 1)))
    return distances, normal_angles, nearest


def distance_stats(values, angles, area):
    if not len(values):
        return {"samples": 0}
    common = values <= 1
    return {"samples": len(values), "median_mm": float(np.median(values)),
            "p90_mm": float(np.percentile(values, 90)), "p95_mm": float(np.percentile(values, 95)),
            "mean_mm": float(values.mean()),
            "within_mm": {str(t): float((values <= t).mean()) for t in (.5, 1., 2., 3.)},
            "estimated_area_farther_than_1mm_mm2": float(area * (values > 1).mean()),
            "normal_angle_in_common_1mm_median_deg": float(np.median(angles[common])) if common.any() else None,
            "normal_angle_in_common_1mm_p90_deg": float(np.percentile(angles[common], 90)) if common.any() else None}


def directional_analysis(source, target, count, seed, diagnostic_transform):
    points, normals = sample_surface(source, count, seed)
    distances, angles, nearest = closest_surface(target, points, normals)
    total_area = source.get_surface_area()
    masks = region_masks(points, diagnostic_transform)
    stats = {}
    for name, mask in masks.items():
        # Area fraction estimated by the same uniform surface samples.
        stats[name] = distance_stats(distances[mask], angles[mask], total_area * mask.mean())
    return stats, (points, distances, nearest)


def residual_plot(pair_name, directions, destination, diagnostic_transform):
    from PIL import Image, ImageDraw
    canvas = Image.new("RGB", (1500, 1160), (24, 29, 37))
    draw = ImageDraw.Draw(canvas)
    draw.text((15, 10), pair_name + " | triangle-surface residuals; no new ICP; not physical accuracy", fill="white")
    draw.text((15, 30), "Green <=0.5mm, yellow 0.5-1mm, orange 1-2mm, red >2mm. Separate directional samples.", fill="white")
    all_points = np.concatenate([transform_points(part[0], diagnostic_transform) for _, part in directions])
    center = (all_points.min(0) + all_points.max(0)) / 2
    span = float(np.ptp(all_points, axis=0).max() * 1.08)
    for row, (name, (points, distances, nearest)) in enumerate(directions):
        points = transform_points(points, diagnostic_transform)
        ids = np.linspace(0, len(points) - 1, min(len(points), 65000), dtype=int)
        points, distances = points[ids], distances[ids]
        # Draw far samples last so a coincident green surface cannot hide them.
        order = np.argsort(distances)
        colors = np.where((distances[:, None] <= .5), [80, 210, 125],
                 np.where((distances[:, None] <= 1), [255, 220, 75],
                 np.where((distances[:, None] <= 2), [255, 145, 55], [250, 75, 95]))).astype(np.uint8)
        draw.text((15, 65 + row * 540), name, fill="white")
        for view, (a, b, depth_axis) in enumerate(((0, 1, 2), (0, 2, 1), (1, 2, 0))):
            x0 = view * 500
            draw.text((x0 + 15, 85 + row * 540), ("XY", "XZ", "YZ")[view], fill="white")
            draw.rectangle((x0 + 10, 105 + row * 540, x0 + 490, 570 + row * 540), outline=(65, 75, 90))
            uv = (points[:, [a, b]] - center[[a, b]]) / span * 430
            uv[:, 0] += x0 + 250
            uv[:, 1] = 335 + row * 540 - uv[:, 1]
            for index in order:
                x, y = uv[index].astype(int)
                if x0 + 10 <= x <= x0 + 490 and 105 + row * 540 <= y <= 570 + row * 540:
                    draw.point((int(x), int(y)), fill=tuple(colors[index]))
    canvas.save(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("reports/four-scans"))
    parser.add_argument("--samples", type=int, default=200000)
    args = parser.parse_args()
    out = args.root / "comparison"
    out.mkdir(exist_ok=True)
    T = np.array(json.loads((args.root / "registration/scan_04_registration.json").read_text(encoding="utf-8"))["transform_source_to_reference"])
    results = []
    for scan_id, label in (("scan_01", "baseline"), ("scan_03", "baseline"),
                           ("scan_04", "baseline"), ("scan_04", "reference_assisted")):
        official_path = args.root / "registration/staged_inputs" / f"{scan_id}_mesh.ply"
        ours_path = args.root / "reconstruction" / scan_id / "tsdf_mesh_mm.ply"
        if label == "reference_assisted":
            ours_path = args.root / "reconstruction/scan_04_reference_assisted/scan_04/tsdf_mesh_mm.ply"
        official = load_mesh(official_path)
        ours = load_mesh(ours_path)
        if label == "reference_assisted":
            ours.transform(np.linalg.inv(T))
        # Comparisons stay in the same project's coordinates. ROI diagnostics
        # for scan04 use only the already fixed transform into scan03's frame.
        diagnostic = T if scan_id == "scan_04" else np.eye(4)
        forward, f_arrays = directional_analysis(official, ours, args.samples, 41, diagnostic)
        reverse, r_arrays = directional_analysis(ours, official, args.samples, 42, diagnostic)
        record = {"scan_id": scan_id, "variant": label, "unit": "mm", "samples_per_direction": args.samples,
                  "sampling": "area-uniform deterministic mesh samples, distances to target triangles",
                  "additional_registration": False,
                  "ours_to_project_transform": np.linalg.inv(T).tolist() if label == "reference_assisted" else np.eye(4).tolist(),
                  "official_mesh": mesh_stats(official, diagnostic), "ours_mesh": mesh_stats(ours, diagnostic),
                  "official_to_ours": forward, "ours_to_official": reverse,
                  "roi_note": "For scan03/04 diagnostic boxes in scan03 coordinates: head y>=0, middle -95<=y<0, base y<-95. Boxes are coarse locations, not anatomical segmentation.",
                  "limitations": ["Unmatched surface area is between algorithm outputs; it is not measured hole/defect area or known truth.",
                                  "Boundary edges include intentionally open bases as well as gaps; count alone cannot rank quality.",
                                  "Normal differences can reflect smoothing, noise, or geometry changes; no direction is certified more accurate.",
                                  "Reference-assisted scan04 depends on scan03; mapping it back does not make it independent."]}
        stem = f"analysis_{scan_id}_{label}"
        (out / f"{stem}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        residual_plot(scan_id + " " + label, [("Official surface samples -> ours triangles", f_arrays),
                      ("Ours surface samples -> official triangles", r_arrays)], out / f"{stem}.png", diagnostic)
        np.savez_compressed(out / f"analysis_mesh_{scan_id}_{label}.npz",
                            official_xyz=f_arrays[0], official_distances=f_arrays[1], official_nearest_xyz=f_arrays[2],
                            own_xyz=r_arrays[0], own_distances=r_arrays[1], own_nearest_xyz=r_arrays[2])
        results.append(record)
        print(json.dumps({"scan": scan_id, "variant": label, "official_to_ours": forward["all"], "ours_to_official": reverse["all"]}), flush=True)
    (out / "analysis_mesh_surface_summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

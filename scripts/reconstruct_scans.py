"""Reconstruct surfaces independently from decoded depth and saved poses.

All computation uses saved measurements. Vendor PLYs only enter the final
consistency report, never TSDF integration, filtering, or surface extraction.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import open3d as o3d

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reconstruction_probe.fusion_settings import effective_truncation_mm
from reconstruction_probe.sources import _read_ply_cloud
from reconstruction_probe.offline import read_global_registration_poses, file_sha256
from reconstruction_probe.poses import parse_compact_frame_pose, parse_frame_info_blob, _rigid_matrix
from reconstruction_probe.attribute_frames import parse_attribute_pose


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def write_geometry(path, geometry, coordinate_frame="saved_scan_coordinates"):
    mesh = isinstance(geometry, o3d.geometry.TriangleMesh)
    points = np.asarray(geometry.vertices if mesh else geometry.points)
    colors = np.asarray(geometry.vertex_colors if mesh else geometry.colors)
    normals = np.asarray(geometry.vertex_normals if mesh else geometry.normals)
    fields = [(name, "<f4") for name in ("x", "y", "z")]
    if len(normals) == len(points):
        fields += [(name, "<f4") for name in ("nx", "ny", "nz")]
    if len(colors) == len(points):
        fields += [(name, "u1") for name in ("red", "green", "blue")]
    records = np.empty(len(points), dtype=fields)
    for axis, name in enumerate(("x", "y", "z")):
        records[name] = points[:, axis] * 1000  # TSDF works in metres, output in mm.
    if len(normals) == len(points):
        for axis, name in enumerate(("nx", "ny", "nz")):
            records[name] = normals[:, axis]
    if len(colors) == len(points):
        for axis, name in enumerate(("red", "green", "blue")):
            records[name] = np.rint(np.clip(colors[:, axis], 0, 1) * 255).astype(np.uint8)
    header = ["ply", "format binary_little_endian 1.0", "comment units mm",
              "comment coordinates " + coordinate_frame,
              "comment reconstructed_from_saved_depth_and_pose_not_copied_vendor_geometry",
              f"element vertex {len(points)}"]
    for name, dtype in fields:
        header.append("property " + ("uchar" if dtype == "u1" else "float") + " " + name)
    if mesh:
        header += [f"element face {len(geometry.triangles)}", "property list uchar int vertex_indices"]
    header += ["end_header"]
    with path.open("wb") as stream:
        stream.write(("\n".join(header) + "\n").encode("ascii"))
        stream.write(records.tobytes())
        if mesh:
            faces = np.empty(len(geometry.triangles), dtype=[("count", "u1"), ("indices", "<i4", (3,))])
            faces["count"] = 3
            faces["indices"] = np.asarray(geometry.triangles)
            stream.write(faces.tobytes())


def summarize_distances(distances):
    return {"median_mm": float(np.median(distances)), "p90_mm": float(np.percentile(distances, 90)),
            "mean_mm": float(np.mean(distances)), "within_1mm": float(np.mean(distances < 1)),
            "within_2mm": float(np.mean(distances < 2))}


def consistency(points_mm, source_directory):
    results = {}
    for name, path in (("fuse", source_directory / "pointclouds" / "fuse.ply"),
                       ("raw_preview", source_directory / "raw_preview.ply")):
        if not path.exists():
            continue
        reference = _read_ply_cloud(o3d, path.resolve()).voxel_down_sample(.4)
        if reference.is_empty():
            continue
        results[name] = {
            "reconstructed_to_vendor": summarize_distances(np.asarray(points_mm.compute_point_cloud_distance(reference))),
            "vendor_to_reconstructed": summarize_distances(np.asarray(reference.compute_point_cloud_distance(points_mm))),
            "reference_points": len(reference.points),
            "meaning": "internal coordinate/surface consistency; vendor result is not independent ground truth",
        }
    return results


def clean_depth_edges(depth_mm, threshold_mm):
    """Omit pixels adjacent to large discontinuities instead of bridging them."""
    if threshold_mm <= 0:
        return depth_mm.copy(), 0
    valid = depth_mm > 0
    edge = np.zeros(depth_mm.shape, bool)
    for a, b in ((np.s_[:-1, :], np.s_[1:, :]), (np.s_[:, :-1], np.s_[:, 1:])):
        discontinuity = valid[a] & valid[b] & (np.abs(depth_mm[a] - depth_mm[b]) > threshold_mm)
        edge[a] |= discontinuity
        edge[b] |= discontinuity
    result = depth_mm.copy()
    result[edge] = 0
    return result, int(edge.sum())


def optical_to_pose_axes(manifest):
    signs = np.asarray(manifest.get("optical_to_pose_axes", [1., -1., -1.]), dtype=float)
    if signs.shape != (3,) or not np.isfinite(signs).all() or not np.all(np.abs(signs) == 1) or np.prod(signs) != 1:
        raise ValueError("Expected an explicitly supported proper axis-sign conversion")
    return signs


def stored_pose(folder, rid, global_matrices, prefer_global, overrides=None, pose_policy="auto"):
    if pose_policy not in ("auto", "stored", "optimized"):
        raise ValueError("Unknown pose selection policy")
    prefer_global = prefer_global and pose_policy != "stored"
    if overrides is not None:
        value = overrides.get(rid)
        if value is None:
            return None, None
        matrix = np.asarray(value, dtype="<f8")
        if matrix.shape != (4, 4):
            raise ValueError("Pose override must be 4x4")
        matrix = _rigid_matrix(matrix.tobytes(), 0, 1e-4).copy()
        return matrix, "explicit_pose_override"
    if prefer_global and rid in global_matrices:
        return global_matrices[rid].copy(), "global_register_pose.pose"
    optimized = folder / "pose_optimized.npy"
    if prefer_global and optimized.exists():
        matrix = np.asarray(np.load(optimized, allow_pickle=False), dtype="<f8")
        if matrix.shape != (4, 4):
            raise ValueError("Optimized pose must be 4x4")
        return _rigid_matrix(matrix.tobytes(), 0, 1e-4).copy(), "table_pose_optimized"
    if pose_policy == "optimized":
        return None, None
    attribute = folder / "frame_pose_attribute.bin"
    if attribute.exists():
        return parse_attribute_pose(attribute.read_bytes()), "Frame_Attr_pose"
    path = folder / "frame_info_bin.bin"
    if not path.exists():
        return None, None
    blob = path.read_bytes()
    parsed = parse_compact_frame_pose(blob) if len(blob) == 164 else parse_frame_info_blob(blob)
    matrix = parsed.matrix_at_16.copy()
    return matrix, "FrameInfo.bin matrix_at_16"


def reconstruction_bounds(decoded, selected, calibration, global_matrices, prefer_global, overrides=None,
                          axis_signs=None, pose_policy="auto"):
    lower = np.full(3, np.inf)
    upper = np.full(3, -np.inf)
    K = np.array(calibration["K"], float)
    signs = np.array([1., -1., -1.]) if axis_signs is None else axis_signs
    for item in selected:
        folder = decoded / f"frame_{item['id']:010d}"
        path = folder / "frame.npz"
        matrix, _ = stored_pose(folder, item["id"], global_matrices, prefer_global, overrides, pose_policy)
        if matrix is None or not path.exists():
            continue
        with np.load(path, allow_pickle=False) as arrays:
            depth = arrays["depth_mm"]
            height, width = depth.shape
            valid = np.flatnonzero(depth.ravel() > 0)[::8]
            v, u = np.divmod(valid, width)
            z = depth.ravel()[valid]
            x = (u * calibration["width"] / width - K[0, 2]) * z / K[0, 0]
            y = (v * calibration["height"] / height - K[1, 2]) * z / K[1, 1]
            points = (np.column_stack((x, y, z)) * signs) @ matrix[:3, :3].T + matrix[:3, 3]
            if len(points):
                lower = np.minimum(lower, points.min(0))
                upper = np.maximum(upper, points.max(0))
    if not np.isfinite(lower).all() or not np.isfinite(upper).all():
        raise ValueError("No valid depths with saved poses for volume bounds")
    return lower, upper


def reconstruct(decoded, out, voxel_mm=.6, truncation_mm=2.4, edge_threshold_mm=3.0, stride=1,
                prefer_global=True, pose_overrides=None, depth_filter=None, evaluate_vendor=True,
                coordinate_frame="independent_saved_scan_frame", reconstruction_note=None, pose_policy="auto",
                bounds_override_mm=None, tsdf_backend="uniform", tsdf_weight_threshold=0., frame_depth_filter=None):
    started = time.time()
    if depth_filter is not None and frame_depth_filter is not None:
        raise ValueError('Choose a depth filter with or without explicit frame identity')
    manifest = json.loads((decoded / "index.json").read_text(encoding="utf-8"))
    source = Path(manifest["source_directory"])
    resolved_output, resolved_source = out.resolve(), source.resolve()
    if resolved_output == resolved_source or resolved_source in resolved_output.parents:
        raise ValueError("Do not write reconstruction outputs inside the original project")
    output = out / manifest["scan_id"]
    output.mkdir(parents=True, exist_ok=True)
    K = np.array(manifest["intrinsics"]["Pl"]["K"], float)
    calibration_width = manifest["intrinsics"]["Pl"]["width"]
    calibration_height = manifest["intrinsics"]["Pl"]["height"]
    selected = manifest["frames"][::stride]
    signs = optical_to_pose_axes(manifest)
    global_path = source / "cache" / "global_register_pose.pose"
    global_matrices = read_global_registration_poses(global_path) if global_path.exists() else {}
    if bounds_override_mm is None:
        lower, upper = reconstruction_bounds(decoded, selected, manifest["intrinsics"]["Pl"], global_matrices,
                                             prefer_global, pose_overrides, signs, pose_policy)
    else:
        bounds = np.asarray(bounds_override_mm, dtype=float)
        if bounds.shape != (2, 3) or not np.isfinite(bounds).all() or np.any(bounds[1] <= bounds[0]):
            raise ValueError("Explicit volume bounds must contain two finite ordered XYZ corners")
        if depth_filter is None and frame_depth_filter is None:
            raise ValueError("Explicit ROI bounds require a corresponding depth selection filter")
        lower, upper = bounds
    length_mm = float(np.max(upper - lower) + 12)
    resolution = min(256, max(64, int(np.ceil(length_mm / voxel_mm))))
    effective_voxel_mm = length_mm / resolution
    if tsdf_backend == "tensor":
        effective_voxel_mm = voxel_mm
    elif tsdf_backend != "uniform":
        raise ValueError("Unknown TSDF backend")
    actual_truncation_mm = effective_truncation_mm(truncation_mm,effective_voxel_mm,tsdf_backend)
    origin_mm = (lower + upper) / 2 - length_mm / 2
    # The installed Windows Open3D 0.20 scalable implementation returned an
    # empty surface even for a known flat-depth control. Uniform TSDF passes
    # that control and provides a bounded-memory reconstruction here.
    if tsdf_backend == "tensor":
        from reconstruction_probe.tensor_tsdf import TensorTSDFVolume
        volume = TensorTSDFVolume(effective_voxel_mm/1000,actual_truncation_mm/1000,weight_threshold=tsdf_weight_threshold)
    else:
        volume = o3d.pipelines.integration.UniformTSDFVolume(
            length=length_mm / 1000, resolution=resolution,
            sdf_trunc=actual_truncation_mm / 1000,
            color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8,
            origin=origin_mm / 1000,
        )
    records = []
    input_points, removed_edges, colored_frames, removed_by_reference = 0, 0, 0, 0
    for index, item in enumerate(selected):
        rid = item["id"]
        folder = decoded / f"frame_{rid:010d}"
        npz_path = folder / "frame.npz"
        matrix, pose_source = stored_pose(folder, rid, global_matrices, prefer_global, pose_overrides, pose_policy)
        if not npz_path.exists() or matrix is None:
            records.append({"id": rid, "status": "skipped_missing_depth_or_pose"})
            continue
        with np.load(npz_path, allow_pickle=False) as arrays:
            depth = arrays["depth_mm"]
            rgba = arrays["rgba"] if "rgba" in arrays else None
            height, width = depth.shape
            color = np.full((height, width, 3), 165, np.uint8)
            if rgba is not None:
                if rgba.shape != (int((depth > 0).sum()), 4):
                    raise ValueError(f"RGBA alignment mismatch: {npz_path}")
                color[depth > 0] = rgba[:, :3]
                colored_frames += 1
            input_points += int((depth > 0).sum())
            reference_removed = 0
            if depth_filter is not None:
                depth, reference_removed = depth_filter(depth, matrix)
                removed_by_reference += reference_removed
            elif frame_depth_filter is not None:
                depth, reference_removed = frame_depth_filter(depth, matrix, rid)
                removed_by_reference += reference_removed
            depth, removed = clean_depth_edges(depth, edge_threshold_mm)
            removed_edges += removed
            intrinsic = o3d.camera.PinholeCameraIntrinsic(width, height,
                K[0, 0] * width / calibration_width, K[1, 1] * height / calibration_height,
                K[0, 2] * width / calibration_width, K[1, 2] * height / calibration_height)
            pose = matrix.copy()
            pose[:3, 3] /= 1000
            # The original four projects require Y/Z reversal. The observed
            # 6.1 attribute format uses optical axes directly, as separately
            # checked against preview geometry and marker correspondences.
            camera_to_scan = pose @ np.diag([*signs, 1.])
            extrinsic = np.linalg.inv(camera_to_scan)
            rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                o3d.geometry.Image(color), o3d.geometry.Image(depth.astype(np.float32)),
                depth_scale=1000., depth_trunc=2., convert_rgb_to_intensity=False)
            volume.integrate(rgbd, intrinsic, extrinsic)
            records.append({"id": rid, "status": "integrated", "pose_source": pose_source,
                            "valid_pixels": int((depth > 0).sum()), "edge_pixels_omitted": removed,
                            "reference_unsupported_pixels_omitted": reference_removed})
        if index % 100 == 0 or index + 1 == len(selected):
            print(f"{manifest['scan_id']}: {index + 1}/{len(selected)} depth records processed", flush=True)
    mesh = volume.extract_triangle_mesh()
    mesh.remove_duplicated_vertices()
    mesh.remove_duplicated_triangles()
    mesh.remove_degenerate_triangles()
    mesh.remove_unreferenced_vertices()
    mesh.compute_vertex_normals()
    points = volume.extract_point_cloud()
    if points.is_empty() or len(mesh.triangles) == 0:
        raise ValueError("TSDF reconstruction returned no supported surface")
    # Surface extraction does not close holes or create a watertight solid.
    write_geometry(output / "tsdf_pointcloud_mm.ply", points, coordinate_frame)
    write_geometry(output / "tsdf_mesh_mm.ply", mesh, coordinate_frame)
    mesh_for_obj = o3d.geometry.TriangleMesh(mesh)
    mesh_for_obj.scale(1000, center=(0, 0, 0))
    o3d.io.write_triangle_mesh(str((output / "tsdf_mesh_mm.obj").resolve()), mesh_for_obj,
                             write_vertex_colors=False, write_triangle_uvs=False)
    points_mm = o3d.geometry.PointCloud(points)
    points_mm.scale(1000, center=(0, 0, 0))
    comparisons = consistency(points_mm.voxel_down_sample(.6), source) if evaluate_vendor else {}
    clusters, counts, areas = mesh.cluster_connected_triangles()
    counts = np.asarray(counts)
    quality = {"point_count": len(points.points), "mesh_vertices": len(mesh.vertices),
               "mesh_triangles": len(mesh.triangles), "mesh_components": len(counts),
               "largest_component_triangle_fraction": float(counts.max() / counts.sum()),
               "is_edge_manifold_allowing_boundary": mesh.is_edge_manifold(allow_boundary_edges=True),
               "is_watertight": mesh.is_watertight(),
               "bounds_min_mm": points_mm.get_min_bound().tolist(),
               "bounds_max_mm": points_mm.get_max_bound().tolist()}
    report = {"scan_id": manifest["scan_id"], "source_directory": str(source),
              "decoded_index_sha256": file_sha256(decoded / "index.json"),
              "input_contract": "decoded/index.json and frame_*/frame.npz, pose_*.npy",
              "algorithm": "Open3D " + ("tensor VoxelBlockGrid" if tsdf_backend == "tensor" else "UniformTSDFVolume") + " depth integration and zero-crossing surface extraction",
              "tsdf_backend": tsdf_backend,
              "tensor_diagnostics": volume.diagnostics() if tsdf_backend == "tensor" else None,
              "unit": "mm", "coordinate_frame": coordinate_frame,
              "reconstruction_note": reconstruction_note,
              "camera_to_scan": "saved_pose @ diag(*optical_to_pose_axes,1), translation normalized mm-to-m for TSDF",
              "optical_to_pose_axes": signs.tolist(), "pose_policy": pose_policy,
              "Pl_intrinsics": manifest["intrinsics"]["Pl"],
              "requested_voxel_mm": voxel_mm, "voxel_mm": effective_voxel_mm,
              "volume_resolution": resolution if tsdf_backend == "uniform" else None,
              "volume_cube_length_mm": length_mm if tsdf_backend == "uniform" else None,
              "volume_origin_mm": origin_mm.tolist() if tsdf_backend == "uniform" else [0.,0.,0.],
              "requested_truncation_mm": truncation_mm,
              "sdf_truncation_mm": actual_truncation_mm,
              "volume_bounds_source": ("explicit_roi" if bounds_override_mm is not None else "sampled_saved_depth") if tsdf_backend == "uniform" else "active_sparse_blocks",
              "explicit_roi_bounds_mm": None if bounds_override_mm is None else np.asarray(bounds_override_mm).tolist(),
              "depth_edge_threshold_mm": edge_threshold_mm,
              "frame_stride": stride, "available_frames": len(manifest["frames"]),
              "integrated_frames": sum(record["status"] == "integrated" for record in records),
              "colored_frames": colored_frames, "input_valid_pixels": input_points,
              "omitted_discontinuity_pixels": removed_edges,
              "depth_selection_pixels_omitted": removed_by_reference,
              "depth_filter_used": depth_filter is not None or frame_depth_filter is not None,
              "depth_filter_receives_frame_id": frame_depth_filter is not None,
              "reference_unsupported_pixels_omitted": removed_by_reference,
              "quality": quality, "vendor_consistency_only": comparisons,
              "elapsed_seconds": time.time() - started,
              "frames": records,
              "limitations": [
                  "Saved frame count does not establish all physical sensor frames were retained.",
                  "Source pose generation/optimization stage is unknown; global file used where available.",
                  "TSDF trusts saved poses and does not repair tracking failures or optimize the trajectory.",
                  "No ground-truth accuracy or dimensional certification is claimed.",
                  "Missing surfaces remain unobserved; no watertight hole filling is performed.",
                  "Separate scan coordinate frames are not aligned by this script.",
                  "Vendor geometry is used only after reconstruction for consistency metrics.",
              ]}
    if pose_overrides is not None:
        report["limitations"] += ["This run uses explicit pose overrides; their provenance is in reconstruction_note and the caller experiment report, not independent accuracy evidence."]
        if depth_filter is not None or frame_depth_filter is not None:
            report["limitations"] += ["Explicit depth selection may discard genuinely new regions; its criterion and provenance are caller-defined."]
    write_json(output / "reconstruction.json", report)
    print(json.dumps({"scan_id": manifest["scan_id"], "frames": report["integrated_frames"],
                      "quality": quality, "elapsed_seconds": report["elapsed_seconds"]}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", type=Path, default=Path("reports/four-scans/decoded"))
    parser.add_argument("--out", type=Path, default=Path("reports/four-scans/reconstruction"))
    parser.add_argument("--scans", nargs="+", help="Default: all decoded projects with depth records")
    parser.add_argument("--voxel-mm", type=float, default=.6)
    parser.add_argument("--truncation-mm", type=float, default=2.4)
    parser.add_argument("--edge-mm", type=float, default=3.)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--backend", choices=("uniform","tensor"), default="uniform")
    parser.add_argument("--tsdf-weight-threshold", type=float, default=0., help="Tensor extraction weight threshold; not an independent confidence score")
    parser.add_argument("--stored-only", action="store_true")
    parser.add_argument("--optimized-only", action="store_true", help="Skip frames without a parsed optimized/global pose; do not infer that skipped frames are invalid")
    args = parser.parse_args()
    if args.voxel_mm <= 0 or args.truncation_mm <= args.voxel_mm or args.stride <= 0:
        parser.error("Positive voxel/stride and truncation > voxel are required")
    if args.stored_only and args.optimized_only:
        parser.error("Choose stored-only or optimized-only, not both")
    if args.tsdf_weight_threshold < 0 or (args.backend != "tensor" and args.tsdf_weight_threshold != 0):
        parser.error("A nonnegative weight threshold is only supported by the tensor backend")
    if args.scans is None:
        args.scans = [p.parent.name for p in sorted(args.decoded.glob("*/index.json"))
                      if json.loads(p.read_text(encoding="utf-8")).get("status", {}).get("depth_decoded", 0) > 0]
    if not args.scans:
        parser.error("No decoded projects with depth records")
    results = []
    for name in args.scans:
        results.append(reconstruct(args.decoded / name, args.out, args.voxel_mm,
            args.truncation_mm, args.edge_mm, args.stride, not args.stored_only,
            pose_policy="optimized" if args.optimized_only else ("stored" if args.stored_only else "auto"),
            tsdf_backend=args.backend,tsdf_weight_threshold=args.tsdf_weight_threshold))
    # Include completed earlier scans when running only a selected subset.
    completed = [json.loads(path.read_text(encoding="utf-8"))
                 for path in sorted(args.out.glob("scan_*/reconstruction.json"))]
    write_json(args.out / "reconstruction_summary.json", [{key: value for key, value in report.items() if key != "frames"} for report in completed])


if __name__ == "__main__":
    main()

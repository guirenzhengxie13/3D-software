"""Keep a weighted voxel summary of every decoded saved depth observation.

This complements TSDF surfaces: missing or inconsistent geometry remains
inspectable here, including the supplied scans' background and tracking errors.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import open3d as o3d

from reconstruct_scans import stored_pose, write_geometry, write_json, consistency, optical_to_pose_axes
from reconstruction_probe.offline import read_global_registration_poses


class VoxelAccumulator:
    def __init__(self, size_mm):
        self.size = size_mm
        self.keys = np.empty(0, np.int64)
        self.sums = np.empty((0, 3), np.float64)
        self.counts = np.empty(0, np.int64)
        self.pending = []
        self.pending_size = 0

    def add(self, points):
        self.pending.append(np.asarray(points, dtype=float))
        self.pending_size += len(points)
        if self.pending_size >= 1_000_000:
            self.flush()

    def flush(self):
        if not self.pending:
            return
        points = np.concatenate(self.pending)
        cells = np.floor(points / self.size).astype(np.int64) + (1 << 20)
        if np.any(cells < 0) or np.any(cells >= (1 << 21)):
            raise ValueError("Coordinates exceed voxel accumulator range")
        keys = (cells[:, 0] << 42) | (cells[:, 1] << 21) | cells[:, 2]
        order = np.argsort(keys)
        keys, points = keys[order], points[order]
        first = np.r_[0, np.flatnonzero(np.diff(keys)) + 1]
        keys, sums = keys[first], np.add.reduceat(points, first, axis=0)
        counts = np.diff(np.r_[first, len(points)])
        if len(self.keys):
            both_keys = np.r_[self.keys, keys]
            both_sums = np.concatenate((self.sums, sums))
            both_counts = np.r_[self.counts, counts]
            order = np.argsort(both_keys)
            both_keys = both_keys[order]
            first = np.r_[0, np.flatnonzero(np.diff(both_keys)) + 1]
            keys = both_keys[first]
            sums = np.add.reduceat(both_sums[order], first, axis=0)
            counts = np.add.reduceat(both_counts[order], first)
        self.keys, self.sums, self.counts = keys, sums, counts
        self.pending.clear()
        self.pending_size = 0

    def points(self):
        self.flush()
        return self.sums / self.counts[:, None]


def process(decoded, output, voxel_mm):
    index = json.loads((decoded / "index.json").read_text(encoding="utf-8"))
    source = Path(index["source_directory"])
    global_file = source / "cache" / "global_register_pose.pose"
    global_matrices = read_global_registration_poses(global_file) if global_file.exists() else {}
    K = np.array(index["intrinsics"]["Pl"]["K"], float)
    signs = optical_to_pose_axes(index)
    cw, ch = index["intrinsics"]["Pl"]["width"], index["intrinsics"]["Pl"]["height"]
    accumulator = VoxelAccumulator(voxel_mm)
    frame_count = 0
    input_points = 0
    for item in index["frames"]:
        folder = decoded / f"frame_{item['id']:010d}"
        path = folder / "frame.npz"
        matrix, _ = stored_pose(folder, item["id"], global_matrices, True)
        if matrix is None or not path.exists():
            continue
        with np.load(path, allow_pickle=False) as data:
            depth = data["depth_mm"]
            height, width = depth.shape
            ids = np.flatnonzero(depth.ravel() > 0)
            v, u = np.divmod(ids, width)
            z = depth.ravel()[ids]
            x = (u * cw / width - K[0, 2]) * z / K[0, 0]
            y = (v * ch / height - K[1, 2]) * z / K[1, 1]
            points = (np.column_stack((x, y, z)) * signs) @ matrix[:3, :3].T + matrix[:3, 3]
            accumulator.add(points)
            input_points += len(points)
            frame_count += 1
    points_mm = accumulator.points()
    if int(accumulator.counts.sum()) != input_points:
        raise RuntimeError("Voxel support conservation failed")
    folder = output / index["scan_id"]
    folder.mkdir(parents=True, exist_ok=True)
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points_mm / 1000)
    write_geometry(folder / "voxel_all_observations_mm.ply", cloud)
    np.savez_compressed(folder / "voxel_support.npz", points_mm=points_mm.astype(np.float32),
                        observation_counts=accumulator.counts)
    cloud_mm = o3d.geometry.PointCloud(cloud)
    cloud_mm.scale(1000, center=(0, 0, 0))
    report = {"scan_id": index["scan_id"], "frames": frame_count, "input_valid_observations": input_points,
              "voxel_count": len(points_mm), "voxel_mm": voxel_mm, "unit": "mm",
              "observation_count_conserved": int(accumulator.counts.sum()) == input_points,
              "support_counts_percentiles": np.percentile(accumulator.counts, [0, 50, 90, 99, 100]).tolist(),
              "vendor_consistency_only": consistency(cloud_mm, source),
              "meaning": "Exact count-weighted voxel centroids from every available valid saved depth pixel; no depth-edge filtering, no registration refinement, no hole fill.",
              "limitations": ["Observation counts are repeated saved pixels, not independent measurements or calibrated confidence.",
                              "Background and tracking mistakes are intentionally retained.",
                              "Saved pose stage and complete physical frame retention are unknown."]}
    mesh_file = folder / "tsdf_mesh_mm.ply"
    if mesh_file.exists():
        mesh = o3d.io.read_triangle_mesh(str(mesh_file.resolve()))
        labels, triangle_counts, _ = mesh.cluster_connected_triangles()
        triangle_counts = np.asarray(triangle_counts)
        dominant = int(triangle_counts.argmax())
        candidate = o3d.geometry.TriangleMesh(mesh)
        candidate.remove_triangles_by_mask(np.asarray(labels) != dominant)
        candidate.remove_unreferenced_vertices()
        candidate.scale(.001, center=(0, 0, 0))
        write_geometry(folder / "tsdf_dominant_component_candidate_mm.ply", candidate)
        report["dominant_component_candidate"] = {
            "kept_triangles": len(candidate.triangles), "input_triangles": len(mesh.triangles),
            "fraction_kept": float(triangle_counts[dominant] / triangle_counts.sum()),
            "warning": "Largest component only; for incomplete scan_02 this may discard real disconnected object parts. It does not fix tracking distortion.",
        }
    write_json(folder / "voxel_fusion.json", report)
    print(json.dumps({"scan_id": index["scan_id"], "frames": frame_count,
                      "observations": input_points, "voxels": len(points_mm)}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", type=Path, default=Path("reports/four-scans/decoded"))
    parser.add_argument("--out", type=Path, default=Path("reports/four-scans/reconstruction"))
    parser.add_argument("--scans", nargs="+", default=["scan_01", "scan_02", "scan_03", "scan_04"])
    parser.add_argument("--voxel-mm", type=float, default=.6)
    args = parser.parse_args()
    if not np.isfinite(args.voxel_mm) or args.voxel_mm <= 0:
        parser.error("voxel size must be positive")
    results = [process(args.decoded / name, args.out, args.voxel_mm) for name in args.scans]
    write_json(args.out / "voxel_fusion_summary.json", results)


if __name__ == "__main__":
    main()

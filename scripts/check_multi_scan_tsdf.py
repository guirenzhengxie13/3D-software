"""Synthetic end-to-end control for compound-frame, raw-depth joint fusion."""

import os
os.environ.setdefault('OMP_NUM_THREADS', '4')

import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
import open3d as o3d

from experiment_multi_scan_tsdf import integrate_arm


def main():
    cache = Path('.cache').resolve(); cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='multi-scan-control-', dir=cache) as temporary:
        root = Path(temporary); sources = []; before = {}
        angle = np.deg2rad(37.); registration = np.array([[np.cos(angle), -np.sin(angle), 0, 72.], [np.sin(angle), np.cos(angle), 0, -25.], [0, 0, 1, 120.], [0, 0, 0, 1.]])
        for scan_id, transform, side, calibration_size in [('synthetic_A', np.eye(4), 'left', 1), ('synthetic_B', registration, 'right', 2)]:
            decoded = root / scan_id; decoded.mkdir(); frames = []
            K = np.array([[200., 0, 32.], [0, 200., 24.], [0, 0, 1.]])
            K[:2] *= calibration_size
            index = dict(scan_id=scan_id, optical_to_pose_axes=[1, 1, 1], intrinsics=dict(Pl=dict(width=64*calibration_size, height=48*calibration_size, K=K.tolist())), frames=frames)
            for rid in range(4):
                folder = decoded / f'frame_{rid:010d}'; folder.mkdir(); depth = np.zeros((48, 64), np.float32)
                if side == 'left':
                    depth[8:40, 10:32] = 500.
                else:
                    depth[8:40, 32:54] = 500.
                rgba = np.tile(np.array([45, 170, 90, 255], np.uint8), (int((depth > 0).sum()), 1))
                np.savez_compressed(folder / 'frame.npz', depth_mm=depth, rgba=rgba, color_layout_version=2)
                np.save(folder / 'pose_optimized.npy', np.linalg.inv(transform)); frames.append(dict(id=rid))
            (decoded / 'index.json').write_text(json.dumps(index), encoding='utf-8')
            sources.append(dict(decoded=decoded, index=index, transform=transform, shared_id='synthetic_A'))
        for path in root.rglob('*'):
            if path.is_file():
                before[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        results = []; clouds = []
        for label, chosen in [('target_only', sources[:1]), ('source_only_registered', sources[1:]), ('joint_raw_depth', sources)]:
            result = integrate_arm(label, chosen, root / label); results.append(result)
            cloud = o3d.io.read_point_cloud(str(root / label / 'tsdf_pointcloud_mm.ply')); points = np.asarray(cloud.points); clouds.append(points)
            if len(points) < 100 or np.max(np.abs(points[:, 2] - 500.)) > .01:
                raise AssertionError('Metric plane depth or extraction incorrect')
            np.testing.assert_allclose(np.asarray(cloud.colors).mean(0), np.array([45, 170, 90])/255, atol=1/255)
        if clouds[0][:, 0].max() > 0 or clouds[1][:, 0].min() < -1:
            raise AssertionError('Source-to-shared registration or source raster calibration incorrect')
        if not (clouds[2][:, 0].min() < -40 and clouds[2][:, 0].max() > 40):
            raise AssertionError('Joint volume lost complementary source geometry')
        joint = {row['scan_id']:row for row in results[2]['source_contributions']}
        if results[2]['integrated_frames'] != 8 or any(r['source_contributions'][0] != joint[r['source_contributions'][0]['scan_id']] for r in results[:2]):
            raise AssertionError('Compound frame IDs collided or source contributions changed')
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest in before.items()):
            raise AssertionError('Synthetic source input modified')
        print(json.dumps(dict(status='passed', controls=['known_500mm_plane', 'source_local_id_collision', 'nontrivial_registration_and_mm_to_m', 'different_calibration_raster_sizes', 'complementary_partial_depth_surfaces', 'physical_RGB', 'paired_source_digests', 'source_immutability'], actual_sensor_accuracy_verified=False)))


if __name__ == '__main__':
    main()

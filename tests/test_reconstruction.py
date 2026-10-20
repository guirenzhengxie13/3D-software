"""Small numerical and format checks for the offline reconstruction helpers."""
from pathlib import Path
import sys
import tempfile
import struct
import unittest

import numpy as np
import open3d as o3d

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from reconstruct_scans import clean_depth_edges, stored_pose, optical_to_pose_axes, reconstruction_bounds
from fuse_depth_points import VoxelAccumulator
from reconstruction_probe.poses import FrameInfoFormatError


class ReconstructionHelperTests(unittest.TestCase):
    def test_schema_axes_and_optimized_pose_policy_are_preserved(self):
        np.testing.assert_array_equal(optical_to_pose_axes({}), [1, -1, -1])
        np.testing.assert_array_equal(optical_to_pose_axes({"optical_to_pose_axes": [1, 1, 1]}), [1, 1, 1])
        with self.assertRaises(ValueError):
            optical_to_pose_axes({"optical_to_pose_axes": [1, 1, -1]})
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            stored, optimized = np.eye(4), np.eye(4)
            stored[:3, 3] = [10, 20, 30]
            optimized[:3, 3] = [11, 22, 33]
            (folder / "frame_pose_attribute.bin").write_bytes(struct.pack("<I", 1) + stored.astype("<f8").tobytes())
            self.assertEqual(stored_pose(folder, 0, {}, True, pose_policy="optimized"), (None, None))
            np.save(folder / "pose_optimized.npy", optimized)
            np.testing.assert_array_equal(stored_pose(folder, 0, {}, True)[0], optimized)
            np.testing.assert_array_equal(stored_pose(folder, 0, {}, False)[0], stored)

    def test_attribute_bounds_keep_positive_optical_depth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "frame_0000000000"
            folder.mkdir()
            np.savez_compressed(folder / "frame.npz", depth_mm=np.array([[200]], np.float32))
            (folder / "frame_pose_attribute.bin").write_bytes(struct.pack("<I", 1) + np.eye(4).astype("<f8").tobytes())
            calibration = {"K": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "width": 1, "height": 1}
            low, high = reconstruction_bounds(root, [{"id": 0}], calibration, {}, True, axis_signs=np.ones(3))
            np.testing.assert_array_equal(low, [0, 0, 200])
            np.testing.assert_array_equal(high, [0, 0, 200])

    def test_depth_edges_do_not_treat_missing_measurements_as_surfaces(self):
        depth = np.array([[0, 100, 101], [0, 100, 120]], np.float32)
        original = depth.copy()
        filtered, removed = clean_depth_edges(depth, 3)
        np.testing.assert_array_equal(filtered, [[0, 100, 0], [0, 0, 0]])
        np.testing.assert_array_equal(depth, original)
        self.assertEqual(removed, 3)

    def test_stored_pose_rejects_unknown_format_and_nonrigid_matrix(self):
        header = bytes.fromhex("0000000001040002000000000c000000")
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            path = folder / "frame_info_bin.bin"
            matrix = np.eye(4)
            path.write_bytes(header + matrix.astype("<f8").tobytes() + bytes(20))
            actual, _ = stored_pose(folder, 0, {}, False)
            np.testing.assert_array_equal(actual, matrix)
            path.write_bytes(bytes(16) + matrix.astype("<f8").tobytes() + bytes(20))
            with self.assertRaises(FrameInfoFormatError):
                stored_pose(folder, 0, {}, False)
            matrix[0, 0] = 2
            path.write_bytes(header + matrix.astype("<f8").tobytes() + bytes(20))
            with self.assertRaises(FrameInfoFormatError):
                stored_pose(folder, 0, {}, False)

    def test_refined_pose_override_must_also_be_rigid(self):
        matrix = np.eye(4)
        matrix[0, 0] = -1
        with self.assertRaises(FrameInfoFormatError):
            stored_pose(Path("."), 0, {}, False, {0: matrix})

    def test_voxel_fusion_preserves_observation_weights_across_batches(self):
        accumulator = VoxelAccumulator(1.)
        accumulator.add(np.array([[.1, .1, .1], [.2, .2, .2]]))
        accumulator.flush()
        accumulator.add(np.array([[.9, .9, .9], [1.1, 1.1, 1.1]]))
        points = accumulator.points()
        np.testing.assert_allclose(points, [[.4, .4, .4], [1.1, 1.1, 1.1]])
        np.testing.assert_array_equal(accumulator.counts, [3, 1])
        self.assertEqual(int(accumulator.counts.sum()), 4)

    def test_uniform_tsdf_plane_control_has_expected_metric_depth(self):
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.full((30, 40, 3), 100, np.uint8)),
            o3d.geometry.Image(np.full((30, 40), 200, np.uint16)),
            depth_scale=1000, depth_trunc=1, convert_rgb_to_intensity=False)
        volume = o3d.pipelines.integration.UniformTSDFVolume(
            length=.5, resolution=64, sdf_trunc=.02,
            color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8,
            origin=np.array([-.25, -.25, 0.]))
        volume.integrate(rgbd, o3d.camera.PinholeCameraIntrinsic(40, 30, 60, 60, 20, 15), np.eye(4))
        points = np.asarray(volume.extract_point_cloud().points)
        self.assertGreater(len(points), 20)
        self.assertAlmostEqual(float(np.median(points[:, 2])), .2, delta=.015)


if __name__ == "__main__":
    unittest.main()

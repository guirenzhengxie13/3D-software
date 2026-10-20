"""Known-motion controls for descriptive turntable pose diagnostics."""

import unittest
import numpy as np
from scipy.spatial.transform import Rotation

from reconstruction_probe.turntable import diagnose_fixed_axis


def sequence():
    axis = np.array([.2, 1., -.3])
    axis /= np.linalg.norm(axis)
    point = np.array([13., -7., 21.])
    base = np.eye(4)
    base[:3, :3] = Rotation.from_euler("xyz", [12, 21, -33], degrees=True).as_matrix()
    base[:3, 3] = [140., 25., -70.]
    angles = np.deg2rad(np.linspace(0, 420, 85))
    rs = Rotation.from_rotvec(angles[:, None] * axis).as_matrix()
    turns = np.repeat(np.eye(4)[None], len(angles), axis=0)
    turns[:, :3, :3] = rs
    turns[:, :3, 3] = np.einsum("nij,j->ni", np.eye(3) - rs, point)
    return turns @ base, axis, point


class TurntableTests(unittest.TestCase):
    def test_known_axis_and_nonzero_pivot_are_recovered_across_full_turn(self):
        poses, axis, point = sequence()
        report, arrays = diagnose_fixed_axis(poses)
        recovered = np.array(report["axis_direction_in_scan_frame"])
        self.assertGreater(abs(recovered @ axis), 1 - 1e-10)
        center = np.array(report["axis_point_minimum_norm_mm"])
        self.assertLess(np.linalg.norm(np.cross(center - point, axis)), 1e-8)
        self.assertLess(report["camera_origin_model_residual_mm"]["max"], 1e-8)
        self.assertLess(report["rotation_residual_deg"]["max"], 1e-8)
        self.assertAlmostEqual(report["unwrapped_angle_span_deg"], 420., places=7)
        np.testing.assert_allclose(arrays["model_poses"], poses, atol=1e-8)

    def test_shared_camera_basis_conversion_cancels_in_relative_model(self):
        poses, _, _ = sequence()
        other = poses @ np.diag([1., -1., -1., 1.])
        a, _ = diagnose_fixed_axis(poses)
        b, _ = diagnose_fixed_axis(other)
        np.testing.assert_allclose(a["axis_direction_in_scan_frame"], b["axis_direction_in_scan_frame"], atol=1e-10)
        np.testing.assert_allclose(a["axis_point_minimum_norm_mm"], b["axis_point_minimum_norm_mm"], atol=1e-8)

    def test_deviation_is_reported_without_silently_correcting_input(self):
        poses, _, _ = sequence()
        poses[40, :3, 3] += [15, -12, 8]
        before = poses.copy()
        report, arrays = diagnose_fixed_axis(poses)
        self.assertGreater(report["camera_origin_model_residual_mm"]["max"], 10)
        np.testing.assert_array_equal(poses, before)
        np.testing.assert_array_equal(arrays["saved_poses"], before)

    def test_insufficient_rotation_and_nonrigid_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Insufficient rotation"):
            diagnose_fixed_axis(np.repeat(np.eye(4)[None], 5, axis=0))
        poses, _, _ = sequence()
        poses[2, 0, 0] = 5
        with self.assertRaisesRegex(ValueError, "rigid"):
            diagnose_fixed_axis(poses)


if __name__ == "__main__":
    unittest.main()

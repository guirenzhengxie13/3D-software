import unittest

import numpy as np

from reconstruction_probe.local_surface_evidence import project_local_planes


class LocalSurfaceEvidenceTests(unittest.TestCase):
    calibration = dict(width=5, height=5, K=[[2000., 0, 2], [0, 2000., 2], [0, 0, 1]])

    def test_grazing_plane_distinguishes_axial_and_normal_distance(self):
        v, u = np.indices((5, 5)); depth = 500 / (1 + 10*(u-2)/2000)
        result = project_local_planes([[0., 0, 496]], np.eye(4), depth, self.calibration, [1, 1, 1])
        self.assertAlmostEqual(result.axial_delta_mm[0], 4.)
        self.assertAlmostEqual(result.signed_point_to_plane_mm[0], 4 / np.sqrt(101), places=8)
        self.assertAlmostEqual(result.abs_view_normal_dot[0], 1 / np.sqrt(101), places=8)
        self.assertLess(result.plane_rms_mm[0], 1e-6)
        self.assertTrue(result.spans_two_dimensions[0])

    def test_result_is_invariant_to_saved_pose_and_axis_convention(self):
        depth = np.full((5, 5), 500.); pose = np.array([[0., -1, 0, 200], [1, 0, 0, 100], [0, 0, 1, 50], [0, 0, 0, 1]])
        for signs in [[1, 1, 1], [1, -1, -1]]:
            optical = np.array([0., 0, 496]); point = pose[:3, :3] @ (optical*signs) + pose[:3, 3]
            result = project_local_planes(point[None, :], pose, depth, self.calibration, signs)
            self.assertAlmostEqual(result.signed_point_to_plane_mm[0], 4.)
            self.assertAlmostEqual(result.abs_view_normal_dot[0], 1.)

    def test_missing_and_collinear_depth_cannot_claim_a_surface_plane(self):
        depth = np.zeros((5, 5)); depth[2, :] = 500.
        result = project_local_planes([[0., 0, 496]], np.eye(4), depth, self.calibration, [1, 1, 1])
        self.assertFalse(result.spans_two_dimensions[0])
        empty = project_local_planes([[0., 0, -1]], np.eye(4), depth, self.calibration, [1, 1, 1])
        self.assertEqual(len(empty.point_indices), 0)


if __name__ == '__main__':
    unittest.main()

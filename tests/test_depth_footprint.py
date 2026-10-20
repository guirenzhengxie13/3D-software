import unittest

import numpy as np

from reconstruction_probe.depth_footprint import project_depth_footprints


class DepthFootprintTests(unittest.TestCase):
    calibration = dict(width=5, height=5, K=[[1, 0, 2], [0, 1, 2], [0, 0, 1]])

    def project(self, points, depth, radius=1):
        return project_depth_footprints(points, np.eye(4), depth, self.calibration, [1, 1, 1], radius)

    def test_flat_plane_retains_a_free_space_discrepancy(self):
        result = self.project([[0, 0, 496]], np.full((5, 5), 500.))
        np.testing.assert_array_equal(result.valid_neighbors, [9])
        np.testing.assert_array_equal(result.center_delta_mm, [4])
        np.testing.assert_array_equal(result.minimum_delta_mm, [4])
        np.testing.assert_array_equal(result.maximum_delta_mm, [4])

    def test_step_crossing_exposes_single_pixel_sensitivity_without_claiming_support(self):
        depth = np.full((5, 5), 500.); depth[:, :2] = 490.
        result = self.project([[0, 0, 496]], depth)
        self.assertEqual(result.center_delta_mm[0], 4)
        self.assertEqual(result.minimum_delta_mm[0], -6)
        self.assertEqual(result.maximum_delta_mm[0], 4)
        self.assertEqual(result.minimum_absolute_delta_mm[0], 4)

    def test_missing_depth_and_image_border_do_not_create_neighbor_duplicates(self):
        depth = np.full((5, 5), 500.); depth[0, 1] = 0; depth[1, 0] = np.nan
        result = self.project([[-1000, -1000, 500], [0, 0, -1]], depth)
        np.testing.assert_array_equal(result.point_indices, [0])
        np.testing.assert_array_equal(result.valid_neighbors, [2])
        center = self.project([[0, 0, 500]], depth, radius=0)
        np.testing.assert_array_equal(center.valid_neighbors, [1])
        with self.assertRaises(ValueError):
            self.project([[0, 0, 500]], depth, radius=True)


if __name__ == '__main__':
    unittest.main()

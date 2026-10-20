import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from scipy.spatial import cKDTree

from reconstruction_probe.marker_refinement import rigid_alignment, refine_marker_points


class MarkerRefinementTests(unittest.TestCase):
    def test_planar_markers_recover_proper_rigid_transform(self):
        source = np.array([[0, 0, 0], [30, 0, 0], [0, 40, 0], [30, 40, 0]], float)
        R = Rotation.from_euler("xyz", [4, -6, 12], degrees=True).as_matrix()
        target = source @ R.T + [10, 20, 30]
        T = rigid_alignment(source, target)
        np.testing.assert_allclose(source @ T[:3, :3].T + T[:3, 3], target, atol=1e-10)
        self.assertAlmostEqual(np.linalg.det(T[:3, :3]), 1.)

    def test_refinement_improves_unused_marker_positions_and_omits_far_outlier(self):
        rng = np.random.default_rng(7)
        reference = rng.normal(size=(30, 3)) * 40
        rotation = Rotation.from_euler("z", .3, degrees=True).as_matrix()
        observed = reference @ rotation.T + [.3, -.2, .1]
        train = np.concatenate((observed[::2], [[1000, 1000, 1000]]))
        T = refine_marker_points(train, reference)
        heldout = observed[1::2]
        after = heldout @ T[:3, :3].T + T[:3, 3]
        self.assertLess(cKDTree(reference).query(after)[0].max(), 1e-8)

    def test_degenerate_nonfinite_and_nonpositive_weights_fail(self):
        with self.assertRaises(ValueError):
            rigid_alignment(np.zeros((4, 3)), np.zeros((4, 3)))
        points = np.eye(3)
        with self.assertRaises(ValueError):
            rigid_alignment(points, points, [1, -1, 1])
        with self.assertRaises(ValueError):
            refine_marker_points(points, points + 1000)
        with self.assertRaises(ValueError):
            refine_marker_points(np.full((3, 3), np.nan), points)


if __name__ == "__main__":
    unittest.main()

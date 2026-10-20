"""Numerical regression cases for fixed-lattice, two-way support comparison.

These tests distinguish geometric support from point density and exercise the
negative-coordinate and threshold boundaries used by the comparison viewer.
"""
from __future__ import annotations

import unittest

import numpy as np

from reconstruction_probe.comparison import compare_point_sets, voxel_representatives


def voxel_map(centroids, keys, counts):
    return {tuple(map(int, key)): (np.asarray(point), int(count))
            for point, key, count in zip(centroids, keys, counts)}


class FixedLatticeTests(unittest.TestCase):
    def test_negative_coordinates_use_floor_and_exact_cell_boundaries(self):
        points = np.array([[-.01, 0, 0], [-.49, 0, 0], [-.5, 0, 0],
                           [-.500001, 0, 0], [.01, 0, 0], [.49, 0, 0], [.5, 0, 0]])
        centroids, keys, counts = voxel_representatives(points, voxel_mm=.5)
        cells = voxel_map(centroids, keys, counts)
        self.assertEqual(set(cells), {(-2, 0, 0), (-1, 0, 0), (0, 0, 0), (1, 0, 0)})
        self.assertEqual(cells[(-1, 0, 0)][1], 3)
        np.testing.assert_allclose(cells[(-1, 0, 0)][0], [-1 / 3, 0, 0], atol=1e-15)
        np.testing.assert_allclose(cells[(0, 0, 0)][0], [.25, 0, 0], atol=1e-15)

    def test_representatives_are_sample_weighted_centroids_not_cell_centers(self):
        points = np.array([[.01, .02, .03], [.01, .02, .03], [.40, .20, .10], [1., 1., 1.]])
        result = voxel_representatives(points, voxel_mm=.5)
        cells = voxel_map(*result)
        self.assertEqual(cells[(0, 0, 0)][1], 3)
        np.testing.assert_allclose(cells[(0, 0, 0)][0], points[:3].mean(axis=0), atol=1e-15)
        self.assertFalse(np.allclose(cells[(0, 0, 0)][0], [.25, .25, .25]))
        self.assertEqual(sum(int(x) for x in result[2]), len(points))

    def test_shared_lattice_does_not_move_with_each_cloud_minimum(self):
        own = np.array([[.49, 0, 0], [1.01, 0, 0]])
        official = np.array([[.01, 0, 0], [.48, 0, 0], [1.20, 0, 0]])
        _, own_keys, _ = voxel_representatives(own, voxel_mm=.5)
        _, official_keys, _ = voxel_representatives(official, voxel_mm=.5)
        expected = {(0, 0, 0), (2, 0, 0)}
        self.assertEqual({tuple(x) for x in own_keys}, expected)
        self.assertEqual({tuple(x) for x in official_keys}, expected)

    def test_nonzero_shared_origin_and_input_permutation_are_stable(self):
        origin = np.array([2., -4., 1.])
        points = origin + np.array([[.1, .2, .3], [.4, .3, .2], [.7, .1, .1]])
        original = points.copy()
        a = voxel_map(*voxel_representatives(points, voxel_mm=.5, origin=origin))
        b = voxel_map(*voxel_representatives(points[::-1], voxel_mm=.5, origin=origin))
        self.assertEqual(set(a), {(0, 0, 0), (1, 0, 0)})
        self.assertEqual(set(a), set(b))
        for key in a:
            np.testing.assert_allclose(a[key][0], b[key][0], atol=1e-15)
            self.assertEqual(a[key][1], b[key][1])
        np.testing.assert_array_equal(points, original)

    def test_invalid_voxel_and_invalid_points_fail_explicitly(self):
        good = np.array([[0., 0., 0.]])
        for voxel in [0., -.5, np.nan, np.inf]:
            with self.subTest(voxel=voxel), self.assertRaises(ValueError):
                voxel_representatives(good, voxel_mm=voxel)
        for bad in [np.empty((0, 3)), np.zeros((2, 2)), np.zeros(3),
                    np.array([[np.nan, 0, 0]]), np.array([[0, np.inf, 0]])]:
            with self.subTest(shape=bad.shape), self.assertRaises(ValueError):
                voxel_representatives(bad)


class BidirectionalSupportTests(unittest.TestCase):
    def test_equal_clouds_have_zero_distances_and_all_points_supported(self):
        points = np.array([[0., 0, 0], [-1., 2., 3.], [5., 4., -6.]])
        original = points.copy()
        result = compare_point_sets(points, points[::-1], thresholds=(.5, 1., 2.))
        np.testing.assert_array_equal(result["own_distances"], np.zeros(3))
        np.testing.assert_array_equal(result["official_distances"], np.zeros(3))
        for key in ["0.5", "1", "2"]:
            for side in ["own", "official"]:
                self.assertEqual(result["stats"][key][side]["common"], 3)
                self.assertEqual(result["stats"][key][side]["unique"], 0)
                self.assertEqual(result["stats"][key][side]["commonFraction"], 1.)
        np.testing.assert_array_equal(points, original)

    def test_threshold_is_inclusive_and_distances_are_mm_not_squared_mm(self):
        result = compare_point_sets(np.array([[0., 0, 0]]), np.array([[.5, 0, 0]]), thresholds=(.5,))
        np.testing.assert_allclose(result["own_distances"], [.5], rtol=0, atol=1e-15)
        np.testing.assert_allclose(result["official_distances"], [.5], rtol=0, atol=1e-15)
        self.assertEqual(result["stats"]["0.5"]["own"]["common"], 1)
        self.assertEqual(result["stats"]["0.5"]["official"]["common"], 1)

    def test_asymmetric_missing_surface_has_independent_directional_coverage(self):
        own = np.array([[0., 0, 0], [1., 0, 0]])
        official = np.array([[0., 0, 0], [10., 0, 0]])
        before_own, before_official = own.copy(), official.copy()
        result = compare_point_sets(own, official, thresholds=(.5, 1., 2.))
        np.testing.assert_allclose(result["own_distances"], [0., 1.])
        np.testing.assert_allclose(result["official_distances"], [0., 9.])
        np.testing.assert_array_equal(result["own_nearest_indices"], [0, 0])
        np.testing.assert_array_equal(result["official_nearest_indices"], [0, 1])
        stats = result["stats"]["1"]
        self.assertEqual(stats["own"]["common"], 2)
        self.assertEqual(stats["own"]["unique"], 0)
        self.assertEqual(stats["official"]["common"], 1)
        self.assertEqual(stats["official"]["unique"], 1)
        self.assertEqual(stats["own"]["commonFraction"], 1.)
        self.assertEqual(stats["official"]["commonFraction"], .5)
        self.assertEqual(stats["medianOwn"], .5)
        self.assertEqual(stats["medianOfficial"], 4.5)
        np.testing.assert_array_equal(own, before_own)
        np.testing.assert_array_equal(official, before_official)

    def test_common_support_is_not_a_one_to_one_pair_count(self):
        own = np.array([[0., 0, 0], [.8, 0, 0]])
        official = np.array([[.4, 0, 0]])
        result = compare_point_sets(own, official, thresholds=(.5,))
        stats = result["stats"]["0.5"]
        self.assertEqual(stats["own"]["common"], 2)
        self.assertEqual(stats["official"]["common"], 1)
        self.assertEqual(stats["own"]["unique"], 0)
        self.assertEqual(stats["official"]["unique"], 0)
        # Either tied official->own index is valid; verify the exported lookup
        # computes the same distance instead of assuming an implementation tie rule.
        self.assert_nearest_index_consistency(own, official, result)

    def test_float64_threshold_boundary_is_not_rounded_to_float32(self):
        official = np.array([[.50000001, 0, 0]], dtype=np.float64)
        result = compare_point_sets(np.zeros((1, 3)), official, thresholds=(.5,))
        self.assertGreater(float(result["own_distances"][0]), .5)
        self.assertEqual(result["stats"]["0.5"]["own"]["common"], 0)
        self.assertEqual(result["stats"]["0.5"]["official"]["common"], 0)

    def test_nearest_indices_match_exported_points_and_plain_distances(self):
        own = np.array([[1., 2., 3.], [4., -5., 6.], [-7., 8., 9.]])
        official = np.array([[3., 1., 2.], [-6., 7., 10.], [5., -4., 8.], [40., 40., 40.]])
        result = compare_point_sets(own, official)
        self.assert_nearest_index_consistency(own, official, result)

    def assert_nearest_index_consistency(self, own, official, result):
        for points, others, index_name, distance_name in [
            (own, official, "own_nearest_indices", "own_distances"),
            (official, own, "official_nearest_indices", "official_distances"),
        ]:
            indices = np.asarray(result[index_name])
            self.assertEqual(indices.shape, (len(points),))
            self.assertTrue(np.issubdtype(indices.dtype, np.integer))
            self.assertTrue(np.all((indices >= 0) & (indices < len(others))))
            expected = np.linalg.norm(points - others[indices], axis=1)
            np.testing.assert_allclose(result[distance_name], expected, rtol=1e-12, atol=1e-12)

    def test_empty_nonfinite_or_malformed_clouds_raise_on_either_side(self):
        good = np.zeros((1, 3))
        for bad in [np.empty((0, 3)), np.zeros((2, 2)), np.zeros(3),
                    np.array([[np.nan, 0, 0]]), np.array([[0, 0, np.inf]])]:
            for own, official in [(bad, good), (good, bad)]:
                with self.subTest(shape=bad.shape), self.assertRaises(ValueError):
                    compare_point_sets(own, official)

    def test_nonpositive_or_nonfinite_thresholds_raise(self):
        good = np.zeros((1, 3))
        for threshold in [0., -.5, np.nan, np.inf]:
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                compare_point_sets(good, good, thresholds=(threshold,))


if __name__ == "__main__":
    unittest.main()

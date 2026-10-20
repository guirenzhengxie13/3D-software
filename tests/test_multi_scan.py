import unittest

import numpy as np

from reconstruction_probe.multi_scan import FrameKey, registered_camera_to_object_m, scaled_intrinsics


class MultiScanContractTests(unittest.TestCase):
    def test_compound_identity_preserves_collisions_and_large_vendor_ids(self):
        keys = [FrameKey('A', 0), FrameKey('B', 0), FrameKey('A', 2**40)]
        self.assertEqual(len(set(keys)), 3)
        for scan, frame in [('', 0), ('A', True), ('A', -1), ('A', 1.5)]:
            with self.assertRaises(ValueError):
                FrameKey(scan, frame)

    def test_noncommuting_composition_scales_all_translations_after_registration(self):
        registration = np.array([[0., -1, 0, 100], [1, 0, 0, -30], [0, 0, 1, 200], [0, 0, 0, 1]])
        camera = np.eye(4); camera[:3, 3] = [10, 20, 500]
        optical_mm = np.array([5., 10, 400, 1.])
        for axes in ([1., 1, 1], [1., -1, -1]):
            result = registered_camera_to_object_m(registration, camera, axes)
            expected = registration @ camera @ np.diag([*axes, 1.]) @ optical_mm
            np.testing.assert_allclose((result @ np.r_[optical_mm[:3] / 1000, 1.])[:3], expected[:3] / 1000)
            np.testing.assert_array_equal(camera[:3, 3], [10, 20, 500])
        for bad in [np.diag([2., 1, 1, 1]), np.diag([-1., 1, 1, 1])]:
            with self.assertRaises(ValueError):
                registered_camera_to_object_m(bad, camera, [1, 1, 1])
        with self.assertRaises(ValueError):
            registered_camera_to_object_m(registration, camera, [-1, 1, 1])

    def test_calibration_size_is_distinct_from_saved_depth_size(self):
        calibration = dict(width=1600, height=1200, K=[[1500, 0, 800], [0, 1500, 860], [0, 0, 1]])
        result = scaled_intrinsics(calibration, 800, 600)
        np.testing.assert_array_equal(result, [[750, 0, 400], [0, 750, 430], [0, 0, 1]])
        with self.assertRaises(ValueError):
            scaled_intrinsics(calibration, 0, 600)


if __name__ == '__main__':
    unittest.main()

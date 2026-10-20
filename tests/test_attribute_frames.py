"""Controls for changed headers, color order and marker attribute layouts."""

import struct
import unittest
import numpy as np

from reconstruction_probe.attribute_frames import (
    decode_attribute_depth, parse_attribute_markers, parse_attribute_pose, split_jpeg_attribute)


class AttributeFormatTests(unittest.TestCase):
    def test_twenty_byte_header_and_abgr_to_rgba_keep_pixel_order(self):
        header = struct.pack("<5I", 3, 2, 2, 0x10001, 0)
        blob = header + bytes([0b00100001]) + np.array([200., 300.], "<f4").tobytes() + bytes([255, 10, 20, 30, 128, 40, 50, 60])
        frame = decode_attribute_depth(blob, 3, 2)
        np.testing.assert_array_equal(frame.depth_mm, [[200, 0, 0], [0, 0, 300]])
        np.testing.assert_array_equal(frame.rgba, [[30, 20, 10, 255], [60, 50, 40, 128]])
        for bad in (blob[:-1], blob + b"x", blob[:20] + bytes([0b10100001]) + blob[21:]):
            with self.assertRaises(ValueError):
                decode_attribute_depth(bad)
        with self.assertRaisesRegex(ValueError, "dimensions"):
            decode_attribute_depth(blob, 2, 3)

    def test_no_color_empty_and_unknown_header_cases(self):
        frame = decode_attribute_depth(struct.pack("<5I", 2, 2, 0, 0x10000, 0) + b"\0")
        self.assertIsNone(frame.rgba)
        np.testing.assert_array_equal(frame.depth_mm, np.zeros((2, 2)))
        for code, opaque in ((1, 0), (0x10002, 0), (0x10000, 1)):
            with self.assertRaises(ValueError):
                decode_attribute_depth(struct.pack("<5I", 2, 2, 0, code, opaque) + b"\0")

    def test_pose_matrix_offset_and_rigid_validation(self):
        matrix = np.eye(4)
        matrix[:3, 3] = [2, -3, 4]
        blob = struct.pack("<I", 1) + matrix.astype("<f8").tobytes()
        np.testing.assert_array_equal(parse_attribute_pose(blob), matrix)
        for bad in (blob[:-1], struct.pack("<I", 2) + blob[4:]):
            with self.assertRaises(ValueError):
                parse_attribute_pose(bad)
        matrix[0, 0] = -1
        with self.assertRaises(ValueError):
            parse_attribute_pose(struct.pack("<I", 1) + matrix.astype("<f8").tobytes())

    def test_jpeg_is_preserved_and_not_silently_found_by_scanning_bytes(self):
        jpeg = b"\xff\xd8example\xff\xd9"
        blob = struct.pack("<3I", 1, 0, len(jpeg)) + jpeg
        self.assertEqual(split_jpeg_attribute(blob), jpeg)
        for bad in (blob[:-1], blob + b"x", b"xxxx" + blob):
            with self.assertRaises(ValueError):
                split_jpeg_attribute(bad)

    def test_local_and_global_marker_prefixes_and_opaque_tails(self):
        for global_frame, stride, version, dtype in ((False, 36, 2, "<f4"), (True, 104, 3, "<f8")):
            prefix = np.array([1, 2, 300, 0, 0, -1], dtype).tobytes()
            raw = prefix + bytes([0xA5]) * (stride - len(prefix))
            blob = struct.pack("<2I", version, 1) + raw
            parsed = parse_attribute_markers(blob, global_frame=global_frame)
            np.testing.assert_array_equal(parsed.xyz, [[1, 2, 300]])
            np.testing.assert_array_equal(parsed.direction_candidate, [[0, 0, -1]])
            self.assertEqual(parsed.raw_records.tobytes(), raw)
            with self.assertRaises(ValueError):
                parse_attribute_markers(blob[:-1], global_frame=global_frame)


if __name__ == "__main__":
    unittest.main()

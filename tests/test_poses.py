"""Synthetic FrameInfo fixtures; no private sample data is distributed here."""

import struct
import unittest

import numpy as np

from reconstruction_probe.poses import FrameInfoFormatError, parse_frame_info_blob


def make_blob(counts=(0, 0, 0), first=None, second=None):
    first = np.eye(4) if first is None else np.asarray(first)
    second = np.eye(4) if second is None else np.asarray(second)
    return b"".join([
        bytes(range(16)), first.astype("<f8").tobytes(),
        struct.pack("<I", counts[0]), b"P" * (counts[0] * 24),
        struct.pack("<I", counts[1]), b"A" * (counts[1] * 16),
        b"opaque!!", second.astype("<f8").tobytes(),
        struct.pack("<I", counts[2]), b"T" * (counts[2] * 8),
    ])


class StoredFrameInfoTests(unittest.TestCase):
    def test_empty_array_292_byte_layout_and_opaque_fields(self):
        blob = make_blob()
        self.assertEqual(len(blob), 292)
        parsed = parse_frame_info_blob(blob)
        self.assertEqual(parsed.counts, (0, 0, 0))
        self.assertEqual(parsed.second_matrix_offset, 160)
        self.assertEqual(parsed.opaque_header, bytes(range(16)))
        self.assertEqual(parsed.opaque_between_matrices, b"opaque!!")
        self.assertIsNone(parsed.translation_unit)
        np.testing.assert_array_equal(parsed.matrix_at_16, np.eye(4))
        np.testing.assert_array_equal(parsed.second_matrix, np.eye(4))

    def test_observed_sizes_move_second_matrix_and_keep_stored_values(self):
        first = np.array([[0, -1, 0, 20], [1, 0, 0, -30], [0, 0, 1, 40], [0, 0, 0, 1]])
        second = np.eye(4)
        second[:3, 3] = [-4, 5, 6]
        for count in (5, 7, 8, 9, 10, 11, 14):
            with self.subTest(count=count):
                blob = make_blob((count, count, count), first, second)
                parsed = parse_frame_info_blob(blob, translation_unit="mm")
                self.assertEqual(len(blob), 292 + 48 * count)
                self.assertEqual(parsed.second_matrix_offset, 160 + 40 * count)
                self.assertEqual(parsed.translation_unit, "mm")
                np.testing.assert_array_equal(parsed.matrix_at_16, first)
                np.testing.assert_array_equal(parsed.second_matrix, second)

    def test_counts_are_independent_and_records_preserved(self):
        parsed = parse_frame_info_blob(make_blob((2, 3, 4)))
        self.assertEqual(parsed.counts, (2, 3, 4))
        self.assertEqual(parsed.second_matrix_offset, 160 + 24 * 2 + 16 * 3)
        self.assertEqual(parsed.records_24, b"P" * 48)
        self.assertEqual(parsed.records_16, b"A" * 48)
        self.assertEqual(parsed.records_8, b"T" * 32)

    def test_result_does_not_alias_mutable_input_and_matrices_stay_read_only(self):
        blob = bytearray(make_blob())
        parsed = parse_frame_info_blob(blob)
        blob[:] = b"x" * len(blob)
        np.testing.assert_array_equal(parsed.matrix_at_16, np.eye(4))
        for matrix in (parsed.matrix_at_16, parsed.second_matrix):
            with self.assertRaises(ValueError):
                matrix[0, 0] = 5
            with self.assertRaises(ValueError):
                matrix.setflags(write=True)

    def test_truncations_and_trailing_bytes_rejected(self):
        blob = make_blob((2, 3, 4))
        for end in (0, 16, 143, 145, 195, 250, len(blob) - 1):
            with self.subTest(end=end), self.assertRaises(FrameInfoFormatError):
                parse_frame_info_blob(blob[:end])
        with self.assertRaisesRegex(FrameInfoFormatError, "trailing"):
            parse_frame_info_blob(blob + b"extra")

    def test_untrusted_counts_and_configured_limit_rejected(self):
        blob = bytearray(make_blob((1, 1, 1)))
        for offset in (144, 172, 328):
            broken = blob.copy()
            struct.pack_into("<I", broken, offset, 0xFFFFFFFF)
            with self.subTest(offset=offset), self.assertRaises(FrameInfoFormatError):
                parse_frame_info_blob(broken)
        with self.assertRaises(FrameInfoFormatError):
            parse_frame_info_blob(make_blob((4, 0, 0)), max_entries=3)
        parsed = parse_frame_info_blob(make_blob(), max_entries=0)
        self.assertEqual(parsed.counts, (0, 0, 0))

    def test_invalid_first_and_second_rigid_transforms_rejected(self):
        cases = []
        for name in ("scale", "reflection", "nonfinite", "homogeneous"):
            matrix = np.eye(4)
            if name == "scale": matrix[0, 0] = 2
            if name == "reflection": matrix[0, 0] = -1
            if name == "nonfinite": matrix[0, 3] = np.nan
            if name == "homogeneous": matrix[3, 3] = 2
            cases.append((name, matrix))
        for name, matrix in cases:
            for location in ("first", "second"):
                kwargs = {location: matrix}
                with self.subTest(name=name, location=location), self.assertRaises(FrameInfoFormatError):
                    parse_frame_info_blob(make_blob((1, 2, 3), **kwargs))

    def test_invalid_parser_options_rejected(self):
        for kwargs in ({"max_entries": -1}, {"max_entries": True}, {"translation_unit": " "},
                       {"rigid_tolerance": 0}, {"rigid_tolerance": np.inf}, {"rigid_tolerance": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                parse_frame_info_blob(make_blob(), **kwargs)


if __name__ == "__main__":
    unittest.main()

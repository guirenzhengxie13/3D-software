"""Small synthetic fixtures for actual offline format and source safety."""

from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

import numpy as np

from reconstruction_probe.offline import decode_sparse_depth, file_sha256, open_scan_database, read_global_registration_poses
from reconstruction_probe.poses import FrameInfoFormatError, parse_compact_frame_pose


class OfflineFormatTests(unittest.TestCase):
    def test_sparse_depth_and_embedded_rgba_preserve_order(self):
        z = np.array([120.25, 230.5], dtype="<f4")
        rgba = bytes([1, 2, 3, 255, 4, 5, 6, 255])
        blob = struct.pack("<4I", 3, 2, 2, 1) + bytes([0b00100001]) + z.tobytes() + rgba
        frame = decode_sparse_depth(blob, 3, 2)
        np.testing.assert_array_equal(frame.depth_mm, [[120.25, 0, 0], [0, 0, 230.5]])
        self.assertEqual(frame.rgba.tobytes(), rgba)
        for bad in (blob[:-1], blob + b"x", blob[:16] + bytes([0b10100001]) + blob[17:]):
            with self.assertRaises(ValueError):
                decode_sparse_depth(bad, 3, 2)

    def test_compact_pose_and_unrecognized_headers(self):
        matrix = np.eye(4)
        matrix[:3, 3] = [1.5, -2, 3]
        head = bytes.fromhex("0000000001040002000000000c000000")
        blob = head + matrix.astype("<f8").tobytes() + bytes(20)
        pose = parse_compact_frame_pose(blob)
        np.testing.assert_array_equal(pose.matrix_at_16, matrix)
        self.assertEqual(pose.opaque_tail, bytes(20))
        changed_segment = struct.pack("<I", 7) + blob[4:]
        np.testing.assert_array_equal(parse_compact_frame_pose(changed_segment).matrix_at_16, matrix)
        changed_flags = bytes.fromhex("0505000000040002") + blob[8:]
        np.testing.assert_array_equal(parse_compact_frame_pose(changed_flags).matrix_at_16, matrix)
        for bad in (blob[:-1], bytes(164), blob + b"x"):
            with self.assertRaises(FrameInfoFormatError):
                parse_compact_frame_pose(bad)

    def test_global_pose_id_words_and_duplicate_rejection(self):
        matrix = np.eye(4).astype("<f8").tobytes()
        entry = struct.pack("<2I", 2, 7) + matrix
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "global.pose"
            path.write_bytes(struct.pack("<I", 1) + entry)
            poses = read_global_registration_poses(path)
            self.assertEqual(list(poses), [(2 << 32) | 7])
            path.write_bytes(struct.pack("<I", 2) + entry * 2)
            with self.assertRaisesRegex(FrameInfoFormatError, "Duplicate"):
                read_global_registration_poses(path)

    def test_database_header_restored_only_in_temporary_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frames.dataset"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE sample (id INTEGER)")
            connection.execute("INSERT INTO sample VALUES (7)")
            connection.commit()
            connection.close()
            with path.open("r+b") as stream:
                stream.write(b"RPAlgo_file_sys\0")
            before = file_sha256(path)
            with open_scan_database(path) as recovered:
                self.assertEqual(recovered.execute("SELECT id FROM sample").fetchone()[0], 7)
                with self.assertRaises(sqlite3.OperationalError):
                    recovered.execute("INSERT INTO sample VALUES (8)")
            self.assertEqual(file_sha256(path), before)
            self.assertEqual(path.read_bytes()[:16], b"RPAlgo_file_sys\0")


if __name__ == "__main__":
    unittest.main()

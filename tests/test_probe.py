import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from reconstruction_probe import (
    PlyReplaySource,
    PointCloudFrame,
    RevopointSdkUnavailableError,
    RevopointSource,
    SimulatedSource,
)
from reconstruction_probe.cli import main
from reconstruction_probe.ply import write_ascii_ply


class FrameContractTests(unittest.TestCase):
    def test_copies_native_buffers_and_makes_them_read_only(self):
        xyz = np.array([[1.0, 2.0, 3.0]])
        colors = np.array([[0.1, 0.2, 0.3]])
        frame = PointCloudFrame(xyz, colors)
        xyz[:] = 99.0
        colors[:] = 1.0
        np.testing.assert_allclose(frame.xyz, [[1.0, 2.0, 3.0]])
        np.testing.assert_allclose(frame.colors, [[0.1, 0.2, 0.3]])
        with self.assertRaises(ValueError):
            frame.xyz[0, 0] = 4.0

    def test_rejects_invalid_shapes_colors_and_nonfinite_points(self):
        cases = [
            {"xyz": np.zeros((3, 2))},
            {"xyz": np.zeros((3, 3)), "colors": np.zeros((2, 3))},
            {"xyz": np.zeros((1, 3)), "colors": [[0, 0, 255]]},
            {"xyz": [[float("nan"), 0, 0]]},
            {"xyz": [[0, 0, 0]], "unit": "mm"},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                PointCloudFrame(**kwargs)


class SourceTests(unittest.TestCase):
    def test_simulation_is_repeatable_and_frames_have_independent_storage(self):
        first = list(SimulatedSource(point_count=100, frame_count=3, seed=8))
        repeat = list(SimulatedSource(point_count=100, frame_count=3, seed=8))
        self.assertEqual([frame.frame_id for frame in first], [0, 1, 2])
        np.testing.assert_array_equal(first[0].xyz, repeat[0].xyz)
        self.assertFalse(np.array_equal(first[0].xyz, first[1].xyz))
        self.assertFalse(np.shares_memory(first[0].xyz, first[1].xyz))
        self.assertEqual(first[0].unit, "m")
        self.assertTrue(np.all(first[0].xyz[:, 2] > 0.0))

    def test_hardware_adapter_fails_explicitly(self):
        with self.assertRaisesRegex(RevopointSdkUnavailableError, "RANGE 2.*not integrated"):
            RevopointSource()

    def test_ply_normalizes_explicit_mm_units_and_preserves_axes(self):
        cloud = SimpleNamespace(
            points=np.array([[10.0, -20.0, 30.0]]),
            colors=np.array([[1.0, 0.5, 0.0]]),
            is_empty=lambda: False,
            has_colors=lambda: True,
        )
        fake_open3d = SimpleNamespace(io=SimpleNamespace(read_point_cloud=lambda _: cloud))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "scan.ply"
            path.touch()
            with patch("reconstruction_probe.sources.require_open3d", return_value=fake_open3d):
                frame = next(iter(PlyReplaySource([path], source_unit="mm")))
        np.testing.assert_allclose(frame.xyz, [[0.01, -0.02, 0.03]])
        np.testing.assert_allclose(frame.colors, [[1.0, 0.5, 0.0]])
        self.assertEqual(frame.coordinate_frame, "ply_source_axes")
        self.assertEqual(frame.timestamp_domain, "host_monotonic")

    def test_exported_ply_records_metres_and_encodes_rgb(self):
        frame = PointCloudFrame([[0.1, -0.2, 0.3]], [[1.0, 0.5, 0.0]])
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "last.ply"
            write_ascii_ply(path, frame)
            contents = path.read_text(encoding="ascii")
        self.assertIn("comment xyz_unit metres\n", contents)
        self.assertIn("element vertex 1\n", contents)
        self.assertEqual(contents.splitlines()[-1], "0.1 -0.2 0.3 255 128 0")

    @unittest.skipUnless(os.name == "nt", "Windows Open3D filename workaround")
    def test_unicode_input_temporary_copy_is_removed_after_native_read_fails(self):
        native_paths = []

        def fail_read(path):
            native_path = Path(path)
            native_paths.append(native_path)
            self.assertTrue(str(native_path).isascii())
            self.assertEqual(native_path.read_bytes(), b"test ply bytes")
            raise RuntimeError("native reader failure")

        fake_open3d = SimpleNamespace(io=SimpleNamespace(read_point_cloud=fail_read))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "\u4e2d\u6587\u626b\u63cf.ply"
            path.write_bytes(b"test ply bytes")
            with patch("reconstruction_probe.sources.require_open3d", return_value=fake_open3d):
                with self.assertRaisesRegex(RuntimeError, "native reader failure"):
                    next(iter(PlyReplaySource([path.resolve()], source_unit="m")))
            self.assertTrue(path.exists())
        self.assertEqual(len(native_paths), 1)
        self.assertFalse(native_paths[0].exists())
        self.assertFalse(native_paths[0].parent.exists())

    @unittest.skipUnless(importlib.util.find_spec("open3d") is not None, "Open3D extra is optional")
    def test_real_open3d_replays_unicode_absolute_ply_path(self):
        original = PointCloudFrame([[0.1, -0.2, 0.3], [-1.0, 2.0, 3.0]], [[1.0, 0.5, 0.0], [0, 0, 1]])
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "\u4e2d\u6587\u626b\u63cf\u76ee\u5f55"
            folder.mkdir()
            path = (folder / "\u70b9\u4e91.ply").resolve()
            write_ascii_ply(path, original)
            actual = next(iter(PlyReplaySource([path], source_unit="m")))
        np.testing.assert_allclose(actual.xyz, original.xyz)
        np.testing.assert_allclose(actual.colors, original.colors, atol=1 / 255)

    def test_headless_cli_reports_synthetic_provenance(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--headless", "--frames", "3", "--points", "50"])
        self.assertEqual(result, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["source"], "simulate")
        self.assertFalse(report["hardware_verified"])
        self.assertEqual(report["frames_received"], 3)
        self.assertEqual(report["point_count"], 50)
        self.assertIn("SYNTHETIC DATA", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

"""Verify real NumPy/Open3D I/O and optionally a hidden OpenGL rendering window."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import open3d as o3d

from reconstruction_probe.ply import write_ascii_ply
from reconstruction_probe.sources import PlyReplaySource, SimulatedSource


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true", help="Also create a hidden OpenGL window and save a preview")
    args = parser.parse_args()
    project = Path(__file__).resolve().parent.parent
    reports = project / "reports"
    reports.mkdir(exist_ok=True)
    report = {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "python_executable": sys.executable,
        "base_python": sys.base_prefix,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "open3d": o3d.__version__,
        "hardware_verified": False,
        "data_source": "synthetic",
    }
    try:
        frame = next(iter(SimulatedSource(point_count=6000, frame_count=1)))
        ply_path = reports / "synthetic-verification.ply"
        write_ascii_ply(ply_path, frame)
        replay = next(iter(PlyReplaySource([ply_path], source_unit="m")))
        if not np.allclose(replay.xyz, frame.xyz, atol=1e-10, rtol=0):
            raise RuntimeError("PLY position round trip failed")
        if replay.colors is None or not np.allclose(replay.colors, frame.colors, atol=1 / 255):
            raise RuntimeError("PLY color round trip failed")
        report["ply_round_trip"] = "passed"
        report["points"] = len(replay.xyz)
        if args.render:
            cloud = o3d.geometry.PointCloud()
            cloud.points = o3d.utility.Vector3dVector(replay.xyz)
            cloud.colors = o3d.utility.Vector3dVector(replay.colors)
            window = o3d.visualization.Visualizer()
            created = window.create_window(window_name="Synthetic verification", width=960, height=640, visible=False)
            if not created:
                raise RuntimeError("Open3D could not create a hidden OpenGL window")
            try:
                window.add_geometry(cloud)
                options = window.get_render_option()
                options.background_color = np.array([0.06, 0.08, 0.11])
                options.point_size = 3.0
                window.poll_events()
                window.update_renderer()
                pixels = np.asarray(window.capture_screen_float_buffer(do_render=True))
                if not np.isfinite(pixels).all() or float(pixels.std()) < 0.01:
                    raise RuntimeError("OpenGL produced an empty or invalid image")
                preview = reports / "synthetic-preview.png"
                # Open3D's Windows file APIs may reject Unicode absolute paths.
                # Keep native I/O on an ASCII temp path and save through Python.
                with tempfile.TemporaryDirectory(prefix="reconstruction-render-") as temporary:
                    native_path = Path(temporary) / "preview.png"
                    if not str(native_path).isascii():
                        raise RuntimeError("Open3D image output requires an ASCII TEMP path on this Windows build")
                    written = o3d.io.write_image(str(native_path), o3d.geometry.Image((np.clip(pixels, 0, 1) * 255).astype(np.uint8)))
                    if written:
                        preview.write_bytes(native_path.read_bytes())
                if not written:
                    raise RuntimeError("Could not save preview")
                report["opengl_render"] = "passed_hidden_window"
                report["preview"] = str(preview)
            finally:
                window.destroy_window()
        else:
            report["opengl_render"] = "not_requested"
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        serialized = json.dumps(report, ensure_ascii=False, indent=2)
        (reports / "environment-check.json").write_text(serialized, encoding="utf-8")
        print(serialized)


if __name__ == "__main__":
    main()

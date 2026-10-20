"""Open3D preview for the normalized frame stream."""

from collections.abc import Iterable
import time

from ._open3d import require_open3d
from .frames import PointCloudFrame


def show_frames(frames: Iterable[PointCloudFrame], title: str) -> PointCloudFrame | None:
    """Preview frames and keep the last frame visible until the window closes."""
    o3d = require_open3d()
    visualizer = o3d.visualization.Visualizer()
    if not visualizer.create_window(window_name=title, width=1280, height=800):
        raise RuntimeError("Open3D could not create a window; use --headless to test data input")
    cloud = o3d.geometry.PointCloud()
    last = None
    window_open = True
    try:
        for frame in frames:
            cloud.points = o3d.utility.Vector3dVector(frame.xyz)
            if frame.colors is not None:
                cloud.colors = o3d.utility.Vector3dVector(frame.colors)
            else:
                cloud.colors = o3d.utility.Vector3dVector()
            if last is None:
                visualizer.add_geometry(cloud)
            else:
                visualizer.update_geometry(cloud)
            last = frame
            window_open = visualizer.poll_events()
            if not window_open:
                break
            visualizer.update_renderer()
        while last is not None and window_open:
            window_open = visualizer.poll_events()
            if window_open:
                visualizer.update_renderer()
                # Avoid busy-spinning after the finite replay has finished.
                time.sleep(0.01)
    finally:
        visualizer.destroy_window()
    return last

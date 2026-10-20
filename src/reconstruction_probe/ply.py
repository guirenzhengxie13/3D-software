"""A minimal ASCII PLY exporter for inspecting or replaying a captured snapshot."""

from pathlib import Path

import numpy as np

from .frames import PointCloudFrame


def write_ascii_ply(path: Path, frame: PointCloudFrame) -> None:
    """Write metres; the header records the convention as a comment."""
    path = Path(path)
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(
            "ply\nformat ascii 1.0\ncomment xyz_unit metres\n"
            f"element vertex {len(frame.xyz)}\n"
            "property double x\nproperty double y\nproperty double z\n"
        )
        if frame.colors is not None:
            stream.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        stream.write("end_header\n")
        if frame.colors is None:
            np.savetxt(stream, frame.xyz, fmt="%.12g")
        else:
            rgb = np.rint(frame.colors * 255.0).astype(np.uint8)
            np.savetxt(
                stream,
                np.column_stack((frame.xyz, rgb)),
                fmt=["%.12g", "%.12g", "%.12g", "%d", "%d", "%d"],
            )

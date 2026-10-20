"""Synthetic input, file replay, and an explicit unimplemented SDK boundary."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
import math
import os
import shutil
import tempfile
import time
from typing import Protocol

import numpy as np

from ._open3d import require_open3d
from .frames import PointCloudFrame


class PointCloudSource(Protocol):
    def __iter__(self) -> Iterator[PointCloudFrame]:
        """Yield owned frames, normalizing positions to metres."""
        ...


def _wait_until(start: float, index: int, fps: float, realtime: bool) -> None:
    if realtime:
        remaining = start + index / fps - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)


def _read_ply_cloud(o3d, path: Path):
    """Work around Open3D's Windows filename conversion for Unicode paths.

    Python handles the original filename; the native reader only sees an
    ASCII temporary filename. The PLY reader consumes the file eagerly, so
    the copy can be deleted before its cloud is returned. Open3D 0.20's
    read_point_cloud_from_bytes does not support PLY.
    """
    if os.name != "nt" or str(path).isascii():
        return o3d.io.read_point_cloud(str(path))
    with tempfile.TemporaryDirectory(prefix="reconstruction-probe-") as temp_dir:
        temp_path = Path(temp_dir) / "input.ply"
        if not str(temp_path).isascii():
            raise RuntimeError(
                "Open3D on Windows requires an ASCII temporary path for this PLY. "
                "Set TEMP and TMP to a writable ASCII directory before starting the probe."
            )
        shutil.copyfile(path, temp_path)
        return o3d.io.read_point_cloud(str(temp_path))


@dataclass
class SimulatedSource:
    """A deterministic, moving ellipsoid. These are not scanner measurements."""

    point_count: int = 6000
    frame_count: int = 90
    fps: float = 15.0
    seed: int = 7
    realtime: bool = False

    def __post_init__(self) -> None:
        if self.point_count <= 0 or self.frame_count <= 0:
            raise ValueError("point_count and frame_count must be positive")
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("fps must be finite and positive")

    def __iter__(self) -> Iterator[PointCloudFrame]:
        rng = np.random.default_rng(self.seed)
        directions = rng.normal(size=(self.point_count, 3))
        norms = np.linalg.norm(directions, axis=1, keepdims=True)
        directions /= np.maximum(norms, np.finfo(float).tiny)
        surface = directions * np.array([0.25, 0.18, 0.32])
        colors = (directions + 1.0) * 0.5
        start = time.monotonic()
        for frame_id in range(self.frame_count):
            _wait_until(start, frame_id, self.fps, self.realtime)
            angle = frame_id * 0.025
            cosine, sine = math.cos(angle), math.sin(angle)
            rotation = np.array([[cosine, 0.0, sine], [0.0, 1.0, 0.0], [-sine, 0.0, cosine]])
            xyz = surface @ rotation.T + np.array([0.0, 0.0, 0.7])
            yield PointCloudFrame(
                xyz=xyz,
                colors=colors,
                frame_id=frame_id,
                timestamp=time.monotonic(),
                coordinate_frame="synthetic_right_handed",
            )


@dataclass
class PlyReplaySource:
    """Read each supplied PLY once; file order is replay order.

    PLY does not establish a physical unit or capture timestamps. The caller
    must supply source_unit. Timestamps here are host replay times. Input
    axes and handedness are preserved and identified as ply_source_axes.
    """

    paths: Sequence[Path]
    source_unit: str
    fps: float = 15.0
    realtime: bool = False

    def __post_init__(self) -> None:
        self.paths = tuple(Path(path) for path in self.paths)
        if not self.paths:
            raise ValueError("Supply at least one PLY file")
        if self.source_unit not in ("m", "mm"):
            raise ValueError("PLY source_unit must explicitly be 'm' or 'mm'")
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("fps must be finite and positive")
        for path in self.paths:
            if path.suffix.lower() != ".ply" or not path.is_file():
                raise ValueError(f"PLY file does not exist or has the wrong suffix: {path}")

    def __iter__(self) -> Iterator[PointCloudFrame]:
        o3d = require_open3d()
        scale = 0.001 if self.source_unit == "mm" else 1.0
        start = time.monotonic()
        for frame_id, path in enumerate(self.paths):
            cloud = _read_ply_cloud(o3d, path)
            if cloud.is_empty():
                raise ValueError(f"PLY contains no readable points: {path}")
            _wait_until(start, frame_id, self.fps, self.realtime)
            yield PointCloudFrame(
                xyz=np.asarray(cloud.points) * scale,
                colors=np.asarray(cloud.colors) if cloud.has_colors() else None,
                frame_id=frame_id,
                timestamp=time.monotonic(),
                coordinate_frame="ply_source_axes",
            )


class RevopointSdkUnavailableError(RuntimeError):
    """Raised until an authorized, model-compatible SDK adapter exists."""


class RevopointSource:
    """An integration boundary, not an implementation of a vendor API."""

    def __init__(self) -> None:
        raise RevopointSdkUnavailableError(
            "Revopoint RANGE 2 live acquisition is not integrated or hardware-tested. "
            "Obtain the official SDK, RANGE 2 support confirmation, license, "
            "connection instructions, and frame/coordinate documentation from Revopoint "
            "before implementing this adapter. No vendor API names are assumed here."
        )

    def __iter__(self) -> Iterator[PointCloudFrame]:
        raise RevopointSdkUnavailableError("No Revopoint SDK adapter is installed")

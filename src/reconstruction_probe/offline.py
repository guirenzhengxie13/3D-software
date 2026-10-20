"""Read-only recovery of the observed offline scan database formats.

Depth/color decoding follows the sparse RANGE v0 structure in the user's
authorized reference recovery implementation. Original headers never change.
Unknown formats fail explicitly rather than producing guessed geometry.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile

import numpy as np

from .poses import FrameInfoFormatError, _rigid_matrix


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def open_scan_database(path: Path):
    """Open only a temporary header-restored copy, closing it before cleanup."""
    with tempfile.TemporaryDirectory(prefix="offline-scan-") as directory:
        copy = Path(directory) / "frames.sqlite"
        shutil.copyfile(path, copy)
        with copy.open("r+b") as stream:
            magic = stream.read(16)
            if magic == b"RPAlgo_file_sys\0":
                stream.seek(0)
                stream.write(b"SQLite format 3\0")
            elif magic != b"SQLite format 3\0":
                raise ValueError("Unrecognized scan database signature")
        connection = sqlite3.connect(copy.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            yield connection
        finally:
            connection.close()


@dataclass(frozen=True)
class SparseDepthFrame:
    depth_mm: np.ndarray
    rgba: np.ndarray | None


def decode_sparse_depth(blob: bytes, width: int, height: int) -> SparseDepthFrame:
    """Decode header, LSB bitmap, float32 millimetres, optional aligned RGBA."""
    if len(blob) < 16:
        raise ValueError("Truncated sparse depth header")
    w, h, count, kind = struct.unpack_from("<4I", blob)
    if (w, h) != (width, height) or not (0 < w <= 16384 and 0 < h <= 16384):
        raise ValueError("Invalid sparse dimensions")
    if w * h > 32_000_000 or count > w * h or kind not in (0, 1):
        raise ValueError("Unsupported sparse depth layout")
    mask_bytes = (w * h + 7) // 8
    offset = 16 + mask_bytes
    if len(blob) != offset + count * (8 if kind == 1 else 4):
        raise ValueError("Sparse payload length mismatch")
    bits = np.unpackbits(np.frombuffer(blob, np.uint8, mask_bytes, 16), bitorder="little")
    if bits[w * h:].any() or int(bits[:w * h].sum()) != count:
        raise ValueError("Sparse bitmap count/padding mismatch")
    z = np.frombuffer(blob, "<f4", count, offset)
    if not np.isfinite(z).all() or np.any(z <= 0) or np.any(z >= 100_000):
        raise ValueError("Invalid depth samples")
    depth = np.zeros(w * h, np.float32)
    depth[np.flatnonzero(bits[:w * h])] = z
    rgba = np.frombuffer(blob, np.uint8, count * 4, offset + count * 4).reshape(count, 4).copy() if kind else None
    return SparseDepthFrame(depth.reshape(h, w), rgba)


def read_global_registration_poses(path: Path) -> dict[int, np.ndarray]:
    """Read the observed count + [id high/low words, f64 4x4] file.

    The filename suggests a global registration result; this parser does not
    establish when those matrices were optimized or whether each is valid.
    """
    data = path.read_bytes()
    if len(data) < 4:
        raise FrameInfoFormatError("Truncated global registration pose header")
    count = struct.unpack_from("<I", data)[0]
    if count > 1_000_000 or len(data) != 4 + 136 * count:
        raise FrameInfoFormatError("Unrecognized global registration pose layout")
    poses = {}
    for index in range(count):
        offset = 4 + 136 * index
        high, low = struct.unpack_from("<2I", data, offset)
        frame_id = (high << 32) | low
        if frame_id in poses:
            raise FrameInfoFormatError("Duplicate global registration frame ID")
        poses[frame_id] = _rigid_matrix(data, offset + 8, 1e-4)
    return poses

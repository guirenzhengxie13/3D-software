"""Strict readers for observed manifest-version 6.1 attribute-table records.

Only layouts validated on the user's 2026-10-18 projects are recognized.
Uninterpreted fields remain opaque; no tracking/timestamp meaning is inferred.
"""

from dataclasses import dataclass
import struct

import numpy as np

from .offline import SparseDepthFrame
from .poses import _rigid_matrix


def decode_attribute_depth(blob, width=None, height=None):
    if len(blob) < 20:
        raise ValueError("Truncated attribute depth header")
    w, h, count, code, opaque = struct.unpack_from("<5I", blob)
    if (not 0 < w <= 16384 or not 0 < h <= 16384 or w * h > 32_000_000
            or count > w * h or code not in (0x10000, 0x10001) or opaque != 0):
        raise ValueError("Unsupported attribute depth layout")
    if (width is not None and width != w) or (height is not None and height != h):
        raise ValueError("Attribute depth dimensions disagree with manifest")
    colored = code == 0x10001
    mask_bytes = (w * h + 7) // 8
    offset = 20 + mask_bytes
    if len(blob) != offset + count * (8 if colored else 4):
        raise ValueError("Attribute sparse payload length mismatch")
    bits = np.unpackbits(np.frombuffer(blob, np.uint8, mask_bytes, 20), bitorder="little")
    if bits[w * h:].any() or int(bits[:w * h].sum()) != count:
        raise ValueError("Attribute bitmap count/padding mismatch")
    values = np.frombuffer(blob, "<f4", count, offset)
    if not np.isfinite(values).all() or np.any(values <= 0) or np.any(values >= 100_000):
        raise ValueError("Invalid attribute depth values")
    depth = np.zeros(w * h, np.float32)
    depth[np.flatnonzero(bits[:w * h])] = values
    rgba = None
    if colored:
        abgr = np.frombuffer(blob, np.uint8, count * 4, offset + count * 4).reshape(count, 4)
        # Observed byte order A,B,G,R. The standard JPEG decode also carries
        # swapped R/B: matching JPEG alone cannot establish physical RGB.
        # This mapping matches native PLY and the user-confirmed blue bow.
        rgba = abgr[:, [3, 2, 1, 0]].copy()
    return SparseDepthFrame(depth.reshape(h, w), rgba)


def parse_attribute_pose(blob):
    if len(blob) != 132 or struct.unpack_from("<I", blob)[0] != 1:
        raise ValueError("Unsupported attribute pose layout")
    return _rigid_matrix(bytes(blob), 4, 1e-4).copy()


def split_jpeg_attribute(blob):
    if len(blob) < 12:
        raise ValueError("Truncated RGB attribute")
    version, opaque, length = struct.unpack_from("<3I", blob)
    if version != 1 or opaque != 0 or length != len(blob) - 12:
        raise ValueError("Unsupported RGB attribute header/length")
    payload = bytes(blob[12:])
    if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
        raise ValueError("RGB attribute is not the observed JPEG payload")
    return payload


@dataclass(frozen=True)
class MarkerRecords:
    xyz: np.ndarray
    direction_candidate: np.ndarray
    raw_records: np.ndarray
    version: int


def parse_attribute_markers(blob, *, global_frame=False):
    if len(blob) < 8:
        raise ValueError("Truncated marker header")
    version, count = struct.unpack_from("<2I", blob)
    stride, required, dtype = (104, 3, "<f8") if global_frame else (36, 2, "<f4")
    if version != required or count > 1_000_000 or len(blob) != 8 + count * stride:
        raise ValueError("Unsupported marker record layout")
    raw = np.frombuffer(blob, np.uint8, offset=8).reshape(count, stride).copy()
    words = np.frombuffer(raw[:, :6 * np.dtype(dtype).itemsize].copy().tobytes(), dtype).reshape(count, 6)
    if not np.isfinite(words).all():
        raise ValueError("Nonfinite marker coordinates/directions")
    return MarkerRecords(words[:, :3].copy(), words[:, 3:].copy(), raw, version)

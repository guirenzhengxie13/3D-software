"""Read stored FrameInfo matrices without assigning them a world convention.

This recognizes the observed RANGE FrameInfo binary shape: a 16-byte header,
two float64 4x4 matrices, three counted record arrays and an 8-byte opaque
field. The second matrix moves with the first two arrays. Counts are parsed
independently; neither their equality nor the meaning of the records is
assumed. An empty-array instance is 292 bytes.

Successful structural parsing does not establish transform direction, axis
signs, tracking/optimization stage, or translation units. Establish those
from the source format and geometric validation before applying a matrix.
"""

from dataclasses import dataclass
import math
import struct

import numpy as np
from numpy.typing import NDArray


class FrameInfoFormatError(ValueError):
    """The blob does not match the supported stored FrameInfo layout."""


@dataclass(frozen=True, slots=True)
class StoredCompactPose:
    """The observed 164-byte Revo Scan 6 record; header/tail stay opaque."""

    matrix_at_16: NDArray[np.float64]
    opaque_header: bytes
    opaque_tail: bytes


def parse_compact_frame_pose(blob: bytes) -> StoredCompactPose:
    """Parse the specific compact layout observed in the four local projects.

    Bytes 5 through 11 identify this observed format; byte 4 is 0 or 1 in
    the supplied files. Header words and the tail retain their opaque flags.
    No second pose, timestamp or tracking validity flag is invented.
    """
    data = bytes(blob)
    if len(data) != 164 or data[4] not in (0, 1) or data[5:12] != bytes.fromhex("04000200000000"):
        raise FrameInfoFormatError("Unrecognized compact FrameInfo layout")
    return StoredCompactPose(_rigid_matrix(data, 16, 1e-4), data[:16], data[144:])


@dataclass(frozen=True, slots=True)
class StoredFrameInfo:
    """Stored values, preserving uninterpreted fields and original units.

    Matrix arrays have immutable byte backing. ``translation_unit`` is only
    caller-provided provenance; the parser never rescales their translation.
    The second matrix is not claimed to be an optimized or inverse pose.
    """

    matrix_at_16: NDArray[np.float64]
    second_matrix: NDArray[np.float64]
    second_matrix_offset: int
    counts: tuple[int, int, int]
    opaque_header: bytes
    opaque_between_matrices: bytes
    records_24: bytes
    records_16: bytes
    records_8: bytes
    translation_unit: str | None = None


def _rigid_matrix(data: bytes, offset: int, tolerance: float) -> NDArray[np.float64]:
    matrix = np.frombuffer(data[offset:offset + 128], dtype="<f8").reshape(4, 4)
    if not np.isfinite(matrix).all():
        raise FrameInfoFormatError(f"Nonfinite matrix at offset {offset}")
    if not np.allclose(matrix[3], [0, 0, 0, 1], rtol=0, atol=tolerance):
        raise FrameInfoFormatError(f"Invalid homogeneous row at offset {offset}")
    rotation = matrix[:3, :3]
    orthogonality = float(np.max(np.abs(rotation.T @ rotation - np.eye(3))))
    determinant = float(np.linalg.det(rotation))
    if orthogonality > tolerance or abs(determinant - 1) > tolerance:
        raise FrameInfoFormatError(f"Nonrigid matrix at offset {offset}")
    return matrix


def parse_frame_info_blob(
    blob: bytes | bytearray | memoryview,
    *,
    translation_unit: str | None = None,
    max_entries: int = 100_000,
    rigid_tolerance: float = 1e-4,
) -> StoredFrameInfo:
    """Parse the supported layout or raise :class:`FrameInfoFormatError`.

    Array lengths are checked against both ``max_entries`` and remaining
    bytes before records are sliced. All bytes must be consumed; no scan for
    plausible matrices or fallback to guessed layouts is performed.
    ``translation_unit`` may be supplied when independently known (e.g.
    ``"mm"`` for the validated RANGE sample); it never changes stored values.
    """
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise TypeError("blob must be bytes, bytearray, or memoryview")
    if not isinstance(max_entries, int) or isinstance(max_entries, bool) or max_entries < 0:
        raise ValueError("max_entries must be a non-negative integer")
    if not math.isfinite(rigid_tolerance) or not 0 < rigid_tolerance <= 1e-2:
        raise ValueError("rigid_tolerance must be finite and in (0, 0.01]")
    if translation_unit is not None and (
        not isinstance(translation_unit, str) or not translation_unit.strip()
    ):
        raise ValueError("translation_unit must be a nonempty string or None")
    byte_count = memoryview(blob).nbytes
    if byte_count < 292:
        raise FrameInfoFormatError("Truncated FrameInfo: supported layout needs at least 292 bytes")
    if byte_count > 292 + max_entries * 48:
        raise FrameInfoFormatError("FrameInfo exceeds configured record limit")
    data = bytes(blob)
    offset = 144

    def take_counted_records(stride: int) -> tuple[int, bytes]:
        nonlocal offset
        if offset + 4 > len(data):
            raise FrameInfoFormatError(f"Truncated record count at offset {offset}")
        count = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if count > max_entries:
            raise FrameInfoFormatError(f"Record count {count} exceeds configured limit")
        if count > (len(data) - offset) // stride:
            raise FrameInfoFormatError(f"Truncated {stride}-byte record array")
        end = offset + count * stride
        records = data[offset:end]
        offset = end
        return count, records

    count_24, records_24 = take_counted_records(24)
    count_16, records_16 = take_counted_records(16)
    if offset + 8 + 128 > len(data):
        raise FrameInfoFormatError("Truncated opaque field or second matrix")
    opaque_between = data[offset:offset + 8]
    offset += 8
    second_matrix_offset = offset
    offset += 128
    count_8, records_8 = take_counted_records(8)
    if offset != len(data):
        raise FrameInfoFormatError(f"Unrecognized trailing bytes: {len(data) - offset}")
    first = _rigid_matrix(data, 16, rigid_tolerance)
    second = _rigid_matrix(data, second_matrix_offset, rigid_tolerance)
    return StoredFrameInfo(
        matrix_at_16=first,
        second_matrix=second,
        second_matrix_offset=second_matrix_offset,
        counts=(count_24, count_16, count_8),
        opaque_header=data[:16],
        opaque_between_matrices=opaque_between,
        records_24=records_24,
        records_16=records_16,
        records_8=records_8,
        translation_unit=translation_unit,
    )

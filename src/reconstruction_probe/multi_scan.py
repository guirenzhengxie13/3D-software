"""Offline frame identity and metric pose composition across scan projects.

No capture timestamp is inferred. A vendor frame ID is only unique within its
own project; an explicit source-to-object registration establishes the shared
coordinate system, independently of the frame ID or calibration equality.
"""

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

from .poses import _rigid_matrix
from .offline import file_sha256


@dataclass(frozen=True, slots=True)
class FrameKey:
    scan_id: str
    frame_id: int

    def __post_init__(self):
        if not isinstance(self.scan_id, str) or not self.scan_id.strip():
            raise ValueError("A nonempty source project ID is required")
        if type(self.frame_id) is not int or self.frame_id < 0:
            raise ValueError("A nonnegative source-local integer frame ID is required")


def rigid(value):
    matrix = np.asarray(value, dtype='<f8')
    if matrix.shape != (4, 4):
        raise ValueError("Expected a proper 4 by 4 rigid transform")
    return _rigid_matrix(matrix.tobytes(), 0, 1e-5).copy()


def registered_camera_to_object_m(source_to_object_mm, camera_to_source_mm, optical_axes):
    """Compose in mm first, then convert translation to m for TSDF integration."""
    axes = np.asarray(optical_axes, dtype=float)
    if axes.shape != (3,) or not np.all(np.abs(axes) == 1) or np.prod(axes) != 1:
        raise ValueError("Expected a proper optical axis sign conversion")
    result = rigid(source_to_object_mm) @ rigid(camera_to_source_mm)
    result[:3, 3] /= 1000
    return result @ np.diag([*axes, 1.])


def scaled_intrinsics(calibration, width, height):
    """Scale calibration pixel coordinates to the actual saved depth raster."""
    if type(width) is not int or type(height) is not int or min(width, height) <= 0:
        raise ValueError("Positive integer raster dimensions required")
    original = np.asarray([calibration['width'], calibration['height']], float)
    K = np.asarray(calibration['K'], float)
    if original.shape != (2,) or not np.isfinite(original).all() or np.any(original <= 0):
        raise ValueError("Invalid calibration image dimensions")
    if K.shape != (3, 3) or not np.isfinite(K).all() or min(K[0, 0], K[1, 1]) <= 0 or not np.allclose(K[2], [0, 0, 1]):
        raise ValueError("Invalid pinhole calibration")
    return np.diag([width / original[0], height / original[1], 1.]) @ K


def bound_evidence_path(fusion, evidence_directory):
    """Reject an evidence folder belonging to a different fusion revision."""
    fusion = Path(fusion).resolve(); evidence = Path(evidence_directory).resolve()
    summary_path = fusion / 'summary.json'
    metadata = json.loads((evidence / 'summary.json').read_text(encoding='utf-8'))
    if metadata.get('input_sha256', {}).get(str(summary_path)) != file_sha256(summary_path):
        raise ValueError('Surface evidence belongs to a different fusion or input revision')
    return evidence / 'joint_raw_depth-evidence.npz'

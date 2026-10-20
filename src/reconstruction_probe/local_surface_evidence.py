"""Separate axial depth differences from local point-to-plane discrepancies.

Each neighborhood fits only measured points on neighboring camera rays. A
local fit is descriptive: it is neither an independent surface reference nor
proof that a candidate point is part of the intended physical object.
"""

from dataclasses import dataclass

import numpy as np

from .multi_scan import scaled_intrinsics
from .visibility import project_depth_observations


@dataclass(frozen=True)
class ProjectedLocalPlanes:
    point_indices: np.ndarray
    pixel_indices: np.ndarray
    axial_delta_mm: np.ndarray
    signed_point_to_plane_mm: np.ndarray
    plane_rms_mm: np.ndarray
    valid_neighbors: np.ndarray
    spans_two_dimensions: np.ndarray
    abs_view_normal_dot: np.ndarray


def project_local_planes(xyz_scan_mm, camera_to_scan, depth_mm, calibration, axis_signs):
    observed = project_depth_observations(xyz_scan_mm, camera_to_scan, depth_mm, calibration, axis_signs)
    depth = np.asarray(depth_mm); height, width = depth.shape; K = scaled_intrinsics(calibration, width, height)
    if K[0, 1] != 0 or K[1, 0] != 0:
        raise ValueError('Current projection requires zero-skew calibration')
    v, u = np.divmod(observed.pixel_indices, width); n = len(v)
    neighbors = np.zeros((n, 9, 3)); valid = np.zeros((n, 9), bool)
    for j, (dv, du) in enumerate(( (dv, du) for dv in [-1, 0, 1] for du in [-1, 0, 1] )):
        vv, uu = v+dv, u+du; inside = (vv >= 0) & (vv < height) & (uu >= 0) & (uu < width)
        ids = np.flatnonzero(inside); z = depth[vv[ids], uu[ids]]; good = np.isfinite(z) & (z > 0); ids = ids[good]; z = z[good]
        valid[ids, j] = True; neighbors[ids, j] = np.column_stack(((uu[ids]-K[0, 2])*z/K[0, 0], (vv[ids]-K[1, 2])*z/K[1, 1], z))
    count = valid.sum(1); centroid = neighbors.sum(1) / count[:, None]
    centered = (neighbors-centroid[:, None, :]) * valid[:, :, None]
    covariance = np.einsum('nki,nkj->nij', centered, centered) / count[:, None, None]
    values, vectors = np.linalg.eigh(covariance); normals = vectors[:, :, 0]
    flip = np.sum(normals * -centroid, axis=1) < 0; normals[flip] *= -1
    pose = np.asarray(camera_to_scan); camera = ((np.asarray(xyz_scan_mm)[observed.point_indices]-pose[:3, 3]) @ pose[:3, :3]) * np.asarray(axis_signs)
    plane_delta = np.sum((camera-centroid)*normals, axis=1)
    direction = -camera / np.linalg.norm(camera, axis=1)[:, None]
    middle_ratio = np.divide(values[:, 1], values[:, 2], out=np.zeros(n), where=values[:, 2] > 1e-12)
    return ProjectedLocalPlanes(observed.point_indices, observed.pixel_indices, observed.signed_delta_mm, plane_delta,
        np.sqrt(np.maximum(values[:, 0], 0)), count, (count >= 6) & (middle_ratio >= .001) & (values[:, 1] > 1e-10),
        np.abs(np.sum(direction*normals, axis=1)))

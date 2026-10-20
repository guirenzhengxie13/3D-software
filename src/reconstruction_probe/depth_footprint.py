"""Pixel-neighborhood sensitivity of projected depth evidence.

Neighboring rays do not measure the exact same physical surface point. These
statistics diagnose dependence on a single raster pixel; they are not a new
confidence score or an automatic replacement for the original observation.
"""

from dataclasses import dataclass

import numpy as np

from .visibility import project_depth_observations


@dataclass(frozen=True)
class ProjectedDepthFootprints:
    point_indices: np.ndarray
    pixel_indices: np.ndarray
    center_delta_mm: np.ndarray
    minimum_delta_mm: np.ndarray
    maximum_delta_mm: np.ndarray
    minimum_absolute_delta_mm: np.ndarray
    valid_neighbors: np.ndarray


def project_depth_footprints(xyz_scan_mm, camera_to_scan, depth_mm, calibration, axis_signs, radius=1):
    if type(radius) is not int or not 0 <= radius <= 3:
        raise ValueError('Pixel radius must be an integer in 0..3')
    observed = project_depth_observations(xyz_scan_mm, camera_to_scan, depth_mm, calibration, axis_signs)
    depth = np.asarray(depth_mm); height, width = depth.shape
    v, u = np.divmod(observed.pixel_indices, width)
    predicted_z = depth.ravel()[observed.pixel_indices] - observed.signed_delta_mm
    minimum = np.full(len(v), np.inf); maximum = np.full(len(v), -np.inf); closest = minimum.copy(); count = np.zeros(len(v), np.uint8)
    for dv in range(-radius, radius+1):
        for du in range(-radius, radius+1):
            vv, uu = v + dv, u + du; inside = (vv >= 0) & (vv < height) & (uu >= 0) & (uu < width)
            ids = np.flatnonzero(inside); values = depth[vv[ids], uu[ids]]
            valid = np.isfinite(values) & (values > 0); ids = ids[valid]; delta = values[valid] - predicted_z[ids]
            minimum[ids] = np.minimum(minimum[ids], delta); maximum[ids] = np.maximum(maximum[ids], delta)
            closest[ids] = np.minimum(closest[ids], np.abs(delta)); count[ids] += 1
    return ProjectedDepthFootprints(observed.point_indices, observed.pixel_indices, observed.signed_delta_mm, minimum, maximum, closest, count)

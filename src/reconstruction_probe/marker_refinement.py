"""Bounded marker-based relative pose refinements, with explicit associations."""

import numpy as np
from scipy.spatial import cKDTree


def rigid_alignment(source, target, weights=None):
    source, target = np.asarray(source, float), np.asarray(target, float)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3 or len(source) < 3:
        raise ValueError("At least three corresponding XYZ points are required")
    if not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("Nonfinite alignment coordinates")
    weights = np.ones(len(source)) if weights is None else np.asarray(weights, float)
    if weights.shape != (len(source),) or not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError("Positive finite weights required")
    weights = weights / weights.sum()
    a, b = (source * weights[:, None]).sum(0), (target * weights[:, None]).sum(0)
    U, singular, Vt = np.linalg.svd(((source - a) * weights[:, None]).T @ (target - b))
    if singular[1] <= max(singular[0], 1.) * 1e-10:
        raise ValueError("Collinear/degenerate marker correspondences")
    rotation = Vt.T @ U.T
    if np.linalg.det(rotation) < 0:
        Vt[-1] *= -1
        rotation = Vt.T @ U.T
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[:3, 3] = b - rotation @ a
    return transform


def refine_marker_points(points, reference, *, max_distance_mm=2., huber_mm=.2, iterations=12):
    points, reference = np.asarray(points, float), np.asarray(reference, float)
    if points.ndim != 2 or reference.ndim != 2 or points.shape[1] != 3 or reference.shape[1] != 3:
        raise ValueError("Expected XYZ arrays")
    if len(points) < 3 or len(reference) < 3 or not np.isfinite(points).all() or not np.isfinite(reference).all():
        raise ValueError("Insufficient or nonfinite marker points")
    if max_distance_mm <= 0 or huber_mm <= 0 or iterations < 1:
        raise ValueError("Positive refinement parameters required")
    tree = cKDTree(reference)
    transform = np.eye(4)
    for _ in range(iterations):
        world = points @ transform[:3, :3].T + transform[:3, 3]
        distance, indices = tree.query(world)
        good = distance <= max_distance_mm
        if good.sum() < 3 or len(np.unique(indices[good])) < 3:
            raise ValueError("Insufficient nearby distinct framework markers")
        weights = np.minimum(1., huber_mm / np.maximum(distance[good], 1e-12))
        delta = rigid_alignment(world[good], reference[indices[good]], weights)
        transform = delta @ transform
    return transform

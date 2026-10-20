"""Symmetric spatial-support comparisons, without treating either side as truth."""

from __future__ import annotations

import math

import numpy as np


def _points(values):
    points = np.asarray(values, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points):
        raise ValueError("Expected a nonempty (N, 3) point array")
    if not np.isfinite(points).all():
        raise ValueError("Point coordinates must be finite")
    return np.ascontiguousarray(points)


def voxel_representatives(points, voxel_mm=.5, origin=(0., 0., 0.)):
    """Centroids in a fixed shared lattice; preserve keys and source counts.

    ``origin`` must be identical for both sides. Negative coordinates use
    mathematical floor, not integer truncation toward zero. Each side keeps
    its own centroid, even when both occupy the same cell.
    """
    points = _points(points)
    if not math.isfinite(voxel_mm) or voxel_mm <= 0:
        raise ValueError("voxel_mm must be positive and finite")
    origin = np.asarray(origin, dtype=np.float64)
    if origin.shape != (3,) or not np.isfinite(origin).all():
        raise ValueError("origin must contain three finite coordinates")
    positions = np.floor((points - origin) / voxel_mm)
    if not np.isfinite(positions).all() or np.max(np.abs(positions)) >= 2**62:
        raise ValueError("Voxel keys exceed supported integer range")
    keys, inverse, counts = np.unique(positions.astype(np.int64), axis=0, return_inverse=True, return_counts=True)
    centroids = np.column_stack([np.bincount(inverse, weights=points[:, axis]) / counts for axis in range(3)])
    return centroids, keys, counts


def _nearest(reference, query):
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        from ._open3d import require_open3d
        o3d = require_open3d()
        search = o3d.core.nns.NearestNeighborSearch(o3d.core.Tensor(reference, dtype=o3d.core.Dtype.Float64))
        search.knn_index()
        indices, squared = search.knn_search(o3d.core.Tensor(query, dtype=o3d.core.Dtype.Float64), 1)
        return np.sqrt(squared.numpy().reshape(-1)), indices.numpy().reshape(-1)
    distances, indices = cKDTree(reference).query(query, workers=1)
    return distances, indices


def compare_point_sets(own, official, thresholds=(.5, 1., 2.)):
    """Use full analysis clouds for both directions, not display subsamples.

    A point is 'common' when the other side supports its location within a
    threshold. This is neither exact vertex intersection nor proof of a
    correct measured surface. The matching is potentially many-to-one.
    """
    own, official = _points(own), _points(official)
    thresholds = tuple(float(value) for value in thresholds)
    if not thresholds or any(not math.isfinite(value) or value <= 0 for value in thresholds):
        raise ValueError("Distance thresholds must be positive and finite")
    if len(set(thresholds)) != len(thresholds):
        raise ValueError("Distance thresholds must be distinct")
    own_distance, own_indices = _nearest(official, own)
    official_distance, official_indices = _nearest(own, official)

    def counts(distances, threshold):
        common = int(np.count_nonzero(distances <= threshold))
        size = len(distances)
        return {"total": size, "common": common, "unique": size - common,
                "commonFraction": common / size, "uniqueFraction": (size - common) / size}

    stats = {}
    for threshold in thresholds:
        stats[f"{threshold:g}"] = {
            "own": counts(own_distance, threshold), "official": counts(official_distance, threshold),
            "medianOwn": float(np.median(own_distance)), "medianOfficial": float(np.median(official_distance)),
            "p90Own": float(np.percentile(own_distance, 90)), "p90Official": float(np.percentile(official_distance, 90))}
    return {"own_distances": own_distance, "official_distances": official_distance,
            "own_nearest_indices": own_indices, "official_nearest_indices": official_indices,
            "stats": stats}

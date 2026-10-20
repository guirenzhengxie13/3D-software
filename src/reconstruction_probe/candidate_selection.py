"""Preserve different rigid alignment hypotheses in the object's own region."""

import numpy as np

from .poses import _rigid_matrix


def hypothesis_rms_displacement(first, second, probe_points):
    """RMS distance between two transformed copies, in the point input unit.

    Compare actual object points: translation columns alone depend on where
    the source coordinate origin happens to be.
    """
    points = np.asarray(probe_points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.isfinite(points).all():
        raise ValueError("Expected nonempty finite N by 3 probe points")
    matrices = []
    for value in (first, second):
        matrix = np.asarray(value, dtype="<f8")
        if matrix.shape != (4,4):
            raise ValueError("Expected rigid 4 by 4 matrices")
        matrices.append(_rigid_matrix(matrix.tobytes(),0,1e-5))
    a,b = matrices
    delta = points @ (a[:3,:3]-b[:3,:3]).T + a[:3,3]-b[:3,3]
    return float(np.sqrt(np.mean(np.sum(delta*delta,axis=1))))


def distinct_hypothesis_indices(transforms, probe_points, maximum=6, minimum_rms=2.):
    """Keep input-ranked hypotheses that move the object differently.

    Ranking is the caller's training-only responsibility. This function does
    not evaluate holdout observations or establish physical correctness.
    """
    if not isinstance(maximum,int) or isinstance(maximum,bool) or maximum<1 or minimum_rms<=0 or not np.isfinite(minimum_rms):
        raise ValueError("Positive maximum and displacement threshold required")
    retained=[]
    for i,matrix in enumerate(transforms):
        hypothesis_rms_displacement(matrix,matrix,probe_points)
        if all(hypothesis_rms_displacement(matrix,transforms[j],probe_points)>=minimum_rms for j in retained):
            retained.append(i)
            if len(retained)==maximum:
                break
    return retained

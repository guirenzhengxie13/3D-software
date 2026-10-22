"""Local point-to-plane constraint spectrum; never calibrated pose uncertainty.

Rotation acts about the stated center. The dimensionless perturbation is
[rotation_radians, translation_mm / length_mm], with residual divided by length.
"""

import numpy as np


def constraint_jacobian(points_mm, normals, center_mm, length_mm):
    points=np.asarray(points_mm,dtype=float);normals=np.asarray(normals,dtype=float)
    center=np.asarray(center_mm,dtype=float)
    if points.ndim!=2 or points.shape[1:]!=(3,) or len(points)<6 or normals.shape!=points.shape:
        raise ValueError('Need at least six paired finite points and normals')
    if center.shape!=(3,) or not all(np.isfinite(a).all() for a in [points,normals,center]):
        raise ValueError('Points, normals, and center must be finite')
    if not np.isscalar(length_mm) or not np.isfinite(length_mm) or length_mm<=0:
        raise ValueError('Normalization length must be positive and finite')
    magnitudes=np.linalg.norm(normals,axis=1)
    if np.any(magnitudes<1e-12):raise ValueError('Normals must have nonzero length')
    unit=normals/magnitudes[:,None]
    return np.column_stack((np.cross((points-center)/length_mm,unit),unit))


def constraint_spectrum(points_mm, normals, center_mm, length_mm):
    jacobian=constraint_jacobian(points_mm,normals,center_mm,length_mm)
    gram=jacobian.T@jacobian/len(jacobian)
    values,vectors=np.linalg.eigh(gram);values=np.maximum(values,0)
    relative=values/values[-1] if values[-1]>0 else values.copy()
    for column in range(6):
        vector=vectors[:,column]
        if vector[np.argmax(np.abs(vector))]<0:vectors[:,column]*=-1
    return dict(correspondences=len(jacobian),center_mm=np.asarray(center_mm,float).tolist(),
        length_mm=float(length_mm),gram_mean=gram.tolist(),eigenvalues=values.tolist(),
        relative_eigenvalues=relative.tolist(),smallest_to_largest_ratio=float(relative[0]),
        eigenvectors_columns=vectors.tolist(),
        numerical_rank_relative_1e_9=int(np.count_nonzero(relative>1e-9)),
        modes_below_relative_one_percent=int(np.count_nonzero(relative<.01)),
        diagnostic_only_not_covariance=True)

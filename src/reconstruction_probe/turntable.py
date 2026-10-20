"""Diagnose compatibility of saved poses with one fixed rotation axis.

This models relative motion in the scan reference frame. It cannot identify
physical camera motion versus object/turntable motion, nor certify tracking.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation


def predict_fixed_axis_poses(poses,axis,axis_point,reference_pose):
    """Project supplied relative rotations onto a fixed-axis pose hypothesis.

    Per-record angles still come from the supplied saved rotations. This is
    a kinematic prior, not independently recovered tracking or timing.
    """
    matrices=np.asarray(poses,float);direction=np.asarray(axis,float);center=np.asarray(axis_point,float);anchor=np.asarray(reference_pose,float)
    if matrices.ndim!=3 or matrices.shape[1:]!=(4,4) or direction.shape!=(3,) or center.shape!=(3,) or anchor.shape!=(4,4):raise ValueError('Invalid pose/axis dimensions')
    if not all(np.isfinite(value).all() for value in (matrices,direction,center,anchor)) or np.linalg.norm(direction)<1e-10:raise ValueError('Finite poses and nonzero axis required')
    all_poses=np.concatenate((matrices,anchor[None]))
    rotations=all_poses[:,:3,:3]
    if not np.allclose(all_poses[:,3],[0,0,0,1],atol=1e-5,rtol=0) or np.max(np.abs(rotations.transpose(0,2,1)@rotations-np.eye(3)))>1e-5 or np.any(np.abs(np.linalg.det(rotations)-1)>1e-5):raise ValueError('Proper rigid input poses required')
    direction=direction/np.linalg.norm(direction);relative=matrices@np.linalg.inv(anchor);R=relative[:,:3,:3]
    skew=np.column_stack((R[:,2,1]-R[:,1,2],R[:,0,2]-R[:,2,0],R[:,1,0]-R[:,0,1]))
    sine=.5*(skew@direction);cosine=.5*(np.trace(R,axis1=1,axis2=2)-np.einsum('i,nij,j->n',direction,R,direction))
    angles=np.arctan2(sine,cosine);fitted=Rotation.from_rotvec(angles[:,None]*direction).as_matrix()
    predicted=np.repeat(np.eye(4)[None],len(matrices),axis=0);predicted[:,:3,:3]=fitted;predicted[:,:3,3]=np.einsum('nij,j->ni',np.eye(3)-fitted,center)
    return predicted@anchor


def _distribution(values):
    values = np.asarray(values, dtype=float)
    return {"median": float(np.median(values)), "p90": float(np.percentile(values, 90)),
            "max": float(np.max(values))}


def diagnose_fixed_axis(poses, *, huber_mm=2.0):
    """Return a descriptive fixed-axis fit and per-pose arrays, in mm.

    Poses map the same camera-local convention to one common scan frame.
    For each pose M_i, A_i=M_i inverse(M_0). A one-axis model has
    A_i=[R(axis,theta_i), (I-R(axis,theta_i))c]. The location along the axis
    is unobservable, so c is chosen perpendicular to the axis.
    """
    matrices = np.asarray(poses, dtype=float)
    if matrices.ndim != 3 or matrices.shape[1:] != (4, 4) or len(matrices) < 3:
        raise ValueError("At least three 4x4 poses are required")
    if not np.isfinite(matrices).all() or not np.isfinite(huber_mm) or huber_mm <= 0:
        raise ValueError("Finite poses and a positive robust scale are required")
    rotations = matrices[:, :3, :3]
    if (not np.allclose(matrices[:, 3, :], [0, 0, 0, 1], atol=1e-4, rtol=0)
            or np.max(np.abs(rotations.transpose(0, 2, 1) @ rotations - np.eye(3))) > 1e-4
            or np.max(np.abs(np.linalg.det(rotations) - 1)) > 1e-4):
        raise ValueError("Proper rigid poses are required")
    relative = matrices @ np.linalg.inv(matrices[0])
    rotvecs = Rotation.from_matrix(relative[:, :3, :3]).as_rotvec()
    magnitudes = np.linalg.norm(rotvecs, axis=1)
    useful = magnitudes > np.deg2rad(5)
    if np.count_nonzero(useful) < 2:
        raise ValueError("Insufficient rotation beyond five degrees to estimate an axis")
    values, vectors = np.linalg.eigh(rotvecs[useful].T @ rotvecs[useful])
    axis = vectors[:, -1]
    if axis[np.argmax(np.abs(axis))] < 0:
        axis = -axis
    eigen_fraction = float(values[-1] / values.sum())
    unit_rotvecs = rotvecs[useful] / magnitudes[useful, None]
    axis_errors = np.rad2deg(np.arccos(np.clip(np.abs(unit_rotvecs @ axis), 0, 1)))

    relative_R = relative[:, :3, :3]
    skew = np.column_stack((relative_R[:, 2, 1] - relative_R[:, 1, 2],
                            relative_R[:, 0, 2] - relative_R[:, 2, 0],
                            relative_R[:, 1, 0] - relative_R[:, 0, 1]))
    sine = .5 * (skew @ axis)
    cosine = .5 * (np.trace(relative_R, axis1=1, axis2=2)
                     - np.einsum("i,nij,j->n", axis, relative_R, axis))
    angles = np.arctan2(sine, cosine)
    fitted_R = Rotation.from_rotvec(angles[:, None] * axis).as_matrix()
    # Explicit two-dimensional coordinates remove the unobservable axial
    # translation, rather than relying on a numerical rank cutoff.
    seed = np.eye(3)[np.argmin(np.abs(axis))]
    first = np.cross(axis, seed)
    first /= np.linalg.norm(first)
    basis = np.column_stack((first, np.cross(axis, first)))
    blocks = (np.eye(3) - fitted_R) @ basis
    target = relative[:, :3, 3]
    weights = np.ones(len(matrices))
    for _ in range(12):
        root_weights = np.sqrt(weights)
        design = (blocks * root_weights[:, None, None]).reshape(-1, 2)
        response = (target * root_weights[:, None]).reshape(-1)
        position_2d, _, rank, _ = np.linalg.lstsq(design, response, rcond=None)
        if rank < 2:
            raise ValueError("Rotation sequence does not constrain an axis line")
        center = basis @ position_2d
        fitted_t = np.einsum("nij,j->ni", np.eye(3) - fitted_R, center)
        residual = np.linalg.norm(target - fitted_t, axis=1)
        weights = np.minimum(1., huber_mm / np.maximum(residual, 1e-12))
    ideal_relative = np.repeat(np.eye(4)[None], len(matrices), axis=0)
    ideal_relative[:, :3, :3] = fitted_R
    ideal_relative[:, :3, 3] = fitted_t
    ideal_poses = ideal_relative @ matrices[0]
    rotation_errors = np.rad2deg(Rotation.from_matrix(
        fitted_R.transpose(0, 2, 1) @ relative_R).magnitude())
    centers = matrices[:, :3, 3]
    center_errors = np.linalg.norm(centers - ideal_poses[:, :3, 3], axis=1)
    vectors_to_axis = centers - center
    axial = vectors_to_axis @ axis
    radius = np.linalg.norm(vectors_to_axis - axial[:, None] * axis, axis=1)
    unwrapped_degrees = np.rad2deg(np.unwrap(angles))
    summary = {
        "poses": len(matrices), "unit": "mm", "axis_direction_in_scan_frame": axis.tolist(),
        "axis_point_minimum_norm_mm": center.tolist(),
        "axis_location_along_itself_is_unobservable": True,
        "rotation_axis_energy_fraction": eigen_fraction,
        "rotation_axis_deviation_deg": _distribution(axis_errors),
        "rotation_residual_deg": _distribution(rotation_errors),
        "relative_translation_residual_mm": _distribution(residual),
        "camera_origin_model_residual_mm": _distribution(center_errors),
        "orbit_radius_mm": _distribution(radius),
        "orbit_axial_range_mm": float(np.ptp(axial)),
        "unwrapped_angle_span_deg": float(np.ptp(unwrapped_degrees)),
        "huber_scale_mm": huber_mm,
        "meaning": "Compatibility diagnostic for one fixed-axis relative-motion model; no pose correction is applied.",
        "limitations": [
            "Object/turntable motion and physical camera motion cannot be separated from these relative poses alone.",
            "A good one-axis fit does not prove tracking accuracy or physical camera stationarity.",
            "Camera repositioning, object movement and multiple scan passes may legitimately violate this model.",
            "Angles follow supplied record order; no capture timestamps or physical angular speed are inferred.",
            "Fitted poses are diagnostic predictions and are not automatically used for fusion.",
        ],
    }
    arrays = {"saved_poses": matrices, "model_poses": ideal_poses,
              "camera_origins_mm": centers, "model_camera_origins_mm": ideal_poses[:, :3, 3],
              "relative_translation_residual_mm": residual, "rotation_residual_deg": rotation_errors,
              "camera_origin_model_residual_mm": center_errors, "unwrapped_angles_deg": unwrapped_degrees,
              "orbit_radius_mm": radius, "orbit_axial_mm": axial}
    return summary, arrays

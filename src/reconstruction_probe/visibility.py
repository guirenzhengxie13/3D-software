"""Signed optical-depth evidence for points in a saved scan coordinate frame."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ProjectedDepthObservations:
    point_indices: np.ndarray
    pixel_indices: np.ndarray
    signed_delta_mm: np.ndarray


def project_depth_observations(xyz_scan_mm, camera_to_scan, depth_mm, calibration, axis_signs):
    """Return point indices and measured-Z minus projected-Z, in millimetres.

    Positive differences can conflict with observed free space; negative ones
    indicate occlusion by a nearer measured surface. Zero/missing depth and
    points behind the camera or outside the image provide no observation.
    """
    xyz = np.asarray(xyz_scan_mm, dtype=float)
    pose = np.asarray(camera_to_scan, dtype=float)
    depth = np.asarray(depth_mm)
    K = np.asarray(calibration["K"], dtype=float)
    signs = np.asarray(axis_signs, dtype=float)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
        raise ValueError("Expected finite N by 3 scan points")
    if pose.shape != (4,4) or not np.isfinite(pose).all():
        raise ValueError("Expected finite camera-to-scan pose")
    if (depth.ndim != 2 or not depth.size or K.shape != (3,3) or signs.shape != (3,)
            or not np.isfinite(K).all() or not np.all(np.abs(signs)==1)):
        raise ValueError("Invalid depth, calibration or axes")
    if calibration["width"]<=0 or calibration["height"]<=0 or K[0,0]<=0 or K[1,1]<=0:
        raise ValueError("Positive calibrated dimensions and focal lengths required")
    h,w = depth.shape
    camera = ((xyz-pose[:3,3])@pose[:3,:3])*signs
    z = camera[:,2];front=np.flatnonzero(z>0)
    u=np.rint((camera[front,0]/z[front]*K[0,0]+K[0,2])*w/calibration["width"]).astype(int)
    v=np.rint((camera[front,1]/z[front]*K[1,1]+K[1,2])*h/calibration["height"]).astype(int)
    inside=(u>=0)&(u<w)&(v>=0)&(v<h);chosen=front[inside]
    measured=depth[v[inside],u[inside]];valid=np.isfinite(measured)&(measured>0)
    pixels=v[inside][valid]*w+u[inside][valid]
    chosen=chosen[valid]
    return ProjectedDepthObservations(chosen,pixels,measured[valid]-z[chosen])


def depth_observation_deltas(xyz_scan_mm, camera_to_scan, depth_mm, calibration, axis_signs):
    """Compatibility pair of point indices and signed millimetre deltas."""
    observed=project_depth_observations(xyz_scan_mm,camera_to_scan,depth_mm,calibration,axis_signs)
    return observed.point_indices,observed.signed_delta_mm

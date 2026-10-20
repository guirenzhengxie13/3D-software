"""Object-relative optical camera proposals for offline inspection."""

import numpy as np


def fibonacci_directions(count=128):
    if type(count) is not int or count<4:raise ValueError("At least four sphere samples required")
    i=np.arange(count,dtype=float);z=1-2*(i+.5)/count;r=np.sqrt(1-z*z);angle=i*np.pi*(3-np.sqrt(5))
    return np.column_stack((r*np.cos(angle),r*np.sin(angle),z))


def look_at_optical_pose(camera,target,up=(-1.,0,0)):
    camera,target,up=[np.asarray(value,float) for value in (camera,target,up)]
    if any(value.shape!=(3,) or not np.isfinite(value).all() for value in (camera,target,up)):raise ValueError("Expected finite XYZ vectors")
    forward=target-camera;length=np.linalg.norm(forward)
    if length<=1e-10 or np.linalg.norm(up)<=1e-10:raise ValueError("Distinct camera/target and nonzero up required")
    forward/=length;right=np.cross(forward,up)
    if np.linalg.norm(right)<1e-8:
        alternate=np.eye(3)[np.argmin(np.abs(forward))];right=np.cross(forward,alternate)
    right/=np.linalg.norm(right);down=np.cross(forward,right)
    pose=np.eye(4);pose[:3,:3]=np.column_stack((right,down,forward));pose[:3,3]=camera
    return pose


def minimum_view_separation_degrees(candidates,observed):
    candidates,observed=np.asarray(candidates,float),np.asarray(observed,float)
    if candidates.ndim!=2 or observed.ndim!=2 or candidates.shape[1]!=3 or observed.shape[1]!=3 or not np.isfinite(candidates).all() or not np.isfinite(observed).all():raise ValueError("Expected finite N by 3 view vectors")
    lengths=np.linalg.norm(candidates,axis=1)
    if np.any(lengths<=1e-12):raise ValueError("Nonzero candidate directions required")
    if not len(observed):return np.full(len(candidates),180.)
    existing_lengths=np.linalg.norm(observed,axis=1)
    if np.any(existing_lengths<=1e-12):raise ValueError("Nonzero observed directions required")
    closest=(candidates/lengths[:,None])@(observed/existing_lengths[:,None]).T
    return np.rad2deg(np.arccos(np.clip(closest.max(1),-1,1)))


def target_visible_from_hit(hit_distance,target_distance,tolerance_mm):
    hit,target=np.asarray(hit_distance,float),np.asarray(target_distance,float)
    if tolerance_mm<=0 or not np.isfinite(tolerance_mm) or np.any(target<=0) or not np.isfinite(target).all():raise ValueError("Positive finite target distance/tolerance required")
    return np.isfinite(hit)&(np.abs(hit-target)<=tolerance_mm)

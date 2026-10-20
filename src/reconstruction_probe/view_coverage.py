"""Descriptive direction coverage of saved observations, not confidence."""

import numpy as np


def support_view_indices(packed_bits,frame_count):
    """Recover saved-view indices from one LSB-first per-point support mask."""
    bits=np.asarray(packed_bits)
    if type(frame_count) is not int or frame_count<0 or bits.ndim!=1 or bits.dtype!=np.uint8 or len(bits)!=(frame_count+7)//8:
        raise ValueError("Invalid packed support-view mask")
    expanded=np.unpackbits(bits,bitorder='little')
    if expanded[frame_count:].any():raise ValueError("Nonzero support-mask padding")
    return np.flatnonzero(expanded[:frame_count])


class ViewDirectionAccumulator:
    def __init__(self,size):
        if type(size) is not int or size<1:raise ValueError("Positive point count required")
        self.count=np.zeros(size,np.uint32)
        self.first=np.zeros((size,3),float)
        self.sum=np.zeros((size,3),float)
        self.minimum_first_dot=np.ones(size,float)

    def add(self,indices,point_to_camera_vectors):
        ids=np.asarray(indices)
        vectors=np.asarray(point_to_camera_vectors,float)
        if ids.ndim!=1 or ids.dtype.kind not in 'iu' or vectors.shape!=(len(ids),3):raise ValueError("Expected integer IDs and N by 3 vectors")
        if not np.isfinite(vectors).all() or np.any(ids<0) or np.any(ids>=len(self.count)) or len(np.unique(ids))!=len(ids):raise ValueError("Invalid or repeated point IDs/directions")
        lengths=np.linalg.norm(vectors,axis=1)
        if np.any(lengths<=1e-12):raise ValueError("Nonzero view vectors required")
        directions=vectors/lengths[:,None]
        first=self.count[ids]==0
        self.first[ids[first]]=directions[first]
        self.minimum_first_dot[ids]=np.minimum(self.minimum_first_dot[ids],np.sum(self.first[ids]*directions,axis=1))
        self.count[ids]+=1;self.sum[ids]+=directions

    def metrics(self):
        present=self.count>0
        separation=np.full(len(self.count),np.nan);concentration=separation.copy();equivalent_angle=separation.copy()
        separation[present]=np.rad2deg(np.arccos(np.clip(self.minimum_first_dot[present],-1,1)))
        concentration[present]=np.clip(np.linalg.norm(self.sum[present]/self.count[present,None],axis=1),0,1)
        equivalent_angle[present]=np.rad2deg(np.arccos(concentration[present]))
        return dict(first_support_max_separation_deg=separation,direction_resultant_length=concentration,
            resultant_equivalent_angle_deg=equivalent_angle)

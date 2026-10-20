"""Bounded-workspace spatial previews that retain original PLY vertex IDs.

One real source vertex nearest each occupied voxel center is retained. The
voxel search is a measured heuristic, not a claim of globally optimal sample
selection. Every returned preview respects the requested point budget.
"""

import numpy as np

from .ply_layout import xyz_block


class RepresentativeCapacityExceeded(RuntimeError):
    pass


def bounds_of_records(records,chunk_size=100000):
    lower=np.full(3,np.inf);upper=-lower;count=0
    for start in range(0,len(records),chunk_size):
        xyz=xyz_block(records,start,start+chunk_size);xyz=xyz[np.isfinite(xyz).all(1)]
        if len(xyz):lower=np.minimum(lower,xyz.min(0));upper=np.maximum(upper,xyz.max(0));count+=len(xyz)
    if count==0:raise ValueError('No finite source points')
    return lower,upper,count


def _reduce(keys,scores,ids):
    order=np.lexsort((ids,scores,keys[:,2],keys[:,1],keys[:,0]));keys=keys[order];scores=scores[order];ids=ids[order]
    first=np.r_[True,np.any(keys[1:]!=keys[:-1],axis=1)]
    return keys[first],scores[first],ids[first]


def voxel_representative_ids(records,voxel_mm,origin_mm,maximum_cells,chunk_size=100000):
    if not np.isfinite(voxel_mm) or voxel_mm<=0 or type(maximum_cells) is not int or maximum_cells<1 or type(chunk_size) is not int or chunk_size<1:
        raise ValueError('Positive voxel, cell capacity and chunk size required')
    origin=np.asarray(origin_mm,float)
    if origin.shape!=(3,) or not np.isfinite(origin).all():raise ValueError('Finite XYZ voxel origin required')
    keys=np.empty((0,3),np.int64);scores=np.empty(0);ids=np.empty(0,np.int64)
    for start in range(0,len(records),chunk_size):
        xyz=xyz_block(records,start,start+chunk_size);valid=np.isfinite(xyz).all(1);source_ids=np.arange(start,start+len(xyz),dtype=np.int64)[valid];xyz=xyz[valid]
        if not len(xyz):continue
        scaled=(xyz-origin)/voxel_mm
        if np.any(np.abs(scaled)>np.iinfo(np.int64).max/2):raise ValueError('Voxel coordinates exceed supported range')
        new_keys=np.floor(scaled).astype(np.int64);new_scores=np.sum((scaled-new_keys-.5)**2,axis=1)
        new_keys,new_scores,source_ids=_reduce(new_keys,new_scores,source_ids)
        keys,scores,ids=_reduce(np.concatenate((keys,new_keys)),np.r_[scores,new_scores],np.r_[ids,source_ids])
        if len(ids)>maximum_cells:raise RepresentativeCapacityExceeded('Spatial preview cell capacity exceeded; coarsen voxel size')
    return ids


def budgeted_spatial_preview(records,budget=40000,chunk_size=100000,max_attempts=12):
    if type(budget) is not int or not 1<=budget<=1000000 or type(max_attempts) is not int or max_attempts<1:
        raise ValueError('Use a point budget in 1..1000000 and positive attempts')
    lower,upper,count=bounds_of_records(records,chunk_size);attempts=[]
    if count<=budget:
        chosen=[]
        for start in range(0,len(records),chunk_size):
            xyz=xyz_block(records,start,start+chunk_size);chosen.append(np.arange(start,start+len(xyz))[np.isfinite(xyz).all(1)])
        return dict(ids=np.concatenate(chosen).astype(np.int64),voxel_mm=0.,origin_mm=lower,finite_source_points=count,
            bounds_min_mm=lower,bounds_max_mm=upper,attempts=attempts,coverage_distance_upper_bound_mm=0.)
    extent=float(np.max(upper-lower))
    if extent==0:
        ids=voxel_representative_ids(records,1.,lower,maximum_cells=budget,chunk_size=chunk_size)
        return dict(ids=ids,voxel_mm=1.,origin_mm=lower,finite_source_points=count,bounds_min_mm=lower,bounds_max_mm=upper,attempts=attempts,coverage_distance_upper_bound_mm=0.)
    voxel=extent/np.sqrt(budget);best=None;too_fine=None
    for _ in range(max_attempts):
        try:
            ids=voxel_representative_ids(records,voxel,lower,maximum_cells=max(2*budget,1000),chunk_size=chunk_size)
            attempts.append(dict(voxel_mm=voxel,occupied_cells=len(ids),capacity_exceeded=False))
            if len(ids)<=budget:
                if best is None or len(ids)>len(best[0]) or (len(ids)==len(best[0]) and voxel<best[1]):best=(ids,voxel)
                if len(ids)>=.95*budget:break
                next_voxel=(voxel+too_fine)/2 if too_fine is not None else voxel*.85
            else:
                too_fine=voxel;next_voxel=(voxel+best[1])/2 if best is not None else voxel*max(1.1,np.sqrt(len(ids)/budget)*1.05)
        except RepresentativeCapacityExceeded:
            attempts.append(dict(voxel_mm=voxel,occupied_cells=None,capacity_exceeded=True));too_fine=voxel
            next_voxel=(voxel+best[1])/2 if best is not None else voxel*1.6
        voxel=next_voxel
    if best is None:
        # A guaranteed feasible voxel places every finite point into at most
        # one cell per axis, while retaining at least one real source ID.
        voxel=max(extent*2,np.finfo(float).eps);ids=voxel_representative_ids(records,voxel,lower,maximum_cells=budget,chunk_size=chunk_size);best=(ids,voxel)
        attempts.append(dict(voxel_mm=voxel,occupied_cells=len(ids),capacity_exceeded=False,fallback=True))
    ids,voxel=best
    return dict(ids=ids,voxel_mm=voxel,origin_mm=lower,finite_source_points=count,bounds_min_mm=lower,bounds_max_mm=upper,
        attempts=attempts,coverage_distance_upper_bound_mm=float(np.sqrt(3)*voxel))

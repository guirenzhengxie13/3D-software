"""Read-only lattice/edge diagnostics for the CPU Open3D VoxelBlockGrid.

Voxel coordinates are integer XYZ; stored tensor flattening uses X fastest.
Diagnostics never edit integration values or certify physical geometry.
"""

import numpy as np


def lattice_edges(point_mm,voxel_mm,tolerance_mm=1e-4):
    point=np.asarray(point_mm,float)
    if point.shape!=(3,) or not np.isfinite(point).all() or not np.isfinite(voxel_mm) or voxel_mm<=0 or not np.isfinite(tolerance_mm) or tolerance_mm<=0:raise ValueError('Need finite XYZ, positive voxel and tolerance')
    scaled=point/voxel_mm;rounded=np.rint(scaled).astype(np.int64);result=[]
    for axis in range(3):
        others=[i for i in range(3) if i!=axis]
        if np.any(np.abs(point[others]-rounded[others]*voxel_mm)>tolerance_mm):continue
        starts=[int(np.floor(scaled[axis]))]
        if abs(point[axis]-rounded[axis]*voxel_mm)<=tolerance_mm:starts=[int(rounded[axis])-1,int(rounded[axis])]
        for start in starts:
            a=rounded.copy();a[axis]=start;b=a.copy();b[axis]+=1
            result.append(dict(axis=axis,start=a.tolist(),end=b.tolist()))
    return result


def neighborhood_voxels(point_mm,voxel_mm,radius=1):
    point=np.asarray(point_mm,float)
    if point.shape!=(3,) or not np.isfinite(point).all() or not np.isfinite(voxel_mm) or voxel_mm<=0 or type(radius) is not int or not 0<=radius<=3:raise ValueError('Invalid local lattice request')
    base=np.floor(point/voxel_mm).astype(np.int64);axis=np.arange(-radius,radius+2,dtype=np.int64)
    return base+np.array(np.meshgrid(axis,axis,axis,indexing='ij')).reshape(3,-1).T


def read_voxels(grid,coordinates,resolution=16):
    import open3d as o3d
    coords=np.asarray(coordinates)
    if coords.ndim!=2 or coords.shape[1]!=3 or coords.dtype.kind not in 'iu' or type(resolution) is not int or resolution<1:raise ValueError('Need integer voxel XYZ')
    if coords.dtype.kind=='u' and np.any(coords>np.iinfo(np.int64).max):raise ValueError('Voxel coordinate outside int64 range')
    coords=coords.astype(np.int64);blocks=np.floor_divide(coords,resolution);local=coords-blocks*resolution
    if np.any(blocks<np.iinfo(np.int32).min) or np.any(blocks>np.iinfo(np.int32).max):raise ValueError('Block key outside int32 range')
    unique,inverse=np.unique(blocks,axis=0,return_inverse=True)
    indices,masks=grid.hashmap().find(o3d.core.Tensor(unique.astype(np.int32)))
    found=masks.numpy()[inverse];buffers=indices.numpy()[inverse].astype(np.int64)
    tsdf=np.full(len(coords),np.nan,np.float32);weight=np.zeros(len(coords),np.float32)
    flat=buffers[found]*resolution**3+local[found,2]*resolution**2+local[found,1]*resolution+local[found,0]
    if len(flat):
        tsdf[found]=grid.attribute('tsdf').reshape((-1,)).numpy()[flat]
        weight[found]=grid.attribute('weight').reshape((-1,)).numpy()[flat]
    return dict(coordinates=coords.copy(),allocated=found.copy(),tsdf=tsdf,weight=weight)


def edge_evidence(edge,state,voxel_mm,threshold=3.,point_mm=None):
    lookup={tuple(c):i for i,c in enumerate(state['coordinates'])};ids=[lookup[tuple(edge[k])] for k in ['start','end']]
    available=bool(np.all(state['allocated'][ids]));tsdf=state['tsdf'][ids].astype(float);weights=state['weight'][ids].astype(float)
    opposite=bool(available and np.isfinite(tsdf).all() and tsdf[0]*tsdf[1]<0)
    gate=bool(available and np.all(weights>threshold));ratio=None;predicted=None;distance=None
    if opposite:
        a,b=np.float32(tsdf);ratio=float(np.float32(-a/np.float32(b-a)))
        grid=np.array(edge['start'],np.float32);grid[edge['axis']]+=np.float32(ratio)
        predicted=(np.float32(voxel_mm/1000)*grid).astype(float)*1000
        if point_mm is not None:distance=float(np.linalg.norm(predicted-np.asarray(point_mm,float)))
    return dict(**edge,allocated=available,tsdf=[float(x) if np.isfinite(x) else None for x in tsdf],weights=weights.tolist(),opposite_sign=opposite,strict_weight_gate=gate,point_extractable=opposite and gate,ratio=ratio,predicted_mm=None if predicted is None else predicted.tolist(),distance_to_reference_mm=distance)

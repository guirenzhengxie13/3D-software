"""Build a spatial point preview with original IDs and paired coverage checks."""

import os
os.environ.setdefault('OMP_NUM_THREADS','4')
os.environ.setdefault('OPENBLAS_NUM_THREADS','4')

import argparse
import json
from pathlib import Path
import time

import numpy as np
import psutil
from scipy.spatial import cKDTree

from reconstruction_probe.lod_cache import record_rgb,load_lod_cache
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.ply_layout import map_ply_vertices,xyz_block
from reconstruction_probe.spatial_lod import budgeted_spatial_preview


def coverage(records,preview_xyz,chunk_size=100000):
    tree=cKDTree(preview_xyz);maximum=0.;total=0.;count=0
    for start in range(0,len(records),chunk_size):
        xyz=xyz_block(records,start,start+chunk_size);xyz=xyz[np.isfinite(xyz).all(1)]
        if not len(xyz):continue
        distances,_=tree.query(xyz,workers=1);maximum=max(maximum,float(distances.max()));total+=float(distances.sum());count+=len(xyz)
    query_ids=np.linspace(0,len(records)-1,min(100000,len(records)),dtype=np.int64);query=np.column_stack([records[name][query_ids] for name in ['x','y','z']]);valid=np.isfinite(query).all(1)
    distance,_=tree.query(query[valid],workers=1)
    return dict(full_finite_points=count,full_maximum_representation_distance_mm=maximum,full_mean_representation_distance_mm=total/count,
        fixed_row_sample_count=len(distance),sample_distance_quantiles_mm=dict(zip(['median','p90','p99','max'],np.percentile(distance,[50,90,99,100]).tolist())))


def write_preview_ply(path,xyz,rgb,ids):
    rows=np.empty(len(ids),dtype=[('x','<f4'),('y','<f4'),('z','<f4'),('red','u1'),('green','u1'),('blue','u1'),('source_vertex_id','<u4')])
    for j,name in enumerate(['x','y','z']):rows[name]=xyz[:,j]
    for j,name in enumerate(['red','green','blue']):rows[name]=rgb[:,j]
    rows['source_vertex_id']=ids
    header=['ply','format binary_little_endian 1.0','comment units mm','comment derived_spatial_preview_original_vertex_ids_not_a_new_fusion',f'element vertex {len(ids)}',
        'property float x','property float y','property float z','property uchar red','property uchar green','property uchar blue','property uint source_vertex_id','end_header']
    with path.open('wb') as stream:stream.write(('\n'.join(header)+'\n').encode('ascii'));stream.write(rows.tobytes())


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--unit',choices=['mm'],required=True)
    parser.add_argument('--budget',type=int,default=40000);parser.add_argument('--chunk-size',type=int,default=100000);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    if source.parent==out or source.parent in out.parents:parser.error('Keep caches separate from the source model directory')
    started=time.perf_counter();records,layout=map_ply_vertices(source)
    if layout.vertex_count>np.iinfo(np.uint32).max:parser.error('Current browser point IDs are limited to uint32')
    selection=budgeted_spatial_preview(records,args.budget,args.chunk_size);ids=selection['ids'].astype(np.uint64)
    original=np.column_stack([records[name][ids] for name in ['x','y','z']]);xyz=original.astype('<f4');rgb=record_rgb(records,ids)
    if not np.isfinite(xyz).all():raise ValueError('Preview coordinates exceed float32 range')
    rounding=float(np.linalg.norm(original-xyz.astype(float),axis=1).max());selection_seconds=time.perf_counter()-started
    spatial=coverage(records,xyz,args.chunk_size)
    uniform_ids=np.linspace(0,len(records)-1,len(ids),dtype=np.int64);uniform=np.column_stack([records[name][uniform_ids] for name in ['x','y','z']]).astype('<f4');uniform=uniform[np.isfinite(uniform).all(1)]
    uniform_coverage=coverage(records,uniform,args.chunk_size)
    if spatial['full_maximum_representation_distance_mm']>selection['coverage_distance_upper_bound_mm']+rounding+1e-6:raise ValueError('Measured spatial coverage exceeded occupied-voxel bound')
    out.mkdir(parents=True,exist_ok=True);np.savez_compressed(out/'preview-data.npz',original_vertex_ids=ids,xyz_mm=xyz,rgb=rgb)
    write_preview_ply(out/'preview-mm.ply',xyz,rgb,ids)
    summary=dict(format_version=1,kind='spatial_original_vertex_preview',unit='mm',source_path=str(source),source_sha256=file_sha256(source),source_vertex_count=layout.vertex_count,
        finite_source_points=selection['finite_source_points'],requested_budget=args.budget,preview_points=len(ids),voxel_mm=selection['voxel_mm'],origin_mm=selection['origin_mm'].tolist(),
        representation_distance_upper_bound_mm=selection['coverage_distance_upper_bound_mm'],max_float32_preview_rounding_mm=rounding,
        bounds_min_mm=selection['bounds_min_mm'].tolist(),bounds_max_mm=selection['bounds_max_mm'].tolist(),search_attempts=selection['attempts'],
        selection_seconds=selection_seconds,total_elapsed_seconds=time.perf_counter()-started,spatial_coverage=spatial,
        same_count_row_uniform_control=dict(points=len(uniform),coverage=uniform_coverage),
        process_rss_after_bytes=psutil.Process().memory_info().rss,process_peak_working_set_bytes=getattr(psutil.Process().memory_info(),'peak_wset',None),
        output_sha256={name:file_sha256(out/name) for name in ['preview-data.npz','preview-mm.ply']},
        limitations=['This is display/interaction sampling, not a new reconstructed surface or physical accuracy estimate.',
          'Original source vertex IDs and original source content hash are retained; no voxel-centroid synthetic vertex is substituted.',
          'Search retains the best feasible observed candidate; arbitrary voxel sizes do not give a proven monotonic cell-count function.',
          'Coverage is source-to-preview distance; it does not certify shape identity, dimensional accuracy or browser frame rate.',
          'Full mean and maximum distances are measured on all finite source points; quantiles use at most 100000 fixed source rows.',
          'A preview point cache alone does not replace full-resolution local picking or raw-depth integration.'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    verified=load_lod_cache(out,source,args.budget,verify_original_rows=True)
    print(json.dumps(dict(source_points=layout.vertex_count,preview_points=len(ids),voxel_mm=selection['voxel_mm'],seconds=summary['total_elapsed_seconds'],
        spatial=spatial,row_uniform=uniform_coverage,original_ids_verified=len(verified['ids']),peak_working_set_bytes=summary['process_peak_working_set_bytes'])),flush=True)


if __name__=='__main__':main()

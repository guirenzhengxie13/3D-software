"""Export exact original vertices around source IDs for local detailed picking."""

import argparse
import json
from pathlib import Path

import numpy as np

from reconstruction_probe.lod_cache import record_rgb,write_vertex_preview_ply,load_lod_cache
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.ply_spatial_index import PlySpatialIndex


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--index',type=Path,required=True);parser.add_argument('--source',type=Path)
    parser.add_argument('--vertex-id',type=int,action='append',required=True);parser.add_argument('--radius-mm',type=float,default=5.)
    parser.add_argument('--maximum-points',type=int,default=60000);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    if not 1<=args.maximum_points<=1000000:parser.error('Use 1..1000000 exact output points')
    with PlySpatialIndex(args.index,args.source) as index:
        if out==index.source.parent or index.source.parent in out.parents:parser.error('Keep region outputs outside the original model directory')
        all_ids=[];regions=[]
        for rid in args.vertex_id:
            if rid<0 or rid>=len(index.records):raise ValueError('Requested original vertex ID is out of range')
            center=np.array([index.records[name][rid] for name in ['x','y','z']],float);result=index.query_sphere(center,args.radius_mm)
            all_ids.append(result['original_vertex_ids']);regions.append(dict(center_original_vertex_id=rid,center_mm=center.tolist(),radius_mm=args.radius_mm,exact_points=len(result['original_vertex_ids'])))
        ids=np.unique(np.concatenate(all_ids)).astype(np.uint64)
        if not len(ids) or len(ids)>args.maximum_points:raise ValueError('Exact region point count is empty or exceeds output budget; adjust region size')
        xyz=np.column_stack([index.records[name][ids] for name in ['x','y','z']]).astype('<f4');rgb=record_rgb(index.records,ids);source=index.source;meta=index.metadata
    out.mkdir(parents=True,exist_ok=True);np.savez_compressed(out/'preview-data.npz',original_vertex_ids=ids,xyz_mm=xyz,rgb=rgb);write_vertex_preview_ply(out/'preview-mm.ply',xyz,rgb,ids)
    report=dict(format_version=1,kind='exact_source_vertex_region_preview',unit='mm',source_path=str(source),source_sha256=meta['source_sha256'],source_vertex_count=meta['source_vertex_count'],
        preview_points=len(ids),regions=regions,all_selected_original_vertices_retained=True,
        input_sha256={str(args.index.resolve()/'summary.json'):file_sha256(args.index/'summary.json')},
        output_sha256={name:file_sha256(out/name) for name in ['preview-data.npz','preview-mm.ply']},
        limitations=['This is an exact subset of the original surface model within selected spheres, not recovery of missing geometry.',
          'Its original source IDs can be sent to the same correspondence verification backend; the region PLY row number is not that original ID.',
          'Browser GPU rendering and the interactive coarse-to-local transition remain separately unverified.'])
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');load_lod_cache(out,source,verify_original_rows=True)
    print(json.dumps(dict(points=len(ids),regions=len(regions),original_ids_verified=True,output=str(out))),flush=True)


if __name__=='__main__':main()

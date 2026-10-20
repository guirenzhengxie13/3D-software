"""Benchmark disk-backed local queries and verify every result against source rows."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import psutil

from reconstruction_probe.ply_layout import map_ply_vertices,xyz_block
from reconstruction_probe.ply_spatial_index import build_ply_spatial_index,PlySpatialIndex


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--unit',choices=['mm'],required=True);parser.add_argument('--tile-mm',type=float,default=5.);parser.add_argument('--queries',type=int,default=12)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--index',type=Path);args=parser.parse_args();out=args.out.resolve();source=args.source.resolve()
    if not 1<=args.queries<=100:parser.error('Use 1..100 validation queries')
    if args.worker:
        process=psutil.Process();started=time.perf_counter();index=PlySpatialIndex(args.index,source);open_seconds=time.perf_counter()-started
        sampled=np.linspace(0,len(index.records)-1,args.queries,dtype=np.int64);centers=np.column_stack([index.records[name][sampled] for name in ['x','y','z']]);radii=np.resize([3.,5.,10.],args.queries)
        results=[];recorded=[]
        for center,radius in zip(centers,radii):
            result=index.query_sphere(center,float(radius));recorded.append(result['original_vertex_ids'])
            results.append(dict(center_mm=center.tolist(),radius_mm=float(radius),candidate_points=result['candidate_points'],visited_tiles=result['visited_tiles'],
                result_points=len(result['original_vertex_ids']),query_seconds=result['elapsed_seconds'],returned_ids_sha256=hashlib.sha256(result['original_vertex_ids'].astype('<u8').tobytes()).hexdigest()))
        info=process.memory_info();before_validation=dict(rss_bytes=info.rss,peak_working_set_bytes=getattr(info,'peak_wset',None))
        for row,expected in zip(results,recorded):
            center=np.array(row['center_mm']);radius=row['radius_mm'];parts=[];started=time.perf_counter()
            for start in range(0,len(index.records),100000):
                xyz=xyz_block(index.records,start,start+100000);inside=np.sum((xyz-center)**2,axis=1)<=radius**2;parts.append(start+np.flatnonzero(inside))
            brute=np.concatenate(parts);row['brute_force_seconds']=time.perf_counter()-started
            if not np.array_equal(brute,expected):raise ValueError('Tile index omitted or added original source vertices')
            row['exact_original_ids_match']=True
        index.close();times=[r['query_seconds'] for r in results];brute=[r['brute_force_seconds'] for r in results]
        report=dict(source=str(source),input_points=index.metadata['source_vertex_count'],open_and_hash_validation_seconds=open_seconds,query_count=len(results),
            median_query_seconds=float(np.median(times)),maximum_query_seconds=float(np.max(times)),median_brute_force_seconds=float(np.median(brute)),
            memory_before_brute_force_validation=before_validation,all_exact_original_ids_match=True,queries=results,
            synthetic_stress_fixture=source.name.startswith('synthetic-'),limitations=['Local-query times exclude one-time index opening and source/hash verification, which are reported separately.',
              'Brute-force validation touches the full source mapping and can raise later working set; the pre-validation memory checkpoint is separate.',
              'Measurements are single-run CPU/backend costs, not browser GPU frame rate or a latency guarantee.'])
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');print(json.dumps({k:report[k] for k in ['input_points','open_and_hash_validation_seconds','median_query_seconds','maximum_query_seconds','median_brute_force_seconds','memory_before_brute_force_validation','all_exact_original_ids_match']}),flush=True);return
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);build=build_ply_spatial_index(source,out/'index',args.tile_mm)
    print(json.dumps(dict(index_build_seconds=build['elapsed_seconds'],index_bytes=build['index_bytes'],tiles=build['tiles'])),flush=True)
    subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker','--source',str(source),'--index',str(out/'index'),'--queries',str(args.queries),'--unit','mm','--out',str(out/'queries.json')],check=True)
    report=dict(build=build,query_benchmark=json.loads((out/'queries.json').read_text(encoding='utf-8')))
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()

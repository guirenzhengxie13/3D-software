"""Measure per-cloud CPU operations in isolated workers with memory accounting."""

import os
os.environ.setdefault('OMP_NUM_THREADS','4')
os.environ.setdefault('OPENBLAS_NUM_THREADS','4')

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import numpy as np
import psutil

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.ply_layout import map_ply_vertices,xyz_block
from reconstruction_probe.sources import _read_ply_cloud


class MemoryProbe:
    def __init__(self):
        self.process=psutil.Process();self.baseline=self.process.memory_info().rss;self.peak=self.baseline;self.stop=threading.Event()
        self.thread=threading.Thread(target=self.monitor,daemon=True);self.thread.start()
    def monitor(self):
        while not self.stop.wait(.01):self.peak=max(self.peak,self.process.memory_info().rss)
    def finish(self):
        self.stop.set();self.thread.join();info=self.process.memory_info()
        return dict(baseline_rss_bytes=self.baseline,sampled_peak_rss_bytes=max(self.peak,info.rss),
            process_lifetime_peak_working_set_bytes=getattr(info,'peak_wset',None),rss_at_end_bytes=info.rss,sampling_interval_seconds=.01)


def worker(args):
    source=args.source.resolve();probe=MemoryProbe();stages=[]
    def measure(name,operation):
        before=time.perf_counter();result=operation();stages.append(dict(name=name,seconds=time.perf_counter()-before,rss_after_bytes=psutil.Process().memory_info().rss));return result
    def scan_mapped():
        rows,layout=map_ply_vertices(source);lower=np.full(3,np.inf);upper=-lower;count=0
        for start in range(0,len(rows),100000):
            xyz=xyz_block(rows,start,start+100000);xyz=xyz[np.isfinite(xyz).all(1)]
            if len(xyz):lower=np.minimum(lower,xyz.min(0));upper=np.maximum(upper,xyz.max(0));count+=len(xyz)
        del rows
        return dict(finite_points=count,bounds_min_mm=lower.tolist(),bounds_max_mm=upper.tolist())
    mapped=measure('read_only_mapping_and_streaming_bounds',scan_mapped)
    def import_open3d():
        import open3d
        return open3d
    o3d=measure('import_open3d',import_open3d)
    pc=measure('open3d_full_cloud_read',lambda:_read_ply_cloud(o3d,source))
    if pc.is_empty():raise ValueError('No loaded points')
    xyz=np.asarray(pc.points);n=len(xyz);down=measure('voxel_down_sample_0_5mm',lambda:pc.voxel_down_sample(.5))
    # A cap is explicitly recorded; this stage is not a claim that normals
    # were computed for every original or every downsampled source point.
    normal_ids=np.linspace(0,len(down.points)-1,min(200000,len(down.points)),dtype=int);normal_cloud=down.select_by_index(normal_ids.tolist())
    measure('estimate_normals_capped_200k_radius_1_5mm',lambda:normal_cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=1.5,max_nn=40)))
    def build_tree():
        from scipy.spatial import cKDTree
        return cKDTree(xyz,copy_data=False)
    tree=measure('ckdtree_build_full_cloud',build_tree)
    rng=np.random.default_rng(20261019);query_ids=rng.integers(0,n,5000);queries=xyz[query_ids]+rng.normal(0,.1,(5000,3))
    distances,nearest=measure('ckdtree_5000_nearest_queries',lambda:tree.query(queries,workers=1))
    if not np.isfinite(distances).all() or np.any(nearest<0) or np.any(nearest>=n):raise ValueError('Invalid nearest-neighbor output')
    zero_distances,zero_ids=tree.query(xyz[query_ids],workers=1)
    if np.max(zero_distances)>1e-8:raise ValueError('Known original points did not find a zero-distance neighbor')
    center=xyz[int(query_ids[0])].copy()
    cropped=measure('ckdtree_5mm_radius_query',lambda:tree.query_ball_point(center,5.))
    def streaming_radius_query():
        records,_=map_ply_vertices(source);parts=[]
        for start in range(0,len(records),100000):
            values=xyz_block(records,start,start+100000);kept=np.linalg.norm(values-center,axis=1)<=5.;parts.append(start+np.flatnonzero(kept))
        del records
        return np.concatenate(parts)
    streamed=measure('mapped_full_scan_5mm_radius_query',streaming_radius_query)
    if not np.array_equal(np.sort(cropped),np.sort(streamed)):raise ValueError('Spatial query point IDs differ between full tree and streamed source')
    result=dict(label=args.label,source=str(source),source_sha256=file_sha256(source),unit='mm',input_points=n,
        unicode_path_temporary_copy_used=os.name=='nt' and not str(source).isascii(),
        scipy_first_import_is_included_in_tree_stage=True,
        input_has_colors=pc.has_colors(),input_has_normals=pc.has_normals(),downsampled_points=len(down.points),normal_stage_points=len(normal_cloud.points),
        stages=stages,memory=probe.finish(),radius_query_points=len(cropped),nearest_self_control_passed=True,radius_original_ids_match=True,
        geometry_array_payload_bytes=sum(a.nbytes for a in [np.asarray(pc.points),np.asarray(pc.colors),np.asarray(pc.normals)]),
        synthetic_stress_fixture=source.name.startswith('synthetic-'),
        limitations=['Single local run with current OS caches and background applications; timings are not stable performance guarantees.',
          'Normals are explicitly capped at 200000 downsampled points; that stage is not full-source normal processing.',
          'CPU operations only. No browser GPU frame rate, interaction latency or rendered image has been verified.',
          'Peak working set includes library imports and intermediate allocations; array byte counts exclude them.'])
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');print(json.dumps(dict(label=args.label,points=n,stages=stages,memory=result['memory'])),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--worker',action='store_true');parser.add_argument('--source',type=Path);parser.add_argument('--label',default='cloud')
    parser.add_argument('--cloud',action='append',default=[],help='LABEL=PLY, all explicit millimetre coordinates');parser.add_argument('--unit',choices=['mm'],required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.worker:
        if args.source is None:parser.error('Worker requires source')
        worker(args);return
    if not args.cloud:parser.error('At least one --cloud LABEL=PATH required')
    out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);results=[]
    for i,entry in enumerate(args.cloud):
        label,path=entry.split('=',1);output=out/f'case-{i}.json'
        subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker','--source',path,'--label',label,'--unit','mm','--out',str(output)],check=True)
        results.append(json.loads(output.read_text(encoding='utf-8')))
    summary=dict(measured_at_utc=datetime.now(timezone.utc).isoformat(),cases=results,cpu_threads=dict(OMP_NUM_THREADS=os.environ['OMP_NUM_THREADS'],OPENBLAS_NUM_THREADS=os.environ['OPENBLAS_NUM_THREADS']))
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()

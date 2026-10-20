"""Disk-backed tile-to-original-vertex index for local full-resolution queries."""

import json
from pathlib import Path
import time

import numpy as np

from .offline import file_sha256
from .ply_layout import map_ply_vertices,xyz_block
from .spatial_lod import bounds_of_records


KEY_DTYPE=np.dtype([('x','<i8'),('y','<i8'),('z','<i8')])


def _structured(keys):return np.ascontiguousarray(keys,dtype='<i8').view(KEY_DTYPE).reshape(-1)


def _merge_counts(keys,counts,new_keys,new_counts):
    keys=np.concatenate((keys,new_keys));counts=np.r_[counts,new_counts];order=np.lexsort((keys[:,2],keys[:,1],keys[:,0]));keys=keys[order];counts=counts[order]
    first=np.r_[True,np.any(keys[1:]!=keys[:-1],axis=1)];starts=np.flatnonzero(first)
    return keys[starts],np.add.reduceat(counts,starts)


def _keys(xyz,origin,tile_mm):
    scaled=(xyz-origin)/tile_mm
    if np.any(np.abs(scaled)>np.iinfo(np.int64).max/2):raise ValueError('Spatial tile coordinates exceed supported range')
    return np.floor(scaled).astype(np.int64)


def build_ply_spatial_index(source,destination,tile_mm=5.,chunk_size=100000,maximum_tiles=2000000):
    source=Path(source).resolve();out=Path(destination).resolve()
    if not np.isfinite(tile_mm) or tile_mm<=0 or type(chunk_size) is not int or chunk_size<1 or maximum_tiles<1:
        raise ValueError('Positive spatial tile/chunk/capacity required')
    if out.exists() and any(out.iterdir()):raise ValueError('Use a new/empty index directory')
    if out==source.parent or source.parent in out.parents:raise ValueError('Keep index outputs outside the source model directory')
    started=time.perf_counter();source_sha=file_sha256(source);source_stat=source.stat();records,layout=map_ply_vertices(source)
    origin,upper,finite_count=bounds_of_records(records,chunk_size);keys=np.empty((0,3),np.int64);counts=np.empty(0,np.int64)
    for start in range(0,len(records),chunk_size):
        xyz=xyz_block(records,start,start+chunk_size);xyz=xyz[np.isfinite(xyz).all(1)]
        if not len(xyz):continue
        local,local_counts=np.unique(_keys(xyz,origin,tile_mm),axis=0,return_counts=True)
        keys,counts=_merge_counts(keys,counts,local,local_counts)
        if len(keys)>maximum_tiles:raise MemoryError('Spatial index tile capacity exceeded; use larger tiles')
    offsets=np.r_[np.int64(0),np.cumsum(counts,dtype=np.int64)]
    if offsets[-1]!=finite_count:raise ValueError('Spatial tile accounting differs from source finite-point count')
    out.mkdir(parents=True,exist_ok=True);id_dtype=np.dtype('<u4' if len(records)<=np.iinfo(np.uint32).max else '<u8')
    ids_path=out/'original-vertex-ids.bin';ids=np.memmap(ids_path,mode='w+',dtype=id_dtype,shape=(finite_count,));cursors=np.zeros(len(keys),np.int64);structured_keys=_structured(keys)
    for start in range(0,len(records),chunk_size):
        xyz=xyz_block(records,start,start+chunk_size);valid=np.isfinite(xyz).all(1);source_ids=np.arange(start,start+len(xyz),dtype=np.int64)[valid];xyz=xyz[valid]
        if not len(xyz):continue
        local_keys=_keys(xyz,origin,tile_mm);tile_ids=np.searchsorted(structured_keys,_structured(local_keys))
        if np.any(tile_ids>=len(keys)) or not np.array_equal(keys[tile_ids],local_keys):raise ValueError('Spatial tile lookup mismatch')
        order=np.argsort(tile_ids,kind='stable');tile_ids=tile_ids[order];source_ids=source_ids[order]
        unique,starts,sizes=np.unique(tile_ids,return_index=True,return_counts=True)
        for tile,begin,size in zip(unique,starts,sizes):
            destination_start=offsets[tile]+cursors[tile];ids[destination_start:destination_start+size]=source_ids[begin:begin+size];cursors[tile]+=size
    ids.flush();del ids;del records
    if not np.array_equal(cursors,counts):raise ValueError('Spatial index second-pass accounting mismatch')
    if source.stat().st_size!=source_stat.st_size or source.stat().st_mtime_ns!=source_stat.st_mtime_ns or file_sha256(source)!=source_sha:
        raise ValueError('Source model changed during spatial index construction')
    np.savez_compressed(out/'tiles.npz',keys=keys,offsets=offsets,origin_mm=origin)
    report=dict(format_version=1,kind='original_ply_vertex_tile_index',unit='mm',source_path=str(source),source_sha256=source_sha,
        source_vertex_count=layout.vertex_count,finite_source_points=finite_count,tile_mm=float(tile_mm),tiles=len(keys),id_dtype=id_dtype.str,
        maximum_points_per_tile=int(counts.max()),median_points_per_tile=float(np.median(counts)),elapsed_seconds=time.perf_counter()-started,
        index_bytes=ids_path.stat().st_size+(out/'tiles.npz').stat().st_size,
        output_sha256={name:file_sha256(out/name) for name in ['tiles.npz','original-vertex-ids.bin']},
        limitations=['This is a search index, not a simplified or reconstructed geometry. Each finite original vertex is retained exactly once.',
          'The source model and derived index are both required; vertex IDs remain source-local and content-bound.',
          'Large requested regions are rejected by a candidate budget instead of silently truncating precise selections.',
          'Memory-mapped file pages can contribute to process working set and OS cache; the index is not zero-memory.'])
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');return report


class PlySpatialIndex:
    def __init__(self,directory,source=None):
        self.directory=Path(directory).resolve();self.metadata=json.loads((self.directory/'summary.json').read_text(encoding='utf-8'))
        meta=self.metadata
        if meta.get('format_version')!=1 or meta.get('kind')!='original_ply_vertex_tile_index' or meta.get('unit')!='mm':raise ValueError('Unsupported spatial index')
        self.source=Path(source).resolve() if source is not None else Path(meta['source_path'])
        if file_sha256(self.source)!=meta['source_sha256']:raise ValueError('Spatial index source model changed')
        for name,digest in meta['output_sha256'].items():
            if file_sha256(self.directory/name)!=digest:raise ValueError('Spatial index payload changed')
        with np.load(self.directory/'tiles.npz',allow_pickle=False) as saved:
            self.keys=saved['keys'].copy();self.offsets=saved['offsets'].copy();self.origin=saved['origin_mm'].copy()
        if len(self.keys)!=meta['tiles'] or len(self.offsets)!=len(self.keys)+1 or self.offsets[0]!=0 or np.any(np.diff(self.offsets)<=0) or self.offsets[-1]!=meta['finite_source_points']:
            raise ValueError('Invalid spatial index offsets')
        self.records,self.layout=map_ply_vertices(self.source)
        if len(self.records)!=meta['source_vertex_count']:raise ValueError('Spatial index source count changed')
        self.ids=np.memmap(self.directory/'original-vertex-ids.bin',mode='r',dtype=meta['id_dtype'],shape=(meta['finite_source_points'],))
        stat=self.source.stat();self.source_signature=(stat.st_size,stat.st_mtime_ns)

    def _check_source(self):
        stat=self.source.stat()
        if (stat.st_size,stat.st_mtime_ns)!=self.source_signature:raise ValueError('Source model changed while spatial index was open')

    def query_sphere(self,center_mm,radius_mm,maximum_candidate_points=500000):
        self._check_source();center=np.asarray(center_mm,float)
        if center.shape!=(3,) or not np.isfinite(center).all() or not np.isfinite(radius_mm) or radius_mm<0 or type(maximum_candidate_points) is not int or maximum_candidate_points<1:
            raise ValueError('Finite center, nonnegative radius and positive candidate budget required')
        started=time.perf_counter();lower=self.origin+self.keys*self.metadata['tile_mm'];upper=lower+self.metadata['tile_mm']
        outside=np.maximum(np.maximum(lower-center,center-upper),0);eligible=np.flatnonzero(np.sum(outside**2,axis=1)<=radius_mm**2+1e-12)
        candidate_count=int(np.sum(self.offsets[eligible+1]-self.offsets[eligible]))
        if candidate_count>maximum_candidate_points:raise MemoryError('Requested exact region exceeds candidate budget; reduce radius or use a preview')
        ids=np.concatenate([self.ids[self.offsets[i]:self.offsets[i+1]] for i in eligible]) if len(eligible) else np.empty(0,dtype=self.ids.dtype)
        xyz=np.column_stack([self.records[name][ids] for name in ['x','y','z']]).astype(float)
        inside=np.sum((xyz-center)**2,axis=1)<=radius_mm**2;ids=ids[inside].copy();xyz=xyz[inside];order=np.argsort(ids)
        self._check_source()
        return dict(original_vertex_ids=ids[order],xyz_mm=xyz[order],candidate_points=candidate_count,visited_tiles=len(eligible),elapsed_seconds=time.perf_counter()-started)

    def close(self):
        for name in ['records','ids']:
            array=getattr(self,name,None)
            if isinstance(array,np.memmap):array._mmap.close()
        self.records=None;self.ids=None

    def __enter__(self):return self
    def __exit__(self,*_):self.close()

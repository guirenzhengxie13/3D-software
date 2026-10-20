"""Load content-bound spatial preview caches without reading a full Open3D cloud."""

import json
from pathlib import Path

import numpy as np

from .offline import file_sha256
from .ply_layout import inspect_ply,map_ply_vertices,xyz_block


def record_rgb(records,ids):
    names=set(records.dtype.names or [])
    if not {'red','green','blue'}<=names:return np.full((len(ids),3),165,np.uint8)
    rgb=np.column_stack([records[name][ids] for name in ['red','green','blue']])
    if rgb.dtype.kind not in 'ui' or np.any(rgb<0) or np.any(rgb>255):raise ValueError('Preview cache requires byte-range integer PLY RGB')
    return rgb.astype(np.uint8)


def load_lod_cache(cache_directory,source,maximum_points=None,verify_original_rows=False):
    root=Path(cache_directory).resolve();source=Path(source).resolve();metadata=json.loads((root/'summary.json').read_text(encoding='utf-8'))
    if metadata.get('format_version')!=1 or metadata.get('unit')!='mm' or metadata.get('kind') not in ['spatial_original_vertex_preview','exact_source_vertex_region_preview']:
        raise ValueError('Unsupported spatial preview cache')
    if file_sha256(source)!=metadata['source_sha256']:raise ValueError('Spatial preview source file changed')
    if inspect_ply(source).vertex_count!=metadata['source_vertex_count']:raise ValueError('Spatial preview source vertex count changed')
    path=root/'preview-data.npz'
    if file_sha256(path)!=metadata['output_sha256']['preview-data.npz']:raise ValueError('Spatial preview payload changed')
    with np.load(path,allow_pickle=False) as saved:ids=saved['original_vertex_ids'].copy();xyz=saved['xyz_mm'].copy();rgb=saved['rgb'].copy()
    if ids.dtype!=np.uint64 or xyz.dtype!=np.float32 or rgb.dtype!=np.uint8 or xyz.shape!=(len(ids),3) or rgb.shape!=xyz.shape:
        raise ValueError('Invalid spatial preview arrays')
    if not len(ids) or len(np.unique(ids))!=len(ids) or np.any(ids>=metadata['source_vertex_count']) or not np.isfinite(xyz).all():
        raise ValueError('Invalid spatial preview vertex identity/coordinates')
    if len(ids)!=metadata['preview_points'] or (maximum_points is not None and len(ids)>maximum_points):
        raise ValueError('Spatial preview exceeds the requested display budget; build a smaller cache')
    if verify_original_rows:
        records,_=map_ply_vertices(source);original=np.column_stack([records[name][ids] for name in ['x','y','z']]).astype(np.float32)
        if not np.array_equal(original,xyz) or not np.array_equal(record_rgb(records,ids),rgb):raise ValueError('Preview IDs do not match original PLY rows')
        del records
    return dict(metadata=metadata,ids=ids,xyz=xyz,rgb=rgb,manifest_path=str(root/'summary.json'),manifest_sha256=file_sha256(root/'summary.json'))


def include_original_vertices(preview,source,required_ids,maximum_points):
    """Keep earlier selected points when opening a different preview sample."""
    if not isinstance(required_ids,list) or any(type(rid) is not int or rid<0 for rid in required_ids):raise ValueError('Original landmark IDs must be nonnegative integers')
    if file_sha256(source)!=preview['metadata']['source_sha256']:raise ValueError('Landmark preview source changed')
    missing=np.setdiff1d(np.asarray(required_ids,np.uint64),preview['ids'])
    if np.any(missing>=preview['metadata']['source_vertex_count']):raise ValueError('Required original landmark ID is out of range')
    if len(preview['ids'])+len(missing)>maximum_points:raise ValueError('Required landmarks exceed display budget; use a smaller cache or a larger display budget')
    result=dict(preview)
    if len(missing):
        records,_=map_ply_vertices(source);xyz=np.column_stack([records[name][missing] for name in ['x','y','z']]).astype(np.float32);rgb=record_rgb(records,missing);del records
        if not np.isfinite(xyz).all():raise ValueError('Required landmark has nonfinite coordinates')
        result.update(ids=np.r_[preview['ids'],missing],xyz=np.concatenate((preview['xyz'],xyz)),rgb=np.concatenate((preview['rgb'],rgb)))
    result['added_required_original_ids']=missing.tolist();return result


def write_vertex_preview_ply(path,xyz,rgb,ids):
    if np.any(np.asarray(ids)>np.iinfo(np.uint32).max):raise ValueError('Current preview PLY vertex IDs require uint32')
    rows=np.empty(len(ids),dtype=[('x','<f4'),('y','<f4'),('z','<f4'),('red','u1'),('green','u1'),('blue','u1'),('source_vertex_id','<u4')])
    for j,name in enumerate(['x','y','z']):rows[name]=xyz[:,j]
    for j,name in enumerate(['red','green','blue']):rows[name]=rgb[:,j]
    rows['source_vertex_id']=ids
    header=['ply','format binary_little_endian 1.0','comment units mm','comment derived_preview_preserving_original_vertex_ids_not_a_new_fusion',f'element vertex {len(ids)}',
        'property float x','property float y','property float z','property uchar red','property uchar green','property uchar blue','property uint source_vertex_id','end_header']
    with Path(path).open('wb') as stream:stream.write(('\n'.join(header)+'\n').encode('ascii'));stream.write(rows.tobytes())

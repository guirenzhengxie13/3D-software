"""Write an explicitly synthetic tiled cloud for bounded scalability checks."""

import argparse
import json
from pathlib import Path

import numpy as np

from reconstruction_probe.lod_cache import record_rgb
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.ply_layout import map_ply_vertices
from reconstruction_probe.spatial_lod import bounds_of_records


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--points',type=int,default=10000000)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();source=args.source.resolve();out=args.out.resolve()
    if out.exists() or not 1<=args.points<=50000000:parser.error('Use a new PLY file and 1..50000000 synthetic points')
    records,layout=map_ply_vertices(source);lower,upper,finite=bounds_of_records(records)
    if finite!=len(records):raise ValueError('Stress fixture base must contain finite points')
    spacing=float(np.max(upper-lower)+20.);dtype=np.dtype([('x','<f4'),('y','<f4'),('z','<f4'),('red','u1'),('green','u1'),('blue','u1')])
    header=['ply','format binary_little_endian 1.0','comment units mm','comment SYNTHETIC_TILED_STRESS_FIXTURE_NOT_SENSOR_CAPTURE',f'element vertex {args.points}',
        'property float x','property float y','property float z','property uchar red','property uchar green','property uchar blue','end_header']
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('wb') as stream:
        stream.write(('\n'.join(header)+'\n').encode())
        for start in range(0,args.points,100000):
            global_ids=np.arange(start,min(start+100000,args.points));ids=global_ids%len(records);tiles=global_ids//len(records)
            xyz=np.column_stack([records[name][ids] for name in ['x','y','z']]);xyz[:,0]+=(tiles%4)*spacing;xyz[:,1]+=(tiles//4)*spacing
            rgb=record_rgb(records,ids);rows=np.empty(len(ids),dtype=dtype)
            for j,name in enumerate(['x','y','z']):rows[name]=xyz[:,j]
            for j,name in enumerate(['red','green','blue']):rows[name]=rgb[:,j]
            stream.write(rows.tobytes())
    metadata=dict(kind='synthetic_tiled_scalability_fixture_not_a_real_scan',points=args.points,unit='mm',tile_spacing_mm=spacing,
        base_source=str(source),base_source_points=layout.vertex_count,base_source_sha256=file_sha256(source),output_sha256=file_sha256(out),bytes=out.stat().st_size,
        limitations=['Repeated translated geometry is a scalability control, not a new scan or evidence of physical accuracy.',
          'It tests data-size costs but does not reproduce arbitrary industrial shape complexity or sensor noise.'])
    out.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(metadata),flush=True)


if __name__=='__main__':main()

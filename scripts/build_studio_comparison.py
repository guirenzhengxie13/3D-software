"""Build a dual-pane comparison with the same viewer used by Web Studio.

Embeds exact shared viewer, picker and CPU raster sources, with their hashes.
Only explicit common-frame mm inputs are accepted; no registration is inferred.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from reconstruction_probe.lod_cache import record_rgb
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.ply_layout import map_ply_vertices
from reconstruction_probe.spatial_lod import budgeted_spatial_preview
from reconstruction_probe.web_studio import pack


def build(specifications, out, common_frame, notes='', title='三维重建 · 两组结果对照', budget=40000):
    if len(specifications)!=2 or not common_frame.strip() or not 100<=budget<=60000:
        raise ValueError('Use exactly two explicit common-frame inputs and 100..60000 preview points')
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(out)
    if out.suffix.lower()!='.html' or out.exists():raise ValueError('Use a new HTML file inside the workspace')
    clouds=[];lo=np.full(3,np.inf);hi=np.full(3,-np.inf)
    for specification in specifications:
        label,separator,name=specification.partition('=')
        if not separator or not label.strip():raise ValueError('Expected label=PLY path')
        path=mapper.resolve(name);digest=file_sha256(path);records,_=map_ply_vertices(path)
        xyz=np.column_stack([records[key] for key in ['x','y','z']])
        if not len(xyz) or not np.isfinite(xyz).all():raise ValueError('Comparison requires finite complete source coordinates')
        lo=np.minimum(lo,xyz.min(0));hi=np.maximum(hi,xyz.max(0));preview=budgeted_spatial_preview(records,budget);ids=preview['ids']
        cloud=dict(pack(xyz[ids],record_rgb(records,ids),ids),id='comparison-'+str(len(clouds)),label=label,
                   originalPoints=len(records),source_sha256=digest,path=str(path),selection='spatial_original_vertices')
        clouds.append(cloud);del records,xyz
        if file_sha256(path)!=digest:raise ValueError('Comparison input changed while reading')
    assets={'__MATH__':root/'web/landmark-workbench/registration_math.js',
            '__RASTER__':root/'web/landmark-workbench/point_raster.js','__VIEWER__':root/'web/studio/point_viewer.js'}
    payload=dict(format_version=1,unit='mm',title=title,notes=notes,commonFrame=common_frame,
        boundsMm=[lo.tolist(),hi.tolist()],clouds=clouds,viewer_sources_sha256={p.relative_to(root).as_posix():file_sha256(p) for p in assets.values()})
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
    html=(root/'web/studio/comparison.html').read_text(encoding='utf-8').replace('__PAYLOAD__',encoded,1)
    for marker,path in assets.items():html=html.replace(marker,path.read_text(encoding='utf-8'),1)
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(html,encoding='utf-8')
    return payload


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud',action='append',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--unit',choices=['mm'],required=True)
    parser.add_argument('--common-frame',required=True)
    parser.add_argument('--notes',default='');parser.add_argument('--title',default='三维重建 · 两组结果对照')
    parser.add_argument('--max-points',type=int,default=40000)
    args=parser.parse_args();payload=build(args.cloud,args.out,args.common_frame,args.notes,args.title,args.max_points)
    print(json.dumps(dict(output=str(args.out),clouds=[dict(label=c['label'],original=c['originalPoints'],display=c['displayPoints']) for c in payload['clouds']]),ensure_ascii=False))


if __name__=='__main__':main()

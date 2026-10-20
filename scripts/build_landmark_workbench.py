"""Build a standalone correspondence alignment workbench for the study fragments."""

import argparse
import base64
import json
from pathlib import Path

import numpy as np

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.poses import _rigid_matrix
from reconstruction_probe.lod_cache import load_lod_cache,include_original_vertices
from reconstruction_probe.sources import _read_ply_cloud


def read(path):return json.loads(path.read_text(encoding="utf-8"))


def cloud(path,label,limit,lod_cache=None,required_ids=None):
    if lod_cache is not None:
        cached=load_lod_cache(lod_cache,path,limit)
        if required_ids:cached=include_original_vertices(cached,path,required_ids,limit)
        if cached['metadata']['source_vertex_count']>np.iinfo(np.uint32).max:raise ValueError('Unsupported original point ID range')
        return dict(label=label,path=str(path),sourceSha256=cached['metadata']['source_sha256'],originalPoints=cached['metadata']['source_vertex_count'],displayPoints=len(cached['ids']),
            xyz=base64.b64encode(cached['xyz'].astype('<f4').tobytes()).decode(),rgb=base64.b64encode(cached['rgb'].tobytes()).decode(),
            ids=base64.b64encode(cached['ids'].astype('<u4').tobytes()).decode(),previewSelection='local_original_vertices' if cached['metadata']['kind']=='exact_source_vertex_region_preview' else 'spatial_original_vertices',
            requiredOriginalVerticesAdded=cached.get('added_required_original_ids',[]),
            lodCache=dict(path=cached['manifest_path'],sha256=cached['manifest_sha256']))
    import open3d as o3d
    pc=_read_ply_cloud(o3d,path);xyz=np.asarray(pc.points);valid=np.flatnonzero(np.isfinite(xyz).all(1))
    if not len(valid) or len(xyz)>np.iinfo(np.uint32).max:raise ValueError("Unsupported point cloud size")
    chosen=valid[np.linspace(0,len(valid)-1,min(limit,len(valid)),dtype=int)]
    if required_ids:
        if any(type(rid) is not int or rid<0 or rid>=len(xyz) for rid in required_ids):raise ValueError('Required landmark IDs out of range')
        chosen=np.union1d(chosen,np.array(required_ids,dtype=np.int64))
        if len(chosen)>limit:raise ValueError('Required landmarks exceed display budget; use a spatial cache with spare capacity')
        if not np.isfinite(xyz[chosen]).all():raise ValueError('Nonfinite required landmark')
    positions=xyz[chosen].astype("<f4")
    if not np.isfinite(positions).all():raise ValueError("Coordinates cannot be displayed as float32")
    colors=np.asarray(pc.colors)[chosen] if pc.has_colors() else np.full((len(chosen),3),165/255)
    if not np.isfinite(colors).all():raise ValueError("Nonfinite preview colors")
    rgb=np.rint(np.clip(colors,0,1)*255).astype(np.uint8)
    return dict(label=label,path=str(path),sourceSha256=file_sha256(path),originalPoints=len(xyz),displayPoints=len(chosen),
        xyz=base64.b64encode(positions.tobytes()).decode(),rgb=base64.b64encode(rgb.tobytes()).decode(),ids=base64.b64encode(chosen.astype("<u4").tobytes()).decode(),previewSelection='row_index_uniform')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--prepared",type=Path);parser.add_argument("--registration",type=Path);parser.add_argument("--out",type=Path,required=True);parser.add_argument("--max-points",type=int,default=40000)
    parser.add_argument('--target-cloud',type=Path);parser.add_argument('--source-cloud',type=Path);parser.add_argument('--target-fragment-id',type=int,default=0);parser.add_argument('--source-fragment-id',type=int,default=1);parser.add_argument('--unit',choices=['mm'])
    parser.add_argument('--target-lod',type=Path);parser.add_argument('--source-lod',type=Path)
    parser.add_argument('--notes',default='')
    parser.add_argument('--include-session',type=Path,help='Retain original landmark IDs from this session in the new preview')
    args=parser.parse_args();prepared=args.prepared.resolve() if args.prepared else None;registration=args.registration.resolve() if args.registration else None;output=args.out.resolve()
    if not 100<=args.max_points<=60000 or output.suffix.lower()!='.html':parser.error("Use HTML output and 100..60000 display points")
    if prepared:
        if args.target_cloud or args.source_cloud:parser.error('Use --prepared or an explicit cloud pair')
        training=read(prepared/"training.json");paths={row["id_high"]:Path(row["path"]) for row in training["groups"]};target_path,source_path=paths[0],paths[1];target_id,source_id=0,1
        if registration is None:registration=prepared/'registration'
    else:
        if not args.target_cloud or not args.source_cloud or args.unit!='mm':parser.error('An explicit cloud pair requires both paths and established --unit mm')
        target_path,source_path=args.target_cloud.resolve(),args.source_cloud.resolve();target_id,source_id=args.target_fragment_id,args.source_fragment_id
        if min(target_id,source_id)<0 or target_id==source_id:parser.error('Distinct nonnegative fragment IDs required')
    candidate_path=registration/'summary.json' if registration else output.with_name(output.stem+'-candidates.json')
    if registration:fitted=read(candidate_path)
    else:
        candidate_path.parent.mkdir(parents=True,exist_ok=True)
        fitted=dict(candidates=[dict(label='identity_unaligned',transform=np.eye(4).tolist())],unit='mm',note='Unaligned original position; no automatic fit performed',input_sha256={str(p):file_sha256(p) for p in [target_path,source_path]})
        candidate_path.write_text(json.dumps(fitted,ensure_ascii=False,indent=2),encoding='utf-8')
    candidates=[]
    for row in fitted["candidates"]:
        matrix=np.array(row["transform"],dtype="<f8")
        if matrix.shape!=(4,4):raise ValueError("Expected 4 by 4 candidate transform")
        _rigid_matrix(matrix.tobytes(),0,1e-5)
        candidates.append(dict(label=row["label"],transform=matrix.tolist()))
    required={'source':[],'target':[]}
    if args.include_session:
        session=read(args.include_session)
        if session.get('format_version')!=1 or session.get('unit')!='mm':raise ValueError('Unsupported included landmark session')
        for name,path,fragment_id in [('source',source_path,source_id),('target',target_path,target_id)]:
            if session.get(name,{}).get('sha256')!=file_sha256(path) or session[name].get('fragment_id',fragment_id)!=fragment_id:raise ValueError('Included landmarks belong to different source/fragment')
            required[name]=[pair[name]['id'] for pair in session.get('point_pairs',[])]
    clouds=[cloud(target_path,f"固定片段 {target_id}",args.max_points,args.target_lod,required['target']),cloud(source_path,f"移动片段 {source_id}",args.max_points,args.source_lod,required['source'])]
    for model,fragment_id in zip(clouds,[target_id,source_id]):model.update(fragmentId=fragment_id,idHighWord=fragment_id if prepared else None)
    data=dict(formatVersion=1,unit="mm",notes=args.notes,preparedPath=str(prepared) if prepared else None,candidateReference=dict(path=str(candidate_path),sha256=file_sha256(candidate_path)),clouds=clouds,candidates=candidates)
    assets=Path(__file__).resolve().parents[1]/"web/landmark-workbench"
    encoded=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
    html=(assets/"index.html").read_text(encoding="utf-8").replace('__DATA__',encoded,1).replace('__MATH__',(assets/"registration_math.js").read_text(encoding="utf-8"),1).replace('__RASTER__',(assets/"point_raster.js").read_text(encoding="utf-8"),1).replace('__APP__',(assets/"app.js").read_text(encoding="utf-8"),1)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(html,encoding="utf-8")
    print(json.dumps(dict(output=str(output),bytes=output.stat().st_size,clouds=[dict(label=row['label'],display=row['displayPoints'],source=row['originalPoints']) for row in data['clouds']])))


if __name__=="__main__":main()

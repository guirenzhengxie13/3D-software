"""Validate frozen voxel readouts and build the interactive local diagnostic."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.ply_layout import map_ply_vertices
from reconstruction_probe.tsdf_trace import edge_evidence


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];mapper=PathMapper(root)
    folder=mapper.resolve(args.report)
    if root/'reports' not in folder.parents:parser.error('Use a local reports folder')
    if (folder/'review.html').exists() or (folder/'presentation.json').exists():parser.error('Presentation already exists; do not overwrite a frozen result')
    pins={}
    def pin(path,expected=None):
        path=mapper.resolve(path);digest=file_sha256(path)
        if expected is not None and digest!=expected:raise ValueError('Input changed: '+str(path))
        if str(path) in pins and pins[str(path)]!=digest:raise ValueError('Input changed during validation')
        pins[str(path)]=digest;return path
    def read(path):
        path=pin(path);raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=pins[str(path)]:raise ValueError('Input changed during read')
        return mapper.record(json.loads(raw.decode('utf-8')))
    data=read(folder/'summary.json')
    for path,digest in data['input_sha256'].items():pin(path,digest)
    template=pin(root/'web/studio/tsdf_voxel_diagnostic.html');pin(Path(__file__))
    checks=[]
    for case in data['cases']:
        name=case['case'];part=folder/name
        if name not in {'coarse-saved','fine-saved','coarse-corrected','fine-corrected'}:raise ValueError('Unexpected replay case')
        if read(part/'summary.json')!=case:raise ValueError('Case summary differs')
        with np.load(pin(part/'voxel-timeline.npz'),allow_pickle=False) as z:
            coords=z['coordinates'];weights=z['weight'];tsdf=z['tsdf'];allocated=z['allocated'];ids=z['frame_ids']
        if len(ids)!=case['observed_frames'] or weights.shape[0]!=len(ids)+1:raise ValueError('Incomplete frame timeline')
        lookup={tuple(c):i for i,c in enumerate(coords)};tested=0
        for target in case['targets']:
            for edge in target['edges']:
                if len(edge['timeline'])!=len(ids)+1:raise ValueError('Missing selected-edge states')
                for n,row in enumerate(edge['timeline']):
                    snapshot=dict(coordinates=coords,weight=weights[n],tsdf=tsdf[n],allocated=allocated[n])
                    actual=edge_evidence({k:edge[k] for k in ['axis','start','end']},snapshot,case['settings']['voxel_mm'],case['settings']['weight_threshold'])
                    for key in ['tsdf','weights','allocated','opposite_sign','strict_weight_gate','point_extractable']:
                        if actual[key]!=row[key]:raise ValueError('Displayed edge state differs from actual tensor readout: '+key)
                    if row['step']!=n or row['frame_id']!=(None if n==0 else str(int(ids[n-1]))):raise ValueError('Frame identity changed')
                    tested+=1
                for endpoint,key in enumerate(['start','end']):
                    column=lookup[tuple(edge[key])];delta=np.diff(weights[:,column]);observed=[str(int(ids[k])) for k in np.flatnonzero(delta>0)]
                    expected=edge['contributors'][endpoint]
                    if observed!=expected['frame_ids'] or len(observed)!=expected['updates']:raise ValueError('Contributor identity differs')
        pair=read(root/'reports/web-studio/runs'/case['reference_job']/'result/summary.json')
        source=pin(pair['results'][0 if name.endswith('saved') else 1]['path'])
        replay=pin(part/'reconstruction/scan_20261018131222/tsdf_pointcloud_mm.ply')
        def xyz(path):
            vertices,_=map_ply_vertices(path)
            return np.column_stack([vertices[k] for k in ['x','y','z']]).astype(float)
        a,b=xyz(source),xyz(replay)
        distance=max(float(cKDTree(a).query(b,workers=1)[0].max()),float(cKDTree(b).query(a,workers=1)[0].max()))
        if len(a)!=len(b) or len(b)!=case['replay_points'] or distance!=case['full_pointset_bidirectional_max_mm'] or distance>1e-7:raise ValueError('Complete reference point set differs')
        checks.append(dict(case=name,edge_snapshot_checks=tested,reference_points=len(a),replay_points=len(b),bidirectional_max_mm=distance))
    if {c['case'] for c in data['cases']}!={'coarse-saved','fine-saved','coarse-corrected','fine-corrected'}:raise ValueError('All four controls required')
    payload=dict(cases=data['cases'],open3d_version=data['open3d_version'],limits=data['limits'])
    encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False).replace('<',chr(92)+'u003c')
    html=template.read_text(encoding='utf-8').replace('__VOXEL_DATA__',encoded,1)
    for path,digest in pins.items():
        if file_sha256(Path(path))!=digest:raise ValueError('Input changed during presentation build: '+path)
    output=folder/'review.html';output.write_text(html,encoding='utf-8',newline='\n')
    manifest=dict(kind='actual_voxel_readout_presentation',checks=checks,edge_snapshot_checks=sum(c['edge_snapshot_checks'] for c in checks),input_sha256=pins,output_sha256={output.name:file_sha256(output)},actual_browser_gpu=False)
    (folder/'presentation.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    print(json.dumps(dict(report=str(output),cases=len(checks),edge_snapshot_checks=manifest['edge_snapshot_checks'],pinned_inputs=len(pins))))


if __name__=='__main__':main()

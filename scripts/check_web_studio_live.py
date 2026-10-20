"""HTTP integration control for our local service; not browser automation."""
import argparse
import base64
import http.client
import json
from pathlib import Path
import re
import time

import numpy as np
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.ply_layout import map_ply_vertices


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8877);args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    def request(path,body=None):
        c=http.client.HTTPConnection('127.0.0.1',args.port,timeout=60);headers={'Content-Type':'application/json'} if body is not None else {}
        c.request('POST' if body is not None else 'GET',path,body=json.dumps(body).encode() if body is not None else None,headers=headers)
        r=c.getresponse();data=r.read();c.close()
        if r.status>=400:raise ValueError(str((r.status,data.decode())))
        return json.loads(data) if 'json' in r.headers.get('Content-Type','') else data
    catalog=request('/api/catalog');checked=[]
    for asset in ['/','/web/studio/style.css','/web/studio/app.js','/web/studio/point_viewer.js','/web/studio/ply_reader.js']:
        if not request(asset):raise ValueError('Empty application asset')
    default=next(m for m in catalog['models'] if m['scan_id']==catalog['default_scan'] and 'tensor-tsdf' in m['path']);cloud=request('/api/cloud?id='+default['id'])
    ids=np.frombuffer(base64.b64decode(cloud['ids']),'<u4');xyz=np.frombuffer(base64.b64decode(cloud['xyz']),'<f4').reshape(-1,3);records,_=map_ply_vertices(Path(default['path']))
    np.testing.assert_array_equal(xyz,np.column_stack([records[n][ids] for n in ['x','y','z']]).astype('<f4'));del records
    for scan in ['scan_20261018122607','scan_20261018131359']:
        frame=request('/api/frame?scan='+scan+'&ordinal=0');image=request(frame['depth_url']);assert image.startswith(b'\x89PNG');checked.append(dict(scan=scan,frame=frame['frame_id'],displayed=frame['displayPoints'],pose_available=frame['pose_available']))
    model=next(m for m in catalog['models'] if 'cup-multi-scan-tsdf' in m['path'] and 'joint_raw_depth' in m['path'])
    def wait(job):
        deadline=time.monotonic()+180
        while job['status'] in ['running','queued'] and time.monotonic()<deadline:
            time.sleep(.4);job=request('/api/jobs/'+job['id'])
        if job['status']!='completed':raise ValueError(json.dumps(job,ensure_ascii=True))
        return job
    earlier=[j for j in request('/api/jobs') if j['kind']=='spatial' and j['status']=='completed' and j.get('workflow',{}).get('nodes',[{}])[0].get('resolved_parameters',{}).get('source')==model['path']]
    spatial=earlier[-1] if earlier else wait(request('/api/jobs',dict(kind='spatial',model_id=model['id'])))
    if len(spatial['workflow']['nodes'])!=2:raise ValueError('Expected preview and index operations')
    region=request('/api/region?id='+model['id']+'&vertex=1000&radius_mm=5')
    region_ids=np.frombuffer(base64.b64decode(region['ids']),'<u4');records,_=map_ply_vertices(Path(model['path']));all_xyz=np.column_stack([records[n] for n in ['x','y','z']]).astype(float)
    expected=np.flatnonzero(np.sum((all_xyz-all_xyz[1000])**2,axis=1)<=25);np.testing.assert_array_equal(region_ids,expected);del records
    page=root/'reports/range2-study-20261018/experiments/cup-direct-split/landmark-workbench.html';html=page.read_text(encoding='utf-8');data=json.loads(re.search(r'<script id="alignment-data" type="application/json">(.*?)</script>',html,re.S)[1]);candidate=next(c for c in data['candidates'] if c['label']=='direct_best_training')
    session=dict(format_version=1,kind='existing_candidate',unit='mm',prepared_path=data['preparedPath'],candidate_reference=data['candidateReference'],candidate_label=candidate['label'],transform_source_to_target=candidate['transform'],point_pairs=[],
        source=dict(path=data['clouds'][1]['path'],sha256=data['clouds'][1]['sourceSha256'],fragment_id=1),target=dict(path=data['clouds'][0]['path'],sha256=data['clouds'][0]['sourceSha256'],fragment_id=0),
        provenance='Automated HTTP replay of an existing recorded candidate; not human annotation')
    source_before={name:file_sha256(Path(session[name]['path'])) for name in ['source','target']}
    alignment=wait(request('/api/jobs',dict(kind='alignment',session=session)))
    result=json.loads((Path(alignment['folder'])/'result/summary.json').read_text(encoding='utf-8'));np.testing.assert_allclose(result['candidates'][0]['transform'],candidate['transform'],atol=1e-10)
    if source_before!={name:file_sha256(Path(session[name]['path'])) for name in source_before}:raise ValueError('Source model changed')
    summary=dict(catalog=catalog['summary'],default_model_original_points=cloud['originalPoints'],default_display_points=cloud['displayPoints'],default_original_ids_and_coordinates_verified=True,
        frames=checked,spatial_job=spatial['id'],spatial_workflow_completed=True,exact_region_points=len(region_ids),exact_region_matches_full_original_sphere=True,
        existing_candidate_alignment_job=alignment['id'],existing_candidate_matrix_preserved=True,source_models_unchanged=True,human_correspondence_not_simulated=True,
        actual_browser_verified=False,actual_gpu_verified=False)
    out=root/'reports/web-studio';out.mkdir(exist_ok=True,parents=True);(out/'http-integration-check.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary),flush=True)

if __name__=='__main__':main()

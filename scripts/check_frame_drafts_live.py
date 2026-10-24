"""Exercise real incomplete frame drafts and optionally a reviewed fusion pair.

The binding/candidate is a frozen research replay, never human approval or a
whole failed-scan repair. Resume reuses persisted snapshot/review/job records.
"""

import argparse
from datetime import datetime,timezone
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import time

from PIL import Image

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8877);parser.add_argument('--out',required=True);parser.add_argument('--node',default=shutil.which('node'));parser.add_argument('--run-fusion',action='store_true');parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(args.out)
    if root/'reports' not in out.parents or (out.exists() and not args.resume):parser.error('Use a new report folder or explicitly resume an existing one')
    out.mkdir(parents=True,exist_ok=args.resume)
    def save(name,value):(out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    def read(name):return json.loads((out/name).read_text(encoding='utf-8'))
    def request(path,body=None,expected=200):
        connection=http.client.HTTPConnection('127.0.0.1',args.port,timeout=120);connection.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body).encode(),{} if body is None else {'Content-Type':'application/json'});response=connection.getresponse();raw=response.read();status=response.status;connection.close()
        if status!=expected:raise ValueError((path,status,raw[:1200]))
        return json.loads(raw)
    scan='scan_20261018131222';context=request('/api/fragments/context?scan='+scan);current=request('/api/frame-drafts?scan='+scan)
    if not (out/'before.json').exists():save('before.json',dict(drafts=current,jobs=request('/api/jobs'),history=request('/api/history?scan='+scan)))
    before=read('before.json');preset=context['presets'][0];alignment=next(a for a in context['alignments'] if a['id'] in preset['alignment_ids']);candidate='selected_frozen_training_1_to_0'
    if candidate not in alignment['candidates']:raise ValueError('Frozen candidate unavailable')
    settings=dict(voxel_mm=.8,truncation_mm=3.2,edge_threshold_mm=3.,weight_threshold=3.)
    complete=dict(format='fragment-editor-draft',format_version=1,unit='mm',alignment=dict(relative_path=alignment['relative_path'],sha256=alignment['sha256']),candidate=candidate,mode='frame_id',source_frames=preset['source_text'],target_frames=preset['target_text'],source_basis=preset['source_basis'],target_basis=preset['target_basis'],decision='Automated draft/settings API replay of frozen 114-frame component; not new human correspondence or geometry approval.',roi_fields=[str(v) for row in preset['roi'] for v in row],fusion_fields={k:str(v) for k,v in settings.items()})
    partial=json.loads(json.dumps(complete));partial['source_frames']='31-88,';partial['roi_fields'][1]='';partial['fusion_fields']['truncation_mm']=''
    snapshots=[]
    for key,label,draft in [('partial','接口验证 · 未完成原帧与ROI',partial),('complete','接口验证 · 114帧与0.8mm参数（非人工批准）',complete)]:
        name=key+'-saved.json'
        if (out/name).exists():result=read(name)
        else:
            body=dict(scan_id=scan,index_sha256=context['index_sha256'],state_sha256=current['state_sha256'],label=label,draft=draft);result=request('/api/frame-drafts',body,201);save(name,result);current=result
        snapshots.append(result['saved_id'])
        restored=request('/api/frame-drafts?scan='+scan+'&draft_id='+result['saved_id']+'&index_sha256='+context['index_sha256'])
        if restored['draft']!=draft:raise ValueError('Draft did not preserve exact text fields')
        save(key+'-restored.json',restored)
    after=request('/api/frame-drafts?scan='+scan);save('after-drafts.json',after)
    old=before['drafts'];request('/api/frame-drafts',dict(scan_id=scan,index_sha256=context['index_sha256'],state_sha256=old['state_sha256'],label='Must reject stale state',draft=complete),400)
    check=subprocess.run([args.node,'tests/check_frame_drafts_http.cjs',f'http://127.0.0.1:{args.port}',scan,','.join(snapshots),str(out/'controller.json')],cwd=root,capture_output=True,text=True,encoding='utf-8',check=True);controller=json.loads(check.stdout)
    review=None;job=None;surfaces=[]
    if args.run_fusion:
        if (out/'review.json').exists():review=read('review.json')
        else:
            body=dict(scan_id=scan,index_sha256=context['index_sha256'],alignment_id=alignment['id'],alignment_sha256=alignment['sha256'],candidate=candidate,mode='frame_id',source_frames=complete['source_frames'],target_frames=complete['target_frames'],source_basis=complete['source_basis'],target_basis=complete['target_basis'],decision=complete['decision'],coordinate_confirmed=True,roi=preset['roi'],fusion_parameters=settings)
            review=request('/api/fragments/reviews',body,201);save('review.json',review)
        if review['fusion_parameters']!=settings:raise ValueError('Review ignored requested settings')
        if (out/'job.json').exists():job=read('job.json')
        else:job=request('/api/jobs',dict(kind='fragment_fusion',review_id=review['id'],plan_sha256=review['plan_sha256'],review_sha256=review['review_sha256']),202);save('job.json',job)
        while True:
            job=request('/api/jobs/'+job['id']);save('job-progress.json',job)
            if job['status'] not in ['queued','running']:break
            print(json.dumps(dict(job=job['id'],status=job['status'])),flush=True);time.sleep(5)
        if job['status']!='completed':raise ValueError('Fusion job did not complete: '+str(job.get('error')))
        pair=json.loads((mapper.resolve(job['folder'])/'result/summary.json').read_text(encoding='utf-8'))
        if pair['fusion_parameters']!=settings or pair['selected_frames']!=114 or pair['selected_depth_with_frame_ids_sha256']!='5c899c637d54df68f358d9bcdb597689ce32b97a08f0d2031de2cd8a8e621736':raise ValueError('Reviewed settings or original ROI pixels differ from the frozen component')
        save('fusion-pair.json',pair)
        catalog=request('/api/catalog?refresh=1')
        for i,row in enumerate(pair['results']):
            if row['fusion_parameters']!=settings:raise ValueError('An arm ignored reviewed parameters')
            model=next(m for m in catalog['models'] if mapper.resolve(m['path'])==mapper.resolve(row['path']));payload=request('/api/cloud?id='+model['id']+'&budget=40000&sha256='+file_sha256(mapper.resolve(row['path'])));save(f'cloud-{i}.json',payload)
            rgba=out/f'cloud-{i}.rgba';p=subprocess.run([args.node,'tests/check_point_viewer_cpu.cjs',str(out/f'cloud-{i}.json'),str(rgba),'depth'],cwd=root,capture_output=True,text=True,encoding='utf-8',check=True);raster=json.loads(p.stdout)['actual_http_payload'];Image.frombytes('RGBA',(800,600),rgba.read_bytes()).convert('RGB').save(out/f'cpu-{i}.png');surfaces.append(dict(points=model['points'],model_sha256=payload['sourceSha256'],cpu_raster=raster))
    history=request('/api/history?scan='+scan)
    if history['state_sha256']!=before['history']['state_sha256']:raise ValueError('Existing active model versions changed')
    result=dict(checked_at_utc=datetime.now(timezone.utc).isoformat(),scan_id=scan,draft_ids=snapshots,draft_state_sha256=after['state_sha256'],draft_count=len(after['drafts']),controller=controller,review_id=review['id'] if review else None,job_id=job['id'] if job else None,fusion_parameters=settings if job else None,surfaces=surfaces,model_history_unchanged=True,model_history_sha256=history['state_sha256'],scope='114 of 336 saved records; all selected enter fusion; other 222 excluded; no new physical accuracy or whole failed-scan repair claim',code_sha256={name:file_sha256(root/name) for name in ['src/reconstruction_probe/frame_drafts.py','src/reconstruction_probe/fusion_settings.py','src/reconstruction_probe/web_fragments.py','src/reconstruction_probe/fragment_plan.py','src/reconstruction_probe/web_studio.py','web/studio/fragment_editor.js','web/studio/index.html','scripts/reconstruct_fragment_plan.py','scripts/run_fragment_fusion_pair.py','scripts/check_frame_drafts_live.py','tests/check_frame_drafts_http.cjs']})
    save('summary.json',result);print(json.dumps({k:result[k] for k in ['draft_count','review_id','job_id','fusion_parameters','model_history_unchanged']}))


if __name__=='__main__':main()

"""Replay reversible project snapshots through real local HTTP APIs.

Uses existing completed fusion outputs. This does not rerun fusion, certify
physical accuracy, operate a browser, or pretend the review was human.
"""

import argparse
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image,ImageDraw,ImageFont

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8877);parser.add_argument('--out',required=True)
    parser.add_argument('--job-id',default='465fdb3b59b740b2');parser.add_argument('--node',default=shutil.which('node'));args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(args.out)
    if out.exists() or root/'reports' not in out.parents:parser.error('Use a new folder strictly inside workspace/reports')
    if not args.node:parser.error('Supply --node with an installed Node executable')
    out.mkdir(parents=True)
    def save(name,value):(out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    def request(path,body=None,expected=200):
        c=http.client.HTTPConnection('127.0.0.1',args.port,timeout=120)
        c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body).encode(),{} if body is None else {'Content-Type':'application/json'})
        response=c.getresponse();data=response.read();status=response.status;c.close()
        if status!=expected:raise ValueError((path,status,data[:1200].decode('utf-8','replace')))
        return json.loads(data)
    job=request('/api/jobs/'+args.job_id)
    if job['status']!='completed' or job['kind']!='fragment_fusion':raise ValueError('Need an existing completed paired fusion job')
    scan=job['scan_id'];catalog=request('/api/catalog');models=catalog['models'];folder=mapper.resolve(job['folder'])
    pair=json.loads((folder/'result/summary.json').read_text(encoding='utf-8'));index_path=root/'reports/range2-study-20261018/decoded'/scan/'index.json'
    candidates=[m for m in models if m['scan_id']==scan];baseline=next(m for m in candidates if m['role']=='baseline')
    arms=[next(m for m in candidates if mapper.resolve(m['path'])==mapper.resolve(r['path'])) for r in pair['results']]
    payloads=[request('/api/cloud?id='+m['id']+'&budget=10000') for m in [baseline,*arms]]
    snapshot=lambda rows:[dict(id=m['id'],sha256=p['sourceSha256']) for m,p in rows]
    sources={m['path']:p['sourceSha256'] for m,p in zip([baseline,*arms],payloads)}
    before=request('/api/history?scan='+scan);save('before.json',before)
    if before['active_version'] and not before['active_version']['available']:raise ValueError('Existing active version is unavailable; retain it and inspect its source files before replaying')
    current=before;versions={};events=[]
    def change(action,**extra):
        nonlocal current
        body=dict(scan_id=scan,index_sha256=current['index_sha256'],state_sha256=current['state_sha256'],action=action,**extra)
        result=request('/api/history',body);events.append(dict(action=action,from_version=current['active'],to_version=result['active']));current=result
        if not current['active_version']['available']:raise ValueError('New active version not loadable')
        return result
    decision='Automated HTTP version-history replay of existing outputs. No human correspondence approval, new reconstruction, or independent accuracy claim.'
    for key,label,rows in [('baseline','接口验证 · 原工程融合起点',[(baseline,payloads[0])]),
        ('saved','接口验证 · 114帧原位姿控制',[(arms[0],payloads[1])]),('corrected','接口验证 · 114帧校正候选',[(arms[1],payloads[2])])]:
        state=change('save',models=snapshot(rows),label=label,decision=decision);versions[key]=state['active']
        if key!='baseline':
            origin=state['active_version']['provenance'][0]
            if origin.get('job_id')!=args.job_id or origin['saved_control']!=(key=='saved'):raise ValueError('Fusion arm provenance was not retained')
    change('undo')
    if current['active']!=versions['saved']:raise ValueError('Undo did not restore the saved-pose version')
    change('redo')
    if current['active']!=versions['corrected']:raise ValueError('Redo did not restore the corrected version')
    change('undo');state=change('save',models=snapshot(list(zip(arms,payloads[1:]))),label='接口验证 · 两组同帧叠加分支',decision=decision)
    versions['comparison_branch']=state['active']
    if state['active_version']['parent_id']!=versions['saved'] or state['can_redo']:raise ValueError('Alternative branch did not clear redo or retain parent')
    if versions['corrected'] not in {v['id'] for v in state['versions']}:raise ValueError('Earlier branch was lost')
    stale=dict(scan_id=scan,index_sha256=before['index_sha256'],state_sha256=before['state_sha256'],action='restore',version_id=versions['baseline'])
    request('/api/history',stale,400)
    request('/api/cloud?id='+arms[0]['id']+'&budget=10000&sha256='+'0'*64,expected=400)
    rasters=[];cache=root/'.cache';cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='history-render-',dir=cache) as temp:
        temp=Path(temp)
        for i,row in enumerate(current['active_version']['models']):
            payload=request('/api/cloud?id='+row['id']+'&budget=10000&sha256='+row['sha256'])
            if payload['sourceSha256']!=row['sha256']:raise ValueError('Restored geometry reply differs from the version')
            fixture=temp/f'{i}.json';fixture.write_text(json.dumps(payload),encoding='utf-8');rgba=temp/f'{i}.rgba'
            r=subprocess.run([args.node,'tests/check_point_viewer_cpu.cjs',str(fixture),str(rgba),'depth'],cwd=root,capture_output=True,text=True,encoding='utf-8',check=True)
            raster=json.loads(r.stdout)['actual_http_payload'];rasters.append(raster)
            Image.frombytes('RGBA',(800,600),rgba.read_bytes()).convert('RGB').save(out/f'cpu-{i}.png')
    # Return to the user's previous active version, or this scan's baseline if none existed.
    destination=before['active'] or versions['baseline'];change('restore',version_id=destination)
    after=request('/api/history?scan='+scan)
    if after['active']!=destination:raise ValueError('Previous project selection was not restored')
    for path,sha in sources.items():
        if file_sha256(mapper.resolve(path))!=sha:raise ValueError('Source model changed during history verification')
    save('after.json',after);save('events.json',events)
    picture=Image.new('RGB',(1200,660),(12,20,32));draw=ImageDraw.Draw(picture);font=lambda size:ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',size)
    draw.text((18,14),'工程版本：登记 → 撤销 → 重做 → 保留分支 → 返回起点',font=font(23),fill='#dcebf5')
    draw.text((18,52),f"真实HTTP接口与固定SHA恢复；下图为共享查看器CPU像素，非浏览器截图。复用已有{pair['selected_frames']}帧结果。",font=font(15),fill='#a9c4d5')
    for i,label in enumerate([f"原位姿控制 · {arms[0]['points']:,}点",f"片段校正候选 · {arms[1]['points']:,}点"]):
        image=Image.open(out/f'cpu-{i}.png').resize((580,435));picture.paste(image,(10+600*i,150));draw.text((18+600*i,108),label,font=font(21),fill='#9fdfd2')
    draw.text((18,610),'版本切换保留原扫描、原位姿和输出；局部候选未自动升级为几何正确的主模型。',font=font(16),fill='#a9c4d5');picture.save(out/'verification.png')
    summary=dict(status='actual_http_project_history_replay_completed',scan_id=scan,existing_fusion_job=args.job_id,
        new_version_ids=versions,operations=events,restored_initial_active_or_baseline=destination,
        stale_state_rejected=True,wrong_model_sha_rejected=True,old_branch_retained=True,redo_cleared_on_new_branch=True,
        original_model_sha256=sources,actual_shared_viewer_cpu_rasters=rasters,new_fusion_run=False,actual_browser_verified=False,
        implementation_sha256={name:file_sha256(root/name) for name in ['src/reconstruction_probe/project_history.py','src/reconstruction_probe/web_studio.py','web/studio/project_history.js','web/studio/app.js','web/studio/index.html','scripts/check_project_history_live.py']},
        limitations=['This is automated HTTP state-transition replay, not human use of the browser or approval of geometric accuracy.',
            'History restores exact model selection and provenance references, not mutable algorithm state or deleted raw frames.',
            'Per-snapshot reference hashes are verified; browsing history does not re-decode every raw payload referenced by an old fusion plan.',
            'No scanner connection, language-model agent, new whole-scan repair or calibrated physical accuracy is demonstrated.'])
    save('summary.json',summary)
    print(json.dumps(dict(status=summary['status'],versions=len(versions),operations=len(events),restored=destination,cpu_pixels=[r['visible_pixels'] for r in rasters])),flush=True)


if __name__=='__main__':main()

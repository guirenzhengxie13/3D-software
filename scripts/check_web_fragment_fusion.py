"""Exercise the Web form's actual context -> review -> two-arm fusion APIs.

Uses a recorded real binding and a frozen existing candidate, as an automated
research replay. It is not a claim of human UI operation or browser validation.
"""

import argparse
import hashlib
import http.client
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image,ImageDraw,ImageFont
from scipy.spatial import cKDTree

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.ply_layout import map_ply_vertices


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def xyz(path):
    rows,_=map_ply_vertices(path)
    return np.column_stack([rows[key] for key in ['x','y','z']]).astype(float)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8877)
    parser.add_argument('--out',required=True);parser.add_argument('--node',default=shutil.which('node'));args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(args.out)
    if out.exists() or root/'reports' not in out.parents:parser.error('Use a new directory strictly within workspace/reports')
    if not args.node:parser.error('Supply --node with a Node executable')
    out.mkdir(parents=True)
    def request(path,body=None,expected=200):
        c=http.client.HTTPConnection('127.0.0.1',args.port,timeout=120)
        c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body).encode(),{} if body is None else {'Content-Type':'application/json'})
        response=c.getresponse();payload=response.read();status=response.status;c.close()
        if status!=expected:raise ValueError((path,status,payload[:1000].decode('utf-8','replace')))
        return json.loads(payload)
    context=request('/api/fragments/context?scan=scan_20261018131222')
    alignment=next(a for a in context['alignments'] if 'selected_frozen_training_1_to_0' in a['candidates'])
    preset=next(p for p in context['presets'] if alignment['id'] in p['alignment_ids'])
    form=dict(scan_id=context['scan_id'],index_sha256=context['index_sha256'],alignment_id=alignment['id'],alignment_sha256=alignment['sha256'],
        candidate='selected_frozen_training_1_to_0',mode='frame_id',source_frames=preset['source_text'],target_frames=preset['target_text'],
        source_basis=preset['source_basis'],target_basis=preset['target_basis'],coordinate_confirmed=True,roi=preset['roi'],
        preset_id=preset['id'],preset_sha256=preset['sha256'],
        decision='Automated Web API replay of recorded ownership and a frozen existing transform. Not human point selection, not whole-scan repair or independent accuracy evidence.')
    save(out/'form.json',form)
    review=request('/api/fragments/reviews',form,201);save(out/'review.json',review)
    if review['summary']['selected_frames']!=114:raise ValueError('Expected the frozen 114-frame local component')
    execution=dict(kind='fragment_fusion',review_id=review['id'],plan_sha256=review['plan_sha256'],review_sha256=review['review_sha256'])
    bad={**execution,'plan_sha256':'0'*64};request('/api/jobs',bad,400)
    job=request('/api/jobs',execution,202);save(out/'submitted-job.json',job)
    last=None;deadline=time.monotonic()+600
    while job['status'] in ['queued','running']:
        if time.monotonic()>deadline:raise TimeoutError('Retain running job '+job['id']+' and inspect its status before retrying')
        key=(job['status'],tuple((n['id'],n['status']) for n in job.get('workflow',{}).get('nodes',[])))
        if key!=last:print(json.dumps(dict(job_id=job['id'],status=job['status'],operations=key[1])),flush=True);last=key
        time.sleep(1);job=request('/api/jobs/'+job['id'])
    save(out/'completed-job.json',job)
    if job['status']!='completed':raise ValueError('Web fusion did not complete: '+job.get('error',job['status']))
    result_folder=mapper.resolve(job['folder'])/'result';result=read(result_folder/'summary.json')
    frozen=read(root/'reports/range2-study-20261018/experiments/cup-first-segment-component/summary.json')['results']
    if result['selected_depth_with_frame_ids_sha256']!=frozen[0]['selected_depth_with_frame_ids_sha256']:
        raise ValueError('Web execution used different original pixels from the frozen control')
    comparisons=[]
    for current,previous in zip(result['results'],frozen):
        a=xyz(Path(current['path']));b=xyz(mapper.resolve(previous['path']))
        maximum=float(max(cKDTree(b).query(a,workers=1)[0].max(),cKDTree(a).query(b,workers=1)[0].max()))
        comparisons.append(dict(points=len(a),previous_points=len(b),full_bidirectional_max_distance_mm=maximum))
    if any(c['full_bidirectional_max_distance_mm']>.001 for c in comparisons):raise ValueError('Web fusion differs from the frozen reconstruction')
    page=(result_folder/'review.html').read_text(encoding='utf-8')
    payload=json.loads(re.search(r'<script id="comparison-data" type="application/json">(.*?)</script>',page,re.S)[1])
    rasters=[];cache=root/'.cache';cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='web-fragment-render-',dir=cache) as temp:
        temp=Path(temp)
        for i,row in enumerate(payload['clouds']):
            fixture=temp/f'{i}.json';rgba=temp/f'{i}.rgba';save(fixture,row)
            command=[args.node,'tests/check_point_viewer_cpu.cjs',str(fixture),str(rgba),'depth']
            checked=subprocess.run(command,cwd=root,capture_output=True,text=True,encoding='utf-8',check=True)
            control=json.loads(checked.stdout)['actual_http_payload'];rasters.append(control)
            Image.frombytes('RGBA',(800,600),rgba.read_bytes()).convert('RGB').save(out/f'cpu-{i}.png')
    picture=Image.new('RGB',(1200,600),(12,20,32));draw=ImageDraw.Draw(picture)
    font=lambda size:ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',size)
    draw.text((18,12),'Web帧归属 → 实际核验 → 两组重融合',font=font(25),fill='#dfedf8')
    draw.text((18,51),'真实HTTP接口自动回放；同一114帧、同一原像素。下方为实际查看器CPU像素，非浏览器截图。',font=font(15),fill='#9bb9ce')
    for i,row in enumerate(payload['clouds']):
        draw.text((i*600+15,92),row['label']+f" · {row['originalPoints']:,} 点",font=font(19),fill='#9bd8bf')
        with Image.open(out/f'cpu-{i}.png') as image:picture.paste(image.resize((580,435)),(i*600+10,127))
    picture.save(out/'comparison.png')
    summary=dict(status='actual_web_frame_binding_and_fusion_completed',scan_id=context['scan_id'],job_id=job['id'],review_id=review['id'],
        method='real HTTP APIs used by the form, automated existing-candidate replay, not human UI operation',
        selected_frames=114,source_frames=review['summary']['source_frames'],target_frames=review['summary']['target_frames'],
        pinned_files=review['summary']['pinned_files'],selected_depth_with_frame_ids_sha256=result['selected_depth_with_frame_ids_sha256'],
        stale_plan_request_rejected_before_execution=True,comparisons=comparisons,actual_shared_viewer_cpu_rasters=rasters,
        report_url=job['report'],workflow_report_url=job['workflow_report'],actual_browser_verified=False,actual_gpu_verified=False,
        source_files_not_overwritten=True,implementation_sha256={name:file_sha256(root/name) for name in [
            'src/reconstruction_probe/web_fragments.py','src/reconstruction_probe/web_studio.py','scripts/run_fragment_fusion_pair.py',
            'web/studio/fragment_editor.js','web/studio/app.js','web/studio/index.html']},
        limitations=['This extends the interface and execution workflow; exact reproduction is not new physical accuracy evidence.',
            'Only the prior 114-frame component is exercised. The rest of the failed scan remains unresolved.',
            'Browser interaction is separately tested by the real controller with a simulated DOM; no new Chrome/GPU claim.'])
    save(out/'summary.json',summary);print(json.dumps({key:summary[key] for key in ['status','job_id','selected_frames','comparisons','report_url']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()

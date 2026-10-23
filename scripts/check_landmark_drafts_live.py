"""Verify incomplete drafts against real HTTP-served workbench data.

Selections are automated API fixtures, not human physical correspondences.
No solver, alignment job or fusion is invoked. Original page bytes stay pinned.
"""

import argparse
import base64
from datetime import datetime,timezone
import http.client
import json
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np
from PIL import Image,ImageDraw,ImageFont

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8877);parser.add_argument('--out',required=True);parser.add_argument('--node',default=shutil.which('node'));parser.add_argument('--resume',action='store_true',help='Finish an existing recorded replay without creating more snapshots');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(args.out)
    if root/'reports' not in out.parents or (out.exists() and not args.resume) or (args.resume and not all((out/name).is_file() for name in ['before.json','after.json','restored-draft.json','served-workbench.html'])):parser.error('Use a new report folder, or --resume an existing recorded replay')
    if not args.node:parser.error('Supply --node')
    out.mkdir(parents=True,exist_ok=args.resume)
    def save(name,data):(out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    def request(path,body=None,expected=200,text=False):
        c=http.client.HTTPConnection('127.0.0.1',args.port,timeout=120);c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body).encode(),{} if body is None else {'Content-Type':'application/json'})
        r=c.getresponse();raw=r.read();status=r.status;c.close()
        if status!=expected:raise ValueError((status,path,raw[:1200]))
        return raw.decode('utf-8') if text else json.loads(raw)
    catalog=request('/api/catalog');jobs_before=request('/api/jobs');history_before=request('/api/history?scan=scan_20261018131222')
    item=next(w for w in catalog['workbenches'] if '/fragment-bridge-20261021/verified/workbench.html' in w['url'])
    page=mapper.resolve(item['url'].lstrip('/'));original_page_sha=file_sha256(page);served=request(item['url'],text=True);(out/'served-workbench.html').write_text(served,encoding='utf-8',newline='\n')
    match=re.search(r'<script id="alignment-data" type="application/json">(.*?)</script>',served,re.S);data=json.loads(match[1]);server=data['serverContext']
    if server['page_sha256']!=original_page_sha or server['workbench_id']!=item['id']:raise ValueError('Served context differs from pinned original page')
    pins={str(page):original_page_sha}
    for row in [*data['clouds'],data['candidateReference']]:
        path=mapper.resolve(row['path']);sha=row.get('sourceSha256',row.get('sha256'))
        if file_sha256(path)!=sha:raise ValueError('Source pin differs')
        pins[str(path)]=sha
    context=request('/api/landmark-drafts?workbench='+item['id'])
    if not args.resume:save('before.json',context)
    candidate=data['candidates'][0]
    draft=dict(format='reconstruction-landmark-draft',format_version=1,unit='mm',source=dict(sha256=data['clouds'][1]['sourceSha256'],fragment_id=data['clouds'][1].get('fragmentId',1)),target=dict(sha256=data['clouds'][0]['sourceSha256'],fragment_id=data['clouds'][0].get('fragmentId',0)),candidate_label=candidate['label'],candidate_sha256=data['candidateReference']['sha256'],requires_recompute=True,point_pairs=[],pending_target=None)
    snapshots=[]
    def store(label):
        nonlocal context
        body=dict(workbench_id=item['id'],page_sha256=server['page_sha256'],state_sha256=context['state_sha256'],label=label,draft=draft)
        context=request('/api/landmark-drafts',body,201);snapshots.append(context['saved_id']);return body
    if not args.resume:stale=store('接口验证 · 未开始的选点草稿')
    def vertex(index,row):
        cloud=data['clouds'][index];ids=np.frombuffer(base64.b64decode(cloud['ids']),'<u4');xyz=np.frombuffer(base64.b64decode(cloud['xyz']),'<f4').reshape(-1,3)
        return dict(id=int(ids[row]),xyz=xyz[row].astype(float).tolist())
    # Arbitrary IDs exercise persistence only. They are deliberately NOT evidence of the same physical location.
    draft['point_pairs']=[dict(target=vertex(0,0),source=vertex(1,0))];draft['pending_target']=vertex(0,1)
    if not args.resume:
        store('接口验证 · 1对与待配对点（非人工对应）');request('/api/landmark-drafts',stale,400)
    else:
        previous=json.loads((out/'before.json').read_text(encoding='utf-8'));after=json.loads((out/'after.json').read_text(encoding='utf-8'))
        if after['state_sha256']!=context['state_sha256']:raise ValueError('Saved draft state changed; inspect before resuming')
        snapshots=[r['id'] for r in reversed(after['drafts']) if r['id'] not in {v['id'] for v in previous['drafts']}]
        if len(snapshots)!=2:raise ValueError('Expected exactly two recorded replay snapshots')
    restore=request('/api/landmark-drafts?workbench='+item['id']+'&draft_id='+snapshots[-1]+'&page_sha256='+server['page_sha256'])
    if restore['draft']!=draft:raise ValueError('HTTP draft content did not round trip')
    
    if not args.resume:save('after.json',context);save('restored-draft.json',dict(id=snapshots[-1],draft=draft))
    check=subprocess.run([args.node,'tests/check_landmark_drafts_http.cjs',str(out/'served-workbench.html'),str(out/'restored-draft.json'),f'http://127.0.0.1:{args.port}'],cwd=root,capture_output=True,text=True,encoding='utf-8',check=True)
    controller=json.loads(check.stdout);save('controller.json',controller)
    # Use the actual shared PointViewer CPU raster over the actual served point arrays.
    rasters=[]
    for index,cloud in enumerate(data['clouds']):
        payload={**cloud,'unit':'mm'};fixture=out/f'cloud-{index}.json';save(fixture.name,payload);rgba=out/f'cloud-{index}.rgba'
        result=subprocess.run([args.node,'tests/check_point_viewer_cpu.cjs',str(fixture),str(rgba),'depth'],cwd=root,capture_output=True,text=True,encoding='utf-8',check=True)
        raster=json.loads(result.stdout)['actual_http_payload'];rasters.append(raster);Image.frombytes('RGBA',(800,600),rgba.read_bytes()).convert('RGB').save(out/f'cpu-{index}.png')
    picture=Image.new('RGB',(1240,700),(12,20,32));draw=ImageDraw.Draw(picture);font=lambda size:ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',size)
    draw.text((18,12),'对应点草稿：未完成也能保存和恢复',font=font(24),fill='#dcebf5')
    draw.text((18,53),'真实HTTP保存0对、1对与待配对点；所选ID为接口测试，并非人工确认的物理对应。',font=font(17),fill='#d3bf8e')
    for i,name in enumerate(['固定片段','移动片段']):
        image=Image.open(out/f'cpu-{i}.png').resize((590,443));picture.paste(image,(18+i*620,100));draw.text((18+i*620,550),f"{name}：{data['clouds'][i]['displayPoints']:,} 个显示原顶点",font=font(18),fill='#dcebf5')
    draw.text((18,594),'保存后重读原ID与待配对点一致；恢复手动草稿后仍需重新计算。没有运行配准或融合。',font=font(17),fill='#adc7d8')
    draw.text((18,630),'图像来自实际PointViewer CPU光栅；控制器使用模拟DOM，不是Chrome/GPU截图。',font=font(16),fill='#adc7d8');picture.save(out/'verification.png')
    for path,sha in pins.items():
        if file_sha256(Path(path))!=sha:raise ValueError('Original input changed')
    jobs_after=request('/api/jobs');history_after=request('/api/history?scan=scan_20261018131222')
    if jobs_before!=jobs_after or history_before['state_sha256']!=history_after['state_sha256']:raise ValueError('Unrelated jobs or model versions changed')
    code=['src/reconstruction_probe/landmark_drafts.py','src/reconstruction_probe/project_history.py','src/reconstruction_probe/web_studio.py','web/landmark-workbench/app.js','web/landmark-workbench/index.html','scripts/check_landmark_drafts_live.py','tests/check_landmark_drafts_http.cjs']
    summary=dict(checked_at_utc=datetime.now(timezone.utc).isoformat(),workbench_id=item['id'],workbench_url=item['url'],scan_id='scan_20261018131222',new_draft_ids=snapshots,previous_drafts=len(context['drafts'])-2,after_drafts=len(context['drafts']),draft_state_sha256=context['state_sha256'],source_inputs_unchanged=True,input_sha256=pins,code_sha256={name:file_sha256(root/name) for name in code},jobs_unchanged=True,model_history_unchanged=True,model_history_sha256=history_after['state_sha256'],served_page_sha256=file_sha256(out/'served-workbench.html'),controller=controller,cpu_rasters=rasters,limits=['Automated arbitrary original IDs are persistence fixtures, not physical corresponding points.','No solver, alignment or fusion invoked; no new geometry improvement claimed.','Actual HTTP plus simulated DOM and shared CPU pixels; no new Chrome/GPU observation.'])
    save('summary.json',summary);print(json.dumps({k:summary[k] for k in ['workbench_id','new_draft_ids','after_drafts','jobs_unchanged','model_history_unchanged','source_inputs_unchanged']}))


if __name__=='__main__':main()

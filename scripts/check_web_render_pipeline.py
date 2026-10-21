"""Feed actual local HTTP responses into the real viewer and CPU rasterizer.

This deliberately connects the contract the old separate HTTP and mocked UI
checks failed to connect. It is still not an actual browser/GPU verification.
"""
import argparse
import http.client
import json
from pathlib import Path
import subprocess
import tempfile

from PIL import Image,ImageDraw,ImageFont


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8877);parser.add_argument('--node',default='C:/Program Files/nodejs/node.exe');parser.add_argument('--out',type=Path,help='New report folder within workspace/reports');args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    def get(path):
        c=http.client.HTTPConnection('127.0.0.1',args.port,timeout=90);c.request('GET',path);r=c.getresponse();body=r.read();c.close()
        if r.status!=200:raise ValueError(str((r.status,body[:500])))
        return json.loads(body)
    catalog=get('/api/catalog');models=catalog['models'];default=catalog['default_scan'];cases=[]
    for label,predicate in [
        ('精细人偶',lambda m:m['scan_id']==default and 'tensor-tsdf' in m['path']),
        ('官方融合',lambda m:m['scan_id']==default and m['role']=='official'),
        ('主融合基线',lambda m:m['scan_id']==default and m['role']=='baseline'),
        ('扫描原预览',lambda m:m['scan_id']==default and m['role']=='preview'),
        ('两工程联合融合',lambda m:'cup-multi-scan-tsdf' in m['path'] and 'joint_raw_depth' in m['path']),
        ('失败扫描片段',lambda m:'segment-2-training-mm.ply' in m['path'])]:
        model=next(m for m in models if predicate(m));cases.append((label,'/api/cloud?id='+model['id']))
    cases.extend([('彩色原帧','/api/frame?scan=scan_20261018122607&ordinal=0'),('失败杯子原帧','/api/frame?scan=scan_20261018131359&ordinal=0')])
    out=(root/'reports/web-studio/render-fix-20261020') if args.out is None else args.out.resolve()
    if root/'reports' not in out.parents or (args.out is not None and out.exists()):raise ValueError('Use a new report directory strictly within workspace/reports')
    out.mkdir(parents=True,exist_ok=True);cache=root/'.cache';cache.mkdir(exist_ok=True);rows=[]
    with tempfile.TemporaryDirectory(prefix='actual-render-payload-',dir=cache) as temporary:
        temporary=Path(temporary).resolve()
        if cache.resolve() not in temporary.parents:raise ValueError('Unexpected temporary directory')
        for i,(label,url) in enumerate(cases):
            payload=get(url);input_path=temporary/f'{i}.json';raw_path=temporary/f'{i}.rgba';input_path.write_text(json.dumps(payload),encoding='utf-8')
            result=subprocess.run([args.node,'tests/check_point_viewer_cpu.cjs',str(input_path),str(raw_path)],cwd=root,capture_output=True,text=True,encoding='utf-8')
            if result.returncode:raise RuntimeError(result.stdout+result.stderr)
            control=json.loads(result.stdout);image=Image.frombytes('RGBA',(800,600),raw_path.read_bytes()).convert('RGB');image.save(out/f'case-{i}.png')
            rows.append(dict(label=label,url=url,original_points=payload.get('originalPoints'),control=control,image=f'case-{i}.png'))
    font=lambda n:ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',n);contact=Image.new('RGB',(1280,4*535+100),(12,20,32));draw=ImageDraw.Draw(contact)
    draw.text((18,10),'真实 HTTP → 实际 PointViewer → CPU 深度像素',font=font(25),fill='#e3edf6');draw.text((18,49),'修复点数字段遮蔽坐标数组；以下不是 Chrome 截图，GPU 仍单独待验。',font=font(17),fill='#9ab6ca')
    for i,row in enumerate(rows):
        x=(i%2)*640;y=(i//2)*535+95;draw.text((x+15,y),f"{row['label']} · {row['control']['actual_http_payload']['display_points']:,} 点",font=font(20),fill='#bfe6d7')
        image=Image.open(out/row['image']).resize((620,465));contact.paste(image,(x+10,y+37))
    contact.save(out/'contact.png');summary=dict(cases=rows,all_actual_payloads_reach_nonempty_pixels=True,scalar_count_collision_regression=True,actual_browser_verified=False,actual_gpu_verified=False)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(dict(cases=len(rows),actual_http_to_real_viewer_to_pixels=True,report=str(out/'summary.json'),actual_browser_verified=False)),flush=True)


if __name__=='__main__':main()

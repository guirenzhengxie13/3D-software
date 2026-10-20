"""Local web application over the existing read-only scan/reconstruction corpus.

Only catalogued models and fixed processing entry points are exposed. Capture
files are never served as a directory, and processing outputs get new folders.
"""

from collections import OrderedDict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import hashlib
import io
import json
import mimetypes
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
from urllib.parse import parse_qs, unquote, urlsplit
import uuid

import numpy as np

from .lod_cache import load_lod_cache, record_rgb
from .offline import file_sha256
from .ply_layout import inspect_ply, map_ply_vertices
from .ply_spatial_index import PlySpatialIndex
from .spatial_lod import budgeted_spatial_preview


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def pack(xyz, rgb, ids):
    return dict(xyz=base64.b64encode(np.asarray(xyz, '<f4').tobytes()).decode(),
                rgb=base64.b64encode(np.asarray(rgb, np.uint8).tobytes()).decode(),
                ids=base64.b64encode(np.asarray(ids, '<u4').tobytes()).decode(), displayPoints=len(xyz))


LABELS = {
    'tensor-tsdf':'精细稀疏融合', 'tensor-weight3':'稀疏融合 · 权重门槛',
    'cup-roi':'杯子选区后重新融合', 'cup-direct-split':'直接对齐两片段',
    'cup-first-segment-component':'失败扫描 · 首个片段组件',
    'cup-multi-scan-tsdf':'两份扫描原始深度联合融合',
    'cup-piecewise-pose':'分段位姿校正', 'cup-piecewise-crosscheck':'同像素交叉检查',
    'cup-segment-pose-graph':'失败扫描分段与连接', 'cup-segment-color-edges':'颜色辅助片段连接',
    'cup-segment-edge-holdout':'片段连接留出检查', 'marker-recovery':'标记点位姿修正',
    'fixed-axis-depth-prior':'固定转轴约束尝试', 'depth-sequence-consistency':'相邻帧深度检查',
    'cup-depth-repeatability':'原深度重复观测检查', 'cup-complementarity':'扫描互补区域',
    'cup-visibility':'支持、冲突与遮挡', 'cup-registration':'跨扫描配准',
    'cup-id-groups':'保存帧分组', 'cup-id-registration':'分组配准',
    'official-fusion-comparison':'官方融合与自研结果', 'comparison':'原扫描预览与自研结果',
}
EXPERIMENT_STATUS={
    'official-fusion-comparison':'已完成同源表面对比；官方输出也不等于物理真值',
    'cup-direct-split':'358帧融合演示减少重复杯柄；孔洞和碎片仍保留',
    'cup-multi-scan-tsdf':'463帧真实联合融合；已回查互补区域和重复冲突',
    'cup-roi':'选区减少背景并重新融合；保存位姿保持不变',
    'tensor-tsdf':'按固定体素进行稀疏融合的精细候选',
    'marker-recovery':'未采用为主结果：标记残差改善未带来表面改善',
    'fixed-axis-depth-prior':'未采用：理想转轴约束增加了深度冲突',
    'cup-segment-pose-graph':'8个片段，7条相邻连接仅3条通过门槛',
    'cup-segment-color-edges':'颜色精修未救回全部连接，保留失败候选',
    'cup-first-segment-component':'114帧局部组件演示；尚不是完整失败扫描的修复',
}


class Studio:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self.study = self.root/'reports/range2-study-20261018'
        self.output = self.root/'reports/web-studio/runs'
        self.lock = threading.RLock()
        self.processing = threading.Semaphore(1)
        self.cache = OrderedDict()
        self.jobs = {}
        for record in self.output.glob('*/job.json'):
            job=read(record)
            if job.get('id')==record.parent.name and Path(job.get('folder','')).resolve()==record.parent.resolve():
                self.jobs[job['id']]=job
        self.refresh()

    def url(self, path):
        return '/' + Path(path).resolve().relative_to(self.root).as_posix()

    def refresh(self):
        projects=[]; indices={}; models={}; page_registry={}
        for decoded in [self.study/'decoded', self.root/'reports/four-scans/decoded']:
            for p in sorted(decoded.glob('*/index.json')):
                index=read(p); key=index['scan_id']; indices[key]=(p,index)
                short=key.replace('scan_','');label=f'{short[:4]}-{short[4:6]}-{short[6:8]} · {short[8:10]}:{short[10:12]}:{short[12:14]}' if re.fullmatch(r'\d{14}',short) else short
                projects.append(dict(id=key,label=label,frames=len(index['frames']),
                    observations=index['status']['valid_depth_points'],colored=index['status'].get('colored_depth_frames',0),
                    poses=index['status'].get('optimized_poses_parsed',index['status'].get('poses_parsed',0)),
                    cohort='Range 2 新批次' if decoded.parent==self.study else '早期四份工程'))
        def model(path, scan_id=None, label=None, role='candidate'):
            path=Path(path).resolve()
            if not path.is_file():return
            layout=inspect_ply(path)
            if not layout.vertex_count or layout.face_count:return
            identifier=hashlib.sha256(str(path).encode()).hexdigest()[:20]
            if identifier in models:return
            rel=path.relative_to(self.root).as_posix() if self.root in path.parents else path.name
            if label is None:
                if role=='baseline':label='自研主融合基线'
                elif 'experiments' in path.parts:
                    relative=list(path.parts[path.parts.index('experiments')+1:-1]);experiment=relative[0]
                    detail=[x for x in relative[1:] if x not in ['reconstruction','candidate'] and not x.startswith('scan_')]
                    label=LABELS.get(experiment,experiment)+(' · '+' / '.join(detail[-2:]) if detail else '')
                elif path.name.endswith('-aligned-mm.ply'):label='对应点核对后对齐 · '+path.stem.replace('-aligned-mm','')
            if scan_id is None:
                scan_id=next((part for part in path.parts if part in indices),None)
                if scan_id is None:
                    if 'cup-direct-split' in path.parts:scan_id='scan_20261018131359'
                    elif any(s in path.parts for s in ['cup-segment-pose-graph','cup-first-segment-component']):scan_id='scan_20261018131222'
            models[identifier]=dict(id=identifier,path=str(path),scan_id=scan_id,
                label=label or rel.replace('reports/range2-study-20261018/','').replace('/tsdf_pointcloud_mm.ply',''),
                points=layout.vertex_count,bytes=path.stat().st_size,role=role,unit='mm')
        for base in [self.study,self.root/'reports/four-scans',self.root/'reports/web-studio/runs']:
            for p in sorted(base.rglob('*.ply')):
                if p.name=='tsdf_pointcloud_mm.ply' or re.fullmatch(r'segment-\d+-training-mm.ply',p.name) or p.name.endswith('-aligned-mm.ply'):
                    model(p,role='baseline' if p.parent.parent==base/'reconstruction' else 'candidate')
        for key,(p,index) in indices.items():
            source=Path(index['source_directory'])
            model(source/'pointclouds/fuse.ply',key,'官方保存融合','official')
            model(source/'raw_preview.ply',key,'官方扫描预览','preview')
        official_report=self.study/'official-fusion-comparison/summary.json'
        if official_report.is_file():
            for pair in read(official_report).get('pairs',[]):
                key=pair.get('scan_id')
                if key not in indices or pair.get('metadata',{}).get('referenceKind')!='saved-fusion':continue
                source=(Path(indices[key][1]['source_directory'])/'pointclouds').resolve()
                for name in pair.get('source_sha256',{}):
                    path=Path(name).resolve()
                    if source in path.parents:model(path,key,'官方保存融合','official')
        experiments=[]; workbenches=[]
        for folder in [self.study/'official-fusion-comparison',self.study/'comparison',*sorted((self.study/'experiments').glob('*'))]:
            if not folder.is_dir():continue
            pages=sorted(folder.rglob('*.html'))
            images=[p for p in [folder/'comparison.png',folder/'evidence-comparison.png',folder/'directions.png'] if p.is_file()]
            if not images:images=sorted(folder.glob('*.png'))[:1]
            experiments.append(dict(id=folder.name,label=LABELS.get(folder.name,folder.name),
                pages=[dict(label=p.relative_to(folder).as_posix(),url=self.url(p)) for p in pages],
                image=self.url(images[0]) if images else None,
                record=self.url(folder/'README.md') if (folder/'README.md').is_file() else None,
                status=EXPERIMENT_STATUS.get(folder.name,'研究候选 / 对照，需结合证据审阅')))
            preferred=folder/'full-reconstruction/review.html' if folder.name=='cup-direct-split' else folder/'comparison.html' if folder.name in ['official-fusion-comparison','tensor-tsdf'] else folder/'review.html'
            if preferred.is_file():experiments[-1]['primary_url']=self.url(preferred)
        priority=['official-fusion-comparison','cup-direct-split','cup-multi-scan-tsdf','cup-roi','tensor-tsdf','cup-first-segment-component']
        experiments.sort(key=lambda row:(priority.index(row['id']) if row['id'] in priority else len(priority),row['id']))
        for base in [self.study,self.root/'reports/pointcloud-scale-20261019',self.output]:
            for p in sorted(base.rglob('*.html')):
                if 'workbench' not in p.name:continue
                text=p.read_text(encoding='utf-8'); match=re.search(r'<script id="alignment-data" type="application/json">(.*?)</script>',text,re.S)
                if not match:continue
                data=json.loads(match[1]); identifier=hashlib.sha256(str(p).encode()).hexdigest()[:16]
                item=dict(id=identifier,label=p.parent.name if p.name=='workbench.html' else p.stem,
                    url=self.url(p),models=[dict(path=c['path'],points=c['originalPoints']) for c in data['clouds']])
                workbenches.append(item);page_registry[identifier]=dict(path=p,data=data)
                for c in data['clouds']:model(Path(c['path']),label='对应点片段 · '+c['label'])
                item['scan_ids']=sorted({m['scan_id'] for m in models.values() if m['scan_id'] is not None and m['path'] in {str(Path(c['path']).resolve()) for c in data['clouds']}})
                if base==self.output:item['label']='自选模型对应点 · '+p.parent.parent.name[:8]
                elif re.fullmatch(r'segment-\d+-to-\d+',item['label']):
                    numbers=re.findall(r'\d+',item['label']);item['label']=f'失败杯子 · 片段 {numbers[0]} → {numbers[1]}'
                elif item['label']=='cached-workbench':item['label']='彩色人偶 · 官方与精细自研'
                elif item['label']=='landmark-workbench':item['label']='杯子 · 两个主要片段'
        catalog=dict(projects=projects,models=list(models.values()),experiments=experiments,workbenches=workbenches,
            reports=[dict(label='点云数量、内存与局部交互',url='/reports/pointcloud-scale-20261019/index.html'),
                     dict(label='当前成果与成功候选展示',url='/reports/web-studio/index.html'),
                     dict(label='新批扫描完整研究',url=self.url(self.study/'index.html')),
                     dict(label='真实五步证据工作流',url=self.url(self.study/'workflow-prototype-run/index.html')),
                     dict(label='真实三步空间工作流',url='/reports/pointcloud-scale-20261019/workflow-spatial-run/index.html'),
                     dict(label='早期四工程结果',url='/reports/four-scans/review.html')],
            summary=dict(frames=sum(p['frames'] for p in projects),observations=sum(p['observations'] for p in projects),
                         projects=len(projects),models=len(models)),
            default_scan='scan_20261018122607',unit='mm',model_service_connected=False)
        with self.lock:self.indices=indices;self.models=models;self.pages=page_registry;self.catalog=catalog
        return catalog

    def cloud(self, identifier, budget=40000):
        if identifier not in self.models:raise ValueError('模型不在当前目录清单中')
        if type(budget) is not int or not 100<=budget<=60000:raise ValueError('预览预算需要在100至60000点之间')
        meta=self.models[identifier];source=Path(meta['path']);stat=source.stat(); key=(str(source),stat.st_size,stat.st_mtime_ns,budget)
        with self.lock:
            if key in self.cache:self.cache.move_to_end(key);return self.cache[key]
        with self.processing:
            cached=None
            for manifest in (self.root/'reports/pointcloud-scale-20261019/lod').glob('*/summary.json'):
                m=read(manifest)
                if Path(m['source_path'])==source and m['preview_points']<=budget:
                    cached=load_lod_cache(manifest.parent,source,budget,verify_original_rows=True);break
            if cached:xyz,rgb,ids=cached['xyz'],cached['rgb'],cached['ids'];selection='空间预览缓存 · 原编号保留'
            else:
                records,_=map_ply_vertices(source);preview=budgeted_spatial_preview(records,budget);ids=preview['ids']
                xyz=np.column_stack([records[n][ids] for n in ['x','y','z']]).astype('<f4');rgb=record_rgb(records,ids);del records
                selection='体素代表点 · 原编号保留'
            result=dict(**pack(xyz,rgb,ids),**{k:v for k,v in meta.items() if k!='points'},sourceSha256=file_sha256(source),selection=selection,
                        originalPoints=meta['points'],bounds=[xyz.min(0).tolist(),xyz.max(0).tolist()])
        with self.lock:
            self.cache[key]=result
            while len(self.cache)>8:self.cache.popitem(last=False)
        return result

    def frame(self, scan_id, ordinal):
        if scan_id not in self.indices:raise ValueError('未知工程')
        path,index=self.indices[scan_id];frames=index['frames']
        if not 0<=ordinal<len(frames):raise ValueError('帧序号超出范围')
        frame=frames[ordinal];folder=path.parent/f"frame_{frame['id']:010d}"
        with np.load(folder/'frame.npz',allow_pickle=False) as saved:
            depth=saved['depth_mm'];valid=np.flatnonzero(depth.ravel()>0);chosen=np.linspace(0,len(valid)-1,min(25000,len(valid)),dtype=int);pixels=valid[chosen]
            colors=saved['rgba'][chosen,:3].copy() if 'rgba' in saved else np.full((len(pixels),3),180,np.uint8)
        h,w=depth.shape;v,u=np.divmod(pixels,w);z=depth.ravel()[pixels];cal=index['intrinsics']['Pl'];K=np.array(cal['K'])
        xyz=np.column_stack(((u*cal['width']/w-K[0,2])*z/K[0,0],(v*cal['height']/h-K[1,2])*z/K[1,1],z))
        pose_path=next((folder/name for name in ['pose_optimized.npy','pose_stored.npy','pose.npy','pose_saved.npy'] if (folder/name).is_file()),None)
        if pose_path:
            pose=np.load(pose_path,allow_pickle=False);xyz=(xyz*np.array(index.get('optical_to_pose_axes',[1,-1,-1])))@pose[:3,:3].T+pose[:3,3]
        return dict(**pack(xyz,colors,pixels),frame_id=frame['id'],ordinal=ordinal,total=len(frames),
            originalPoints=len(valid),unit='mm',pose_available=pose_path is not None,
            coordinate='保存工程坐标' if pose_path else '相机光学坐标（缺少位姿）',
            capture_timestamp=None,label=f"保存帧 {frame['id']}",
            depth_url=f'/api/depth.png?scan={scan_id}&ordinal={ordinal}')

    def region(self, identifier, vertex, radius_mm):
        if identifier not in self.models:raise ValueError('未知模型')
        if type(vertex) is not int or not np.isfinite(radius_mm) or not 0<radius_mm<=50:raise ValueError('需要有效原点编号和0至50mm局部半径')
        meta=self.models[identifier];source=Path(meta['path']);digest=file_sha256(source)
        candidates=[*(self.root/'reports/pointcloud-scale-20261019/spatial-index').glob('*/index/summary.json'),
                    *(self.root/'reports/pointcloud-scale-20261019/workflow-spatial-run/nodes').glob('*/summary.json'),
                    *self.output.glob('*/result/nodes/index/summary.json')]
        manifest=next((p for p in candidates if read(p).get('kind')=='original_ply_vertex_tile_index' and read(p).get('source_sha256')==digest),None)
        if manifest is None:raise ValueError('这份模型尚未建立局部索引，请先点击“生成空间缓存与局部索引”')
        with PlySpatialIndex(manifest.parent,source) as index:
            if not 0<=vertex<len(index.records):raise ValueError('原点编号超出范围')
            center=np.array([index.records[n][vertex] for n in ['x','y','z']],float);region=index.query_sphere(center,radius_mm)
            ids=region['original_vertex_ids']
            if len(ids)>60000:raise ValueError('局部完整点超过60000显示预算，请缩小半径')
            xyz=region['xyz_mm'];rgb=record_rgb(index.records,ids)
        return dict(**pack(xyz,rgb,ids),**{k:v for k,v in meta.items() if k!='points'},originalPoints=meta['points'],sourceSha256=digest,
                    selection=f'局部完整原顶点 · 原点 #{vertex} 周围 {radius_mm:g} mm',exact_region=True,center_mm=center.tolist())

    def depth_image(self, scan_id, ordinal):
        from PIL import Image
        path,index=self.indices[scan_id];frame=index['frames'][ordinal]
        if not 0<=ordinal<len(index['frames']):raise ValueError('帧序号超出范围')
        with np.load(path.parent/f"frame_{frame['id']:010d}"/'frame.npz',allow_pickle=False) as saved:depth=saved['depth_mm']
        valid=depth>0;low,high=np.percentile(depth[valid],[2,98]) if valid.any() else (0,1)
        value=np.clip((depth-low)/max(high-low,1e-6),0,1);rgb=np.stack((255*value,220*(1-np.abs(value-.5)*2),255*(1-value)),axis=-1).astype(np.uint8);rgb[~valid]=[12,20,32]
        output=io.BytesIO();Image.fromarray(rgb).resize((400,300)).save(output,format='PNG');return output.getvalue()

    def start_job(self, request):
        with self.lock:
            if any(j['status'] in ['queued','running'] for j in self.jobs.values()):raise ValueError('当前有一个处理任务，请等待或在步骤之间取消')
        kind=request.get('kind');job_id=uuid.uuid4().hex[:16];folder=self.output/job_id
        if kind=='spatial':
            model=self.models.get(request.get('model_id'))
            if model is None:raise ValueError('请选择目录中的模型')
            plan=dict(format_version=1,name='Web 空间预览与原顶点索引',input_sha256={model['path']:file_sha256(Path(model['path']))},nodes=[
                dict(id='preview',tool='cloud.preview',parameters=dict(source=model['path'],unit='mm',budget=40000)),
                dict(id='index',tool='cloud.index',parameters=dict(source=model['path'],unit='mm',tile_mm=5.))])
            folder.mkdir(parents=True);(folder/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
            command=[sys.executable,str(self.root/'scripts/run_reconstruction_workflow.py'),'--plan',str(folder/'plan.json'),'--out',str(folder/'result'),'--cancel-file',str(folder/'cancel')]
        elif kind=='workbench':
            source=self.models.get(request.get('source_id'));target=self.models.get(request.get('target_id'))
            if source is None or target is None or source['id']==target['id']:raise ValueError('需要两份不同的目录模型')
            folder.mkdir(parents=True)
            command=[sys.executable,str(self.root/'scripts/build_landmark_workbench.py'),'--source-cloud',source['path'],'--target-cloud',target['path'],'--unit','mm','--out',str(folder/'result/workbench.html'),
                     '--notes','来自Web工程工作区的自选模型。原始点和模型不覆盖；同一物理位置需人工判断。']
            (folder/'selection.json').write_text(json.dumps(dict(source=source,target=target),ensure_ascii=False,indent=2),encoding='utf-8')
        elif kind=='alignment':
            session=request.get('session')
            if not isinstance(session,dict):raise ValueError('需要对应点会话 JSON')
            allowed={Path(m['path']).resolve() for m in self.models.values()}
            for name in ['source','target']:
                if Path(session[name]['path']).resolve() not in allowed:raise ValueError('会话引用的模型不在当前清单中')
            references={Path(p['data']['candidateReference']['path']).resolve() for p in self.pages.values()}
            if session.get('kind')=='existing_candidate' and Path(session['candidate_reference']['path']).resolve() not in references:raise ValueError('已有候选引用不在当前工作台中')
            prepared={p['data'].get('preparedPath') for p in self.pages.values()}
            if session.get('prepared_path') not in prepared|{None}:raise ValueError('未知片段工程')
            folder.mkdir(parents=True);(folder/'session.json').write_text(json.dumps(session,ensure_ascii=False,indent=2),encoding='utf-8')
            command=[sys.executable,str(self.root/'scripts/apply_landmark_alignment.py'),'--session',str(folder/'session.json'),'--out',str(folder/'result')]
        else:raise ValueError('未知处理工具')
        job=dict(id=job_id,kind=kind,status='queued',created_at=datetime.now(timezone.utc).isoformat(),folder=str(folder),command_argv=command)
        self.jobs[job_id]=job
        def run():
            import os
            with self.processing:
                job['status']='running'
                try:
                    env=dict(os.environ,PYTHONIOENCODING='utf-8',OMP_NUM_THREADS='4')
                    with (folder/'process.log').open('w',encoding='utf-8') as log:
                        result=subprocess.run(command,cwd=self.root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
                    status='completed' if result.returncode==0 else 'failed';job['exit_code']=result.returncode
                    if (folder/'result/state.json').is_file():status=read(folder/'result/state.json')['status']
                    if kind=='spatial' and (folder/'result/index.html').is_file():job['report']=self.url(folder/'result/index.html')
                    if kind=='workbench' and (folder/'result/workbench.html').is_file():job['report']=self.url(folder/'result/workbench.html')
                    self.refresh()
                    job['status']=status
                except Exception as error:job['status']='failed';job['error']=str(error)
                job['finished_at']=datetime.now(timezone.utc).isoformat();(folder/'job.json').write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
        threading.Thread(target=run,daemon=True).start();return self.job(job_id)

    def job(self, identifier):
        if identifier not in self.jobs:raise ValueError('未知任务')
        job=dict(self.jobs[identifier]);folder=Path(job['folder']);log=folder/'process.log'
        job['log']=log.read_text(encoding='utf-8',errors='replace')[-14000:] if log.is_file() else ''
        state=folder/'result/state.json'
        if state.is_file():job['workflow']=read(state)
        return job


def make_handler(studio):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send(self, data, content='application/json; charset=utf-8', status=200):
            if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type',content);self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)

        def trusted_host(self):
            return self.headers.get('Host') in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}']

        def do_GET(self):
            if not self.trusted_host():self.send(dict(error='仅允许本机地址'),status=403);return
            parsed=urlsplit(self.path);query=parse_qs(parsed.query);get=lambda key,default=None:query.get(key,[default])[0]
            try:
                if parsed.path=='/api/catalog':self.send(studio.catalog)
                elif parsed.path=='/api/cloud':self.send(studio.cloud(get('id'),int(get('budget',40000))))
                elif parsed.path=='/api/frame':self.send(studio.frame(get('scan'),int(get('ordinal',0))))
                elif parsed.path=='/api/region':self.send(studio.region(get('id'),int(get('vertex')),float(get('radius_mm',5))))
                elif parsed.path=='/api/depth.png':self.send(studio.depth_image(get('scan'),int(get('ordinal',0))),'image/png')
                elif parsed.path=='/api/jobs':self.send([studio.job(key) for key in studio.jobs])
                elif parsed.path.startswith('/api/jobs/'):self.send(studio.job(parsed.path.rsplit('/',1)[1]))
                else:
                    raw=unquote(parsed.path);relative='web/studio/index.html' if raw=='/' else raw.lstrip('/')
                    path=(studio.root/relative).resolve()
                    allowed=[studio.root/'web',studio.root/'reports',studio.root/'docs']
                    if not any(root==path or root in path.parents for root in allowed) or path.suffix.lower() not in ['.html','.js','.css','.json','.png','.jpg','.jpeg','.svg','.md','.txt','.csv'] or not path.is_file():
                        self.send(dict(error='文件不存在或不提供该类型下载'),status=404);return
                    # Do not expose arbitrary session/log folders as static JSON.
                    if studio.output in path.parents and path.name in ['session.json','plan.json']:self.send(dict(error='会话文件由任务接口管理'),status=403);return
                    content=mimetypes.guess_type(path.name)[0] or 'text/plain'
                    if path.suffix=='.md':content='text/plain; charset=utf-8'
                    self.send(path.read_bytes(),content)
            except (ValueError,KeyError,TypeError,IndexError,OSError) as error:self.send(dict(error=str(error)),status=400)

        def do_POST(self):
            origin=self.headers.get('Origin');expected=[f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}']
            if not self.trusted_host() or (origin is not None and origin not in expected):self.send(dict(error='请求来源不匹配'),status=403);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=1000000:raise ValueError('请求大小超过限制')
                request=json.loads(self.rfile.read(length))
                if self.path=='/api/jobs':self.send(studio.start_job(request),status=202)
                elif self.path.startswith('/api/jobs/') and self.path.endswith('/cancel'):
                    identifier=self.path.split('/')[3];job=studio.job(identifier)
                    if job['kind']!='spatial':raise ValueError('该单步任务不支持步骤间取消')
                    (Path(job['folder'])/'cancel').touch();self.send(dict(status='cancel_requested_between_steps'))
                else:self.send(dict(error='未知操作'),status=404)
            except (ValueError,KeyError,TypeError,OSError) as error:self.send(dict(error=str(error)),status=400)
    return Handler


def serve(workspace, port=8877):
    studio=Studio(workspace)
    class LocalServer(ThreadingHTTPServer):
        allow_reuse_address=False
    server=LocalServer(('127.0.0.1',port),make_handler(studio),bind_and_activate=False)
    if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):server.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
    server.server_bind();server.server_activate()
    print(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}',projects=len(studio.indices),models=len(studio.models)),ensure_ascii=True),flush=True)
    try:server.serve_forever()
    finally:server.server_close()

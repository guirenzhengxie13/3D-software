"""Pinned project result snapshots and reversible active-version transitions.

Only model selection and provenance references change. Geometry, poses, and
processing outputs remain immutable; this is not an undo of algorithm steps.
"""

from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid

from .offline import file_sha256


def now():return datetime.now(timezone.utc).isoformat()


@contextmanager
def project_file_lock(path):
    """Nonblocking OS lock, released on process exit without a stale sentinel."""
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b',buffering=0) as handle:
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:raise ValueError('另一个服务正在更新本工程版本，请稍后刷新') from error
        try:
            # Initialize only after locking: concurrent creators must not write
            # the lock byte while another process owns that byte on Windows.
            if path.stat().st_size==0:handle.write(b'0')
            yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def atomic_save(path,record):
    temporary=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    try:
        with temporary.open('w',encoding='utf-8',newline='\n') as handle:
            json.dump(record,handle,ensure_ascii=False,indent=2,allow_nan=False);handle.flush();os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()


class ProjectHistory:
    def __init__(self,studio):
        self.studio=studio;self.root=studio.root;self.mapper=studio.paths;self.lock=threading.RLock()
        self.directory=self.root/'reports/web-studio/project-history'

    def index(self,scan):
        if not isinstance(scan,str) or scan not in self.studio.indices:raise ValueError('请选择一份已解包工程')
        path=self.studio.indices[scan][0];raw=path.read_bytes();index=json.loads(raw.decode('utf-8'))
        if index.get('scan_id')!=scan:raise ValueError('工程索引身份不一致')
        return path,hashlib.sha256(raw).hexdigest()

    def folder(self,scan):return self.mapper.resolve_output(self.directory/hashlib.sha256(scan.encode()).hexdigest()[:24])

    def load(self,scan):
        path=self.folder(scan)/'state.json'
        if not path.exists():return dict(format_version=1,scan_id=scan,versions={},active=None,undo=[],redo=[],events=[]),'empty'
        raw=path.read_bytes();record=json.loads(raw.decode('utf-8'))
        if not isinstance(record,dict) or record.get('format_version')!=1 or record.get('scan_id')!=scan:raise ValueError('工程版本记录格式或身份不一致')
        versions=record.get('versions')
        if not isinstance(versions,dict) or not isinstance(record.get('events'),list):raise ValueError('工程版本记录不完整')
        for key,value in versions.items():
            if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{16}',key) or not isinstance(value,dict) or value.get('id')!=key:raise ValueError('派生版本编号不一致')
            if any(k not in value for k in ['created_at','label','decision','models','index_path','index_sha256','input_sha256']):raise ValueError('派生版本记录不完整')
            if not isinstance(value['input_sha256'],dict) or not isinstance(value['models'],list) or not 1<=len(value['models'])<=3 or not all(isinstance(m,dict) and all(k in m for k in ['label','path','sha256']) for m in value['models']):raise ValueError('派生版本模型信息不完整')
            parent=value.get('parent_id')
            if parent is not None and (not isinstance(parent,str) or parent not in versions):raise ValueError('派生版本父节点缺失')
        for key in versions:
            seen=set();cursor=key
            while cursor is not None:
                if cursor in seen:raise ValueError('派生版本父节点形成循环')
                seen.add(cursor);cursor=versions[cursor].get('parent_id')
        if versions and record.get('active') is None:raise ValueError('非空工程版本缺少活动节点')
        for key in ['undo','redo']:
            if not isinstance(record.get(key),list) or any(i not in versions for i in record[key]):raise ValueError('版本切换历史损坏')
        if record.get('active') is not None and record['active'] not in versions:raise ValueError('活动版本缺失')
        return record,hashlib.sha256(raw).hexdigest()

    def verify(self,version,scan,index_path,index_sha,cache):
        problems=[];models=[];catalog={self.mapper.resolve(m['path']):m for m in list(self.studio.models.values()) if m.get('scan_id')==scan}
        def digest(path):
            path=self.mapper.resolve(path);key=str(path)
            if key not in cache:
                before=path.stat();sha=file_sha256(path);after=path.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('文件正在变化：'+path.name)
                cache[key]=sha
            return path,cache[key]
        try:
            if self.mapper.resolve(version['index_path'])!=index_path or version['index_sha256']!=index_sha:raise ValueError('原工程索引已换版')
            if not isinstance(version['models'],list) or not 1<=len(version['models'])<=3:raise ValueError('版本模型列表无效')
            pins=version['input_sha256']
            for row in version['models']:
                path,sha=digest(row['path']);meta=catalog.get(path)
                if meta is None:raise ValueError('版本模型不在当前工程目录中：'+path.name)
                if sha!=row['sha256']:raise ValueError('模型内容已变化：'+path.name)
                if self.mapper.record(pins).get(str(path))!=sha:raise ValueError('模型来源固定版本缺失')
                models.append(dict(id=meta['id'],sha256=sha,label=row['label'],path=str(path)))
            for path,expected in pins.items():
                _,actual=digest(path)
                if actual!=expected:raise ValueError('版本引用文件已变化：'+Path(path).name)
        except (ValueError,KeyError,TypeError,OSError) as error:problems.append(str(error))
        return dict(available=not problems,problems=problems,models=models if not problems else [])

    def context(self,scan,loaded=None):
        index_path,index_sha=self.index(scan);record,state_sha=loaded or self.load(scan);cache={};versions=[]
        for version in record['versions'].values():
            status=self.verify(version,scan,index_path,index_sha,cache)
            versions.append(dict(id=version['id'],parent_id=version.get('parent_id'),created_at=version['created_at'],
                label=version['label'],decision=version['decision'],model_labels=[m['label'] for m in version['models']],
                provenance=version.get('provenance',[]),**status))
        lookup={v['id']:v for v in versions}
        can=lambda stack:bool(stack and lookup[stack[-1]]['available'])
        return dict(scan_id=scan,index_sha256=index_sha,state_sha256=state_sha,versions=versions,active=record['active'],
            active_version=lookup.get(record['active']),can_undo=can(record['undo']),can_redo=can(record['redo']),
            undo_blocked=bool(record['undo'] and not can(record['undo'])),redo_blocked=bool(record['redo'] and not can(record['redo'])),
            events=record['events'],semantics='pinned_model_selection_and_provenance_not_algorithm_or_geometry_undo')

    def provenance(self,path,sha,scan,pin):
        for job in list(self.studio.jobs.values()):
            if job.get('kind')!='fragment_fusion':continue
            folder=self.mapper.resolve(job['folder']);result=folder/'result'
            if result not in path.parents:continue
            if job.get('status')!='completed' or job.get('scan_id')!=scan:raise ValueError('该派生模型的重融合任务尚未完成或工程不一致')
            summary=json.loads(pin(result/'summary.json').read_text(encoding='utf-8'))
            if summary.get('scan_id')!=scan or not summary.get('same_original_frames_and_roi_pixels'):raise ValueError('重融合来源记录不完整')
            arm=next((r for r in summary['results'] if self.mapper.resolve(r['path'])==path),None)
            if arm is None:raise ValueError('模型未列在该重融合任务结果中')
            state=self.mapper.record(json.loads(pin(result/'state.json').read_text(encoding='utf-8')))
            matches=[]
            for node in state['nodes']:
                node_root=result/'nodes'/node['id']
                if node.get('tool')=='fragments.fuse' and node.get('status')=='completed' and node_root in path.parents:
                    key=path.relative_to(node_root).as_posix();matches.append(node.get('output_sha256',{}).get(key))
            if state.get('status')!='completed' or matches!=[sha]:raise ValueError('模型与已完成工作流的输出SHA不一致')
            pin(folder/'review-original.json',job['reviewed_record_sha256']);pin(folder/'binding.json')
            review_id=job['review_id']
            if not re.fullmatch('[0-9a-f]{16}',review_id):raise ValueError('重融合核验编号无效')
            pin(self.studio.fragments.reviews/review_id/'fragment-plan.json',job['reviewed_plan_sha256'])
            if summary.get('reviewed_plan_sha256')!=job['reviewed_plan_sha256']:raise ValueError('重融合计划来源版本不一致')
            return dict(kind='completed_fragment_fusion',job_id=job['id'],review_id=review_id,
                saved_control=arm['saved_control'],selected_frames=summary['selected_frames'],
                same_original_pixel_sha256=summary['selected_depth_with_frame_ids_sha256'],report=job.get('report'))
        return dict(kind='catalog_model_snapshot',limitation='原帧归属没有由本版本登记过程推断或重新验证')

    def change(self,request):
        allowed={'scan_id','index_sha256','state_sha256','action','models','label','decision','version_id'}
        if not isinstance(request,dict) or set(request)-allowed:raise ValueError('版本操作包含未知字段')
        scan=request.get('scan_id');index_path,index_sha=self.index(scan);action=request.get('action')
        if request.get('index_sha256')!=index_sha:raise ValueError('工程索引已变化，请刷新版本记录')
        if action not in ['save','restore','undo','redo']:raise ValueError('未知版本操作')
        if action=='save':
            for key,limit in [('label',200),('decision',4000)]:
                if not isinstance(request.get(key),str) or not request[key].strip() or len(request[key])>limit:raise ValueError('请填写版本名称和本次决定说明')
            rows=request.get('models')
            if not isinstance(rows,list) or not 1<=len(rows)<=3 or any(not isinstance(row,dict) or set(row)!=set(['id','sha256']) for row in rows):raise ValueError('需要1至3份已加载的目录模型及SHA')
            if len({r['id'] for r in rows})!=len(rows):raise ValueError('同一模型不能在版本中重复登记')
        with self.lock,project_file_lock(self.folder(scan)/'writer.lock'):
            record,state_sha=self.load(scan)
            if request.get('state_sha256')!=state_sha:raise ValueError('工程版本已被另一个页面或服务更新，请刷新后重试')
            previous=record['active'];pins={};cache={}
            def pin(path,expected=None):
                path=self.mapper.resolve(path);before=path.stat();sha=file_sha256(path);after=path.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('版本文件正在变化')
                if expected is not None and sha!=expected:raise ValueError('待登记文件与已查看版本不一致：'+path.name)
                if str(path) in pins and pins[str(path)]!=sha:raise ValueError('登记期间输入版本变化')
                pins[str(path)]=sha;return path
            if action=='save':
                pin(index_path,index_sha);models=[];origins=[]
                for row in rows:
                    meta=self.studio.models.get(row['id'])
                    if meta is None or meta.get('scan_id')!=scan or meta.get('unit')!='mm':raise ValueError('只可登记本工程的毫米目录模型')
                    if not isinstance(row['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',row['sha256']):raise ValueError('需要已加载模型的内容SHA')
                    path=pin(meta['path'],row['sha256'])
                    models.append(dict(path=str(path),sha256=row['sha256'],label=meta['label'],role=meta.get('role'),points=meta['points']))
                    origins.append(self.provenance(path,row['sha256'],scan,pin))
                version_id=uuid.uuid4().hex[:16]
                version=dict(id=version_id,parent_id=previous,created_at=now(),label=request['label'].strip(),decision=request['decision'].strip(),
                    index_path=str(index_path),index_sha256=index_sha,models=models,input_sha256=pins,provenance=origins)
                record['versions'][version_id]=version
            else:
                if action=='restore':version_id=request.get('version_id')
                else:
                    stack=record['undo' if action=='undo' else 'redo']
                    if not stack:raise ValueError('没有可撤销或重做的版本切换')
                    version_id=stack[-1]
                if version_id not in record['versions']:raise ValueError('未知派生版本')
                status=self.verify(record['versions'][version_id],scan,index_path,index_sha,cache)
                if not status['available']:raise ValueError('目标版本无法载入：'+'；'.join(status['problems']))
                if version_id==previous:return self.context(scan,(record,state_sha))
            if action=='undo':record['undo'].pop();record['redo'].append(previous)
            elif action=='redo':record['redo'].pop();record['undo'].append(previous)
            else:
                if previous is not None:record['undo'].append(previous)
                record['redo']=[]
            record['active']=version_id
            record['events'].append(dict(sequence=len(record['events'])+1,action=action,from_version=previous,to_version=version_id,at=now()))
            # Verify every captured version and original state just before commit.
            status=self.verify(record['versions'][version_id],scan,index_path,index_sha,{})
            if not status['available']:raise ValueError('登记期间输入变化：'+'；'.join(status['problems']))
            if self.load(scan)[1]!=state_sha:raise ValueError('版本记录在写入前被外部修改，请刷新')
            atomic_save(self.folder(scan)/'state.json',record)
            return self.context(scan)

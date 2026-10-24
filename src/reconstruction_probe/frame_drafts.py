"""Immutable, incomplete frame-ownership/ROI/settings form snapshots.

Drafts never retain coordinate confirmation, ready reviews, executable plans or
job IDs. Restore requires current index/alignment/model references; raw frame
payload validation remains the explicit review step.
"""

import hashlib
import json
import re
import threading
import uuid

from .fusion_settings import DEFAULT_FUSION_SETTINGS
from .offline import file_sha256
from .project_history import atomic_save,now,project_file_lock


TEXT_LIMITS=dict(source_frames=100000,target_frames=100000,source_basis=4000,target_basis=4000,decision=4000)
SHA=re.compile('[0-9a-f]{64}')


def shape(draft):
    fields={'format','format_version','unit','alignment','candidate','mode','roi_fields','fusion_fields',*TEXT_LIMITS}
    if not isinstance(draft,dict) or set(draft)!=fields:raise ValueError('帧编辑草稿字段不完整；不能包含坐标确认、核验或任务字段')
    if draft['format']!='fragment-editor-draft' or type(draft['format_version']) is not int or draft['format_version']!=1 or draft['unit']!='mm':raise ValueError('不支持的帧编辑草稿格式')
    if draft['mode'] not in ['frame_id','ordinal_1based']:raise ValueError('未知保存序号/原帧编号方式')
    for key,limit in TEXT_LIMITS.items():
        if not isinstance(draft[key],str) or len(draft[key])>limit:raise ValueError('草稿文本过长或格式无效：'+key)
    if not isinstance(draft['candidate'],str) or len(draft['candidate'])>100:raise ValueError('草稿候选格式无效')
    ref=draft['alignment']
    if ref is not None and (not isinstance(ref,dict) or set(ref)!={'relative_path','sha256'} or not isinstance(ref['relative_path'],str) or len(ref['relative_path'])>600 or not isinstance(ref['sha256'],str) or not SHA.fullmatch(ref['sha256'])):raise ValueError('草稿对齐来源格式无效')
    if not isinstance(draft['roi_fields'],list) or len(draft['roi_fields'])!=6 or any(not isinstance(v,str) or len(v)>100 for v in draft['roi_fields']):raise ValueError('草稿选区需保留六个文本边界，可部分留空')
    values=draft['fusion_fields']
    if not isinstance(values,dict) or set(values)!=set(DEFAULT_FUSION_SETTINGS) or any(not isinstance(v,str) or len(v)>60 for v in values.values()):raise ValueError('草稿需保留四个融合参数文本')
    return json.loads(json.dumps(draft,allow_nan=False))


class FrameDrafts:
    def __init__(self,studio):
        self.studio=studio;self.mapper=studio.paths;self.directory=studio.root/'reports/web-studio/frame-drafts';self.lock=threading.RLock()

    def folder(self,scan):return self.mapper.resolve_output(self.directory/hashlib.sha256(scan.encode()).hexdigest()[:24])

    def load(self,scan):
        path=self.folder(scan)/'state.json'
        if not path.exists():return dict(format_version=1,scan_id=scan,drafts=[]),'empty'
        raw=path.read_bytes();record=json.loads(raw.decode('utf-8'))
        if not isinstance(record,dict) or type(record.get('format_version')) is not int or record['format_version']!=1 or record.get('scan_id')!=scan or not isinstance(record.get('drafts'),list):raise ValueError('帧草稿记录格式或工程身份损坏')
        seen=set()
        for row in record['drafts']:
            if not isinstance(row,dict) or set(row)!={'id','created_at','label','index_sha256','input_sha256','draft'}:raise ValueError('帧草稿记录不完整')
            if not isinstance(row['id'],str) or not re.fullmatch('[0-9a-f]{16}',row['id']) or row['id'] in seen:raise ValueError('帧草稿编号损坏或重复')
            seen.add(row['id'])
            if not isinstance(row['label'],str) or not row['label'].strip() or len(row['label'])>100 or not isinstance(row['created_at'],str) or not isinstance(row['index_sha256'],str) or not SHA.fullmatch(row['index_sha256']):raise ValueError('帧草稿名称、时间或索引版本损坏')
            if not isinstance(row['input_sha256'],dict) or not row['input_sha256'] or any(not isinstance(k,str) or not isinstance(v,str) or not SHA.fullmatch(v) for k,v in row['input_sha256'].items()):raise ValueError('帧草稿来源版本损坏')
            shape(row['draft'])
        return record,hashlib.sha256(raw).hexdigest()

    def basis(self,scan):
        if not isinstance(scan,str):raise ValueError('请选择工程')
        path,_,sha,_=self.studio.fragments._index(scan)
        return path,sha,self.studio.fragments._alignments(scan)

    def validate(self,draft,alignments):
        draft=shape(draft);ref=draft['alignment']
        if ref is None:
            if draft['candidate']:raise ValueError('未选择对齐来源时不能保存位置候选')
            return draft,None
        alignment=next((a for a in alignments.values() if a['relative_path']==ref['relative_path'] and a['sha256']==ref['sha256']),None)
        if alignment is None:raise ValueError('草稿的已核验对齐来源已变化或不可用')
        if draft['candidate'] not in alignment['candidates']:raise ValueError('草稿候选不属于所选对齐来源')
        return draft,alignment

    def pins(self,path,sha,alignment):
        pins={str(path):sha}
        if alignment is None:return pins
        summary=alignment['directory']/'summary.json';raw=summary.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=alignment['sha256']:raise ValueError('对齐来源在读取期间变化')
        report=self.mapper.record(json.loads(raw.decode('utf-8')));references=report.get('input_sha256')
        if not isinstance(references,dict):raise ValueError('对齐缺少原输入版本')
        pins[str(summary)]=alignment['sha256']
        session=alignment['directory']/'session-original.json';pins[str(session)]=file_sha256(session)
        if pins[str(session)] not in references.values():raise ValueError('对齐未固定导出会话版本')
        for name,expected in references.items():
            actual=self.mapper.resolve(name)
            if not isinstance(expected,str) or not SHA.fullmatch(expected) or file_sha256(actual)!=expected:raise ValueError('对齐原输入已变化：'+actual.name)
            if str(actual) in pins and pins[str(actual)]!=expected:raise ValueError('对齐原输入SHA冲突')
            pins[str(actual)]=expected
        for side in ['source','target']:pins[alignment[side]['path']]=alignment[side]['sha256']
        self.check(pins);return pins

    def check(self,pins):
        for name,sha in pins.items():
            if file_sha256(self.mapper.resolve(name))!=sha:raise ValueError('帧草稿引用的文件版本变化')

    def context(self,scan,draft_id=None,index_sha256=None):
        path,sha,alignments=self.basis(scan);record,state_sha=self.load(scan);rows=[];restored=None
        for row in reversed(record['drafts']):
            problem=None;alignment=None
            try:
                if row['index_sha256']!=sha:raise ValueError('草稿工程索引已换版')
                draft,alignment=self.validate(row['draft'],alignments);pins=self.pins(path,sha,alignment)
                if self.mapper.record(row['input_sha256'])!=pins:raise ValueError('草稿固定的对齐/模型来源不一致')
            except (ValueError,KeyError,TypeError,OSError) as error:problem=str(error)
            rows.append(dict(id=row['id'],label=row['label'],created_at=row['created_at'],available=problem is None,reason=problem))
            if draft_id==row['id']:
                if problem:raise ValueError(problem)
                if index_sha256!=sha:raise ValueError('当前工程索引已变化，请刷新')
                restored=dict(draft=draft,alignment_id=alignment['id'] if alignment else '',input_sha256=pins)
        if draft_id is not None and restored is None:raise ValueError('未知帧编辑草稿')
        if file_sha256(path)!=sha:raise ValueError('工程索引在读取期间变化')
        return dict(scan_id=scan,index_sha256=sha,state_sha256=state_sha,drafts=rows,**(restored or {}))

    def inspect(self,request):
        if not isinstance(request,dict) or set(request)!={'scan_id','index_sha256','draft'}:raise ValueError('帧草稿载入参数不完整')
        path,sha,alignments=self.basis(request['scan_id'])
        if request['index_sha256']!=sha:raise ValueError('草稿工程索引不匹配')
        draft,alignment=self.validate(request['draft'],alignments);pins=self.pins(path,sha,alignment);self.check(pins)
        return dict(scan_id=request['scan_id'],index_sha256=sha,draft=draft,alignment_id=alignment['id'] if alignment else '',input_sha256=pins,requires_review=True)

    def save(self,request):
        if not isinstance(request,dict) or set(request)!={'scan_id','index_sha256','state_sha256','label','draft'}:raise ValueError('帧草稿保存参数不完整')
        if not isinstance(request['label'],str) or not request['label'].strip() or len(request['label'])>100:raise ValueError('请输入1至100字草稿名称')
        inspected=self.inspect({k:request[k] for k in ['scan_id','index_sha256','draft']});scan=request['scan_id']
        with self.lock,project_file_lock(self.folder(scan)/'writer.lock'):
            record,state_sha=self.load(scan)
            if request['state_sha256']!=state_sha:raise ValueError('帧草稿列表已有新保存，请刷新后重试')
            self.check(inspected['input_sha256'])
            row=dict(id=uuid.uuid4().hex[:16],created_at=now(),label=request['label'].strip(),index_sha256=inspected['index_sha256'],input_sha256=inspected['input_sha256'],draft=inspected['draft'])
            record['drafts'].append(row);atomic_save(self.folder(scan)/'state.json',record)
        result=self.context(scan);result['saved_id']=row['id'];return result

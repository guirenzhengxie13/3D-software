"""Explicit, immutable snapshots of incomplete correspondence selections.

No fitting or alignment jobs run during save/restore. Original model vertices,
page bytes and candidate references are checked before any draft is published.
"""

import base64
import hashlib
import json
import re
import threading
import uuid

import numpy as np

from .offline import file_sha256
from .ply_layout import map_ply_vertices
from .project_history import atomic_save, now, project_file_lock


class LandmarkDrafts:
    def __init__(self, studio):
        self.studio=studio;self.mapper=studio.paths;self.lock=threading.RLock()
        self.directory=studio.root/'reports/web-studio/landmark-drafts'

    def page(self, identifier):
        with self.studio.lock:entry=self.studio.pages.get(identifier)
        if entry is None:raise ValueError('未知对应点工作区，请刷新目录')
        path=entry['path'];raw=path.read_bytes();data=self.studio.workbench_data(raw.decode('utf-8'))
        if data is None or data.get('unit')!='mm' or len(data['clouds'])!=2:raise ValueError('对应点工作区格式不完整')
        relative=path.relative_to(self.studio.root).as_posix()
        return path,relative,hashlib.sha256(raw).hexdigest(),data

    def folder(self, relative):
        return self.mapper.resolve_output(self.directory/hashlib.sha256(relative.encode()).hexdigest()[:24])

    def load(self, relative):
        path=self.folder(relative)/'state.json'
        if not path.exists():return dict(format_version=1,workbench_relative=relative,drafts=[]),'empty'
        raw=path.read_bytes();record=json.loads(raw.decode('utf-8'))
        if not isinstance(record,dict) or type(record.get('format_version')) is not int or record['format_version']!=1 or record.get('workbench_relative')!=relative or not isinstance(record.get('drafts'),list):raise ValueError('草稿记录格式或工作区身份不一致')
        seen=set()
        for row in record['drafts']:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not re.fullmatch('[0-9a-f]{16}',row['id']) or row['id'] in seen:raise ValueError('草稿编号损坏或重复')
            seen.add(row['id'])
            if any(k not in row for k in ['created_at','label','page_sha256','input_sha256','draft']) or not isinstance(row['input_sha256'],dict) or not isinstance(row['draft'],dict):raise ValueError('草稿记录不完整')
            if not isinstance(row['label'],str) or not row['label'].strip() or len(row['label'])>100 or not isinstance(row['created_at'],str) or not isinstance(row['page_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',row['page_sha256']):raise ValueError('草稿名称、时间或页面SHA损坏')
            if not row['input_sha256'] or any(not isinstance(k,str) or not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for k,v in row['input_sha256'].items()):raise ValueError('草稿来源SHA损坏')
            draft=row['draft']
            if draft.get('format')!='reconstruction-landmark-draft' or type(draft.get('format_version')) is not int or draft['format_version']!=1 or draft.get('unit')!='mm' or type(draft.get('requires_recompute')) is not bool or not isinstance(draft.get('point_pairs'),list) or len(draft['point_pairs'])>64 or not all(isinstance(p,dict) for p in draft['point_pairs']):raise ValueError('草稿选点记录损坏')
        return record,hashlib.sha256(raw).hexdigest()

    def inputs(self, data):
        pins={}
        for row in [*data['clouds'],data.get('candidateReference',{})]:
            if not isinstance(row,dict) or not isinstance(row.get('path'),str):raise ValueError('工作区模型或候选引用损坏')
            path=self.mapper.resolve(row['path']);expected=row.get('sourceSha256',row.get('sha256'))
            if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected) or file_sha256(path)!=expected:raise ValueError('工作区原模型或候选SHA已变化，请重新建立工作区')
            pins[str(path)]=expected
        return pins

    def validate(self, draft, data):
        if not isinstance(draft,dict) or set(draft)!={'format','format_version','unit','source','target','candidate_label','candidate_sha256','requires_recompute','point_pairs','pending_target'}:raise ValueError('需要完整的选点草稿，不能包含变换或任务命令')
        if draft['format']!='reconstruction-landmark-draft' or type(draft['format_version']) is not int or draft['format_version']!=1 or draft['unit']!='mm' or type(draft['requires_recompute']) is not bool:raise ValueError('不支持的草稿格式或单位')
        if draft['candidate_sha256']!=data['candidateReference']['sha256']:raise ValueError('草稿候选来源已换版')
        if not isinstance(draft['candidate_label'],str) or draft['candidate_label'] not in {r['label'] for r in data['candidates']}:raise ValueError('草稿位置候选不属于当前工作区')
        pairs=draft['point_pairs']
        if not isinstance(pairs,list) or len(pairs)>64:raise ValueError('草稿最多64对对应点')
        canonical={k:draft[k] for k in ['format','format_version','unit','candidate_label','candidate_sha256','requires_recompute']};canonical['point_pairs']=[{} for _ in pairs];canonical['pending_target']=None
        for key,index in [('target',0),('source',1)]:
            model=data['clouds'][index];ref=draft[key]
            if not isinstance(ref,dict) or set(ref)!={'sha256','fragment_id'} or ref['sha256']!=model['sourceSha256'] or type(ref['fragment_id']) is not int or ref['fragment_id']!=model.get('fragmentId',index):raise ValueError('草稿模型、方向或片段身份不一致')
            canonical[key]=dict(sha256=model['sourceSha256'],fragment_id=model.get('fragmentId',index))
            ids=np.frombuffer(base64.b64decode(model['ids'],validate=True),'<u4');xyz=np.frombuffer(base64.b64decode(model['xyz'],validate=True),'<f4').reshape(-1,3)
            if len(ids)!=len(xyz) or len(np.unique(ids))!=len(ids):raise ValueError('页面原点编号或坐标载荷损坏')
            lookup={int(rid):i for i,rid in enumerate(ids)};vertices,_=map_ply_vertices(self.mapper.resolve(model['path']));used=set()
            def selected(row, duplicate=False):
                if not isinstance(row,dict) or set(row)!={'id','xyz'} or type(row['id']) is not int or row['id'] not in lookup or not 0<=row['id']<len(vertices):raise ValueError('草稿选点不在当前预览的原顶点中')
                rid=row['id']
                if not duplicate and rid in used:raise ValueError('草稿对应点重复')
                used.add(rid);original=np.array([vertices[n][rid] for n in ['x','y','z']],dtype='<f4');point=xyz[lookup[rid]]
                given=row['xyz']
                if not isinstance(given,list) or len(given)!=3 or any(type(v) not in [float,int] for v in given) or not np.isfinite(given).all() or not np.isfinite(original).all() or not np.array_equal(point,original) or not np.array_equal(np.array(given,dtype=float),point.astype(float)):raise ValueError('草稿坐标与原点编号不一致')
                return dict(id=rid,xyz=point.astype(float).tolist())
            for i,pair in enumerate(pairs):
                if not isinstance(pair,dict) or set(pair)!={'source','target'}:raise ValueError('对应对格式不完整')
                canonical['point_pairs'][i][key]=selected(pair[key])
            if key=='target' and draft['pending_target'] is not None:canonical['pending_target']=selected(draft['pending_target'],duplicate=True)
            del vertices
        return canonical

    def verify_row(self, row, sha, pins):
        if row['page_sha256']!=sha:raise ValueError('草稿绑定的工作区页面已换版')
        if self.mapper.record(row['input_sha256'])!=pins:raise ValueError('草稿原模型或候选已换版')

    def context(self, identifier, draft_id=None, page_sha256=None):
        path,relative,sha,data=self.page(identifier);pins=self.inputs(data);record,state_sha=self.load(relative)
        result=dict(workbench_id=identifier,page_sha256=sha,state_sha256=state_sha,drafts=[])
        for row in reversed(record['drafts']):
            problem=None
            try:self.verify_row(row,sha,pins)
            except ValueError as error:problem=str(error)
            result['drafts'].append(dict(id=row['id'],created_at=row['created_at'],label=row['label'],pairs=len(row['draft'].get('point_pairs',[])),pending=row['draft'].get('pending_target') is not None,available=problem is None,reason=problem))
        if draft_id is not None:
            if page_sha256!=sha:raise ValueError('当前页面版本已变化，请重新打开工作区')
            row=next((r for r in record['drafts'] if r['id']==draft_id),None)
            if row is None:raise ValueError('未知草稿编号')
            self.verify_row(row,sha,pins);result['draft']=self.validate(row['draft'],data)
        if file_sha256(path)!=sha or self.inputs(data)!=pins:raise ValueError('工作区输入在读取期间变化')
        return result

    def save(self, request):
        if not isinstance(request,dict) or set(request)!={'workbench_id','page_sha256','state_sha256','label','draft'}:raise ValueError('草稿保存参数不完整')
        path,relative,sha,data=self.page(request['workbench_id'])
        if request['page_sha256']!=sha:raise ValueError('当前页面版本已变化，请重新打开工作区')
        label=request['label']
        if not isinstance(label,str) or not label.strip() or len(label)>100:raise ValueError('请输入1至100字草稿名称')
        with self.lock,project_file_lock(self.folder(relative)/'writer.lock'):
            record,state_sha=self.load(relative)
            if request['state_sha256']!=state_sha:raise ValueError('草稿列表已有新保存，请刷新列表后重试')
            pins=self.inputs(data);draft=self.validate(request['draft'],data)
            row=dict(id=uuid.uuid4().hex[:16],created_at=now(),label=label.strip(),page_sha256=sha,input_sha256=pins,draft=draft)
            if file_sha256(path)!=sha or self.inputs(data)!=pins:raise ValueError('工作区输入在保存期间变化')
            if self.load(relative)[1]!=state_sha:raise ValueError('草稿列表正在变化，请刷新')
            record['drafts'].append(row);atomic_save(self.folder(relative)/'state.json',record)
        result=self.context(request['workbench_id']);result['saved_id']=row['id'];return result

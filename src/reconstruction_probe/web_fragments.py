"""Reviewed Web bindings from catalogued alignments to original saved frames."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid
import zipfile

from .fragment_bridge import build_fragment_plan, read_json
from .fragment_plan import load_fragment_inputs
from .multi_scan import FrameKey, rigid
from .offline import file_sha256


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temporary.replace(path)


def frame_selection(text, mode, frame_ids):
    """Resolve explicit original IDs or one-based saved-record ordinals."""
    if not isinstance(text,str) or not text.strip() or len(text)>100000:
        raise ValueError('请填写原帧编号或保存记录序号，使用逗号与范围，例如0-30,32')
    if mode not in {'frame_id','ordinal_1based'}:raise ValueError('未知帧选择方式')
    available=set(frame_ids);values=[]
    normalized=re.sub(r'\s*-\s*','-',text.strip())
    for token in re.split(r'[,;，；\s]+',normalized):
        match=re.fullmatch(r'([0-9]{1,20})(?:-([0-9]{1,20}))?',token)
        if not match:raise ValueError('帧选择只能使用非负整数、逗号与递增范围')
        low=int(match[1]);high=int(match[2] or match[1])
        if high<low or high-low+1>len(frame_ids) or len(values)+high-low+1>len(frame_ids):
            raise ValueError('帧范围超出工程记录数或顺序不正确')
        values.extend(range(low,high+1))
    if len(set(values))!=len(values):raise ValueError('同一片段不能重复选择原帧')
    if mode=='ordinal_1based':
        if any(not 1<=i<=len(frame_ids) for i in values):raise ValueError('保存记录序号从1开始，不能超出工程范围')
        values=[frame_ids[i-1] for i in values]
    if any(v not in available for v in values):raise ValueError('所选原帧编号不在当前工程中，请核对原ID与保存序号')
    return sorted(values)


def expression(ids):
    """Small exact text representation; IDs stay strings in browser metadata."""
    values=sorted(ids);ranges=[];start=last=values[0]
    for value in values[1:]:
        if value==last+1:last=value
        else:
            ranges.append(str(start) if start==last else f'{start}-{last}');start=last=value
    ranges.append(str(start) if start==last else f'{start}-{last}')
    return ','.join(ranges)


class FragmentEditorService:
    def __init__(self, studio):
        self.studio=studio;self.root=studio.root;self.mapper=studio.paths
        self.reviews=self.root/'reports/web-studio/fragment-reviews'

    def _index(self, scan_id, expected=None):
        if scan_id not in self.studio.indices:raise ValueError('请选择一份已解包工程')
        path=self.studio.indices[scan_id][0];raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        index=json.loads(raw.decode('utf-8'))
        if index.get('scan_id')!=scan_id:raise ValueError('工程索引与目录不一致')
        if expected is not None and expected!=digest:raise ValueError('工程索引已变化，请刷新并重新核验')
        ids=[FrameKey(scan_id,row['id']).frame_id for row in index['frames']]
        if len(set(ids))!=len(ids):raise ValueError('工程含重复原帧编号')
        return path,index,digest,ids

    def _alignments(self, scan_id):
        candidates=[]
        for job in list(self.studio.jobs.values()):
            if job.get('kind')=='alignment' and job.get('status')=='completed':
                candidates.append((self.mapper.resolve(job['folder'])/'result','已核验对齐 · '+job['id']))
        seeds=[self.root/'reports/web-studio/sync-20261021/final-bridge/alignment',
               self.root/'reports/range2-study-20261018/experiments/fragment-bridge-20261021/verified/alignment']
        seed=next((p for p in seeds if (p/'summary.json').is_file()),None)
        if seed:candidates.append((seed,'已有研究回放 · 失败杯子局部组件'))
        allowed={self.mapper.resolve(m['path']):m for m in self.studio.models.values()};result={}
        for folder,label in candidates:
            try:
                summary_path=folder/'summary.json';report=read_json(summary_path)
                if report.get('status')!='reviewable_candidates_not_automatically_promoted':continue
                session_path=folder/'session-original.json';session=self.mapper.record(read_json(session_path))
                models={side:allowed[self.mapper.resolve(session[side]['path'])] for side in ['source','target']}
                if any(m.get('scan_id') not in {None,scan_id} for m in models.values()):continue
                for side,model in models.items():
                    if file_sha256(Path(model['path']))!=session[side]['sha256']:raise ValueError('原模型变化')
                labels=[]
                for row in report['candidates']:
                    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',row['label']):raise ValueError('候选标签无效')
                    rigid(row['transform']);labels.append(row['label'])
                if not labels or len(set(labels))!=len(labels):continue
                key=hashlib.sha256(str(summary_path).encode()).hexdigest()[:16]
                result[key]=dict(id=key,label=label,directory=folder,sha256=file_sha256(summary_path),candidates=labels,
                    source=dict(path=models['source']['path'],sha256=session['source']['sha256'],label=models['source']['label']),
                    target=dict(path=models['target']['path'],sha256=session['target']['sha256'],label=models['target']['label']))
            except (ValueError,KeyError,TypeError,OSError):continue
        return result

    def _presets(self, scan_id, index_sha, alignments):
        seed=self.root/'reports/web-studio/sync-20261021/final-bridge/binding.json'
        paths=[seed,*sorted(self.reviews.glob('*/binding.json'),key=lambda p:p.stat().st_mtime_ns)[-20:]];result=[];seen=set()
        for path in paths:
            try:
                binding=self.mapper.record(read_json(path));sha=file_sha256(path)
                if binding.get('scan_id')!=scan_id or binding.get('decoded_index_sha256')!=index_sha:continue
                matches=[a['id'] for a in alignments.values() if all(
                    self.mapper.resolve(binding[s]['path'])==self.mapper.resolve(a[s]['path']) and binding[s]['sha256']==a[s]['sha256'] for s in ['source','target'])]
                if not matches:continue
                signature=(tuple(matches),tuple(tuple(binding[side]['frame_ids']) for side in ['source','target']))
                if signature in seen:continue
                seen.add(signature)
                result.append(dict(id=hashlib.sha256(str(path).encode()).hexdigest()[:16],sha256=sha,path=str(path),
                    alignment_ids=matches,label='已记录归属 · 固定%d / 移动%d帧'%(len(binding['target']['frame_ids']),len(binding['source']['frame_ids'])),
                    source_text=expression(binding['source']['frame_ids']),target_text=expression(binding['target']['frame_ids']),
                    source_basis=binding['source']['basis'],target_basis=binding['target']['basis'],
                    roi=binding.get('selection_roi_original_scan_mm'),input_sha256=binding.get('input_sha256',{})))
            except (ValueError,KeyError,TypeError,OSError,IndexError):continue
        return result

    def context(self, scan_id):
        index_path,index,digest,ids=self._index(scan_id);alignments=self._alignments(scan_id)
        frames=[]
        for ordinal,rid in enumerate(ids,1):
            folder=index_path.parent/f'frame_{rid:010d}'
            frames.append(dict(ordinal=ordinal,frame_id=str(rid),depth_present=(folder/'frame.npz').is_file(),
                               optimized_pose_present=(folder/'pose_optimized.npy').is_file()))
        return dict(scan_id=scan_id,index_sha256=digest,frames=frames,frame_count=len(ids),
            availability='file_presence_only_full_payload_checked_when_reviewing',
            alignments=[{k:v for k,v in a.items() if k!='directory'} for a in alignments.values()],
            presets=self._presets(scan_id,digest,alignments),
            coordinate_contract='saved_scan_mm',single_scan_only=True)

    def preview(self, request):
        allowed={'scan_id','index_sha256','alignment_id','alignment_sha256','candidate','mode','source_frames','target_frames',
                 'source_basis','target_basis','decision','coordinate_confirmed','roi','preset_id','preset_sha256'}
        if not isinstance(request,dict) or set(request)-allowed:raise ValueError('帧归属表单包含未知字段')
        if request.get('coordinate_confirmed') is not True:raise ValueError('请确认两模型使用原保存扫描毫米坐标，并填写依据')
        scan_id=request.get('scan_id');index_path,index,index_sha,ids=self._index(scan_id,request.get('index_sha256'))
        if request.get('index_sha256')!=index_sha:raise ValueError('需要当前工程索引版本')
        alignments=self._alignments(scan_id);alignment=alignments.get(request.get('alignment_id'))
        if alignment is None:raise ValueError('请选择当前工程已核验的对齐结果')
        if request.get('alignment_sha256')!=alignment['sha256']:raise ValueError('对齐结果已变化，请刷新并重新核验')
        candidate=request.get('candidate')
        if candidate not in alignment['candidates']:raise ValueError('请选择该对齐结果中的明确候选')
        selected={side:frame_selection(request.get(side+'_frames'),request.get('mode'),ids) for side in ['source','target']}
        if set(selected['source'])&set(selected['target']):raise ValueError('固定片段与移动片段不能重复拥有同一原帧')
        for name in ['source_basis','target_basis','decision']:
            if not isinstance(request.get(name),str) or not request[name].strip() or len(request[name])>4000:raise ValueError('请填写帧归属/保存坐标依据与本次选择说明')
        binding=dict(format_version=1,unit='mm',scan_id=scan_id,decoded_index_sha256=index_sha,
            alignment_summary_sha256=alignment['sha256'],decision=request['decision'])
        for side in ['source','target']:
            binding[side]=dict(path=alignment[side]['path'],sha256=alignment[side]['sha256'],frame_ids=selected[side],
                               coordinate_frame='saved_scan_mm',basis=request[side+'_basis'])
        if request.get('roi') is not None:binding['selection_roi_original_scan_mm']=request['roi']
        if request.get('preset_id'):
            preset=next((p for p in self._presets(scan_id,index_sha,alignments) if p['id']==request['preset_id']),None)
            if preset is None or preset['sha256']!=request.get('preset_sha256'):raise ValueError('已记录帧归属发生变化，请重新载入')
            if any(selected[s]!=frame_selection(preset[s+'_text'],'frame_id',ids) for s in ['source','target']) or request.get('roi')!=preset['roi']:
                raise ValueError('帧或ROI已编辑，请取消旧归属引用后重新核验')
            binding['input_sha256']={preset['path']:preset['sha256'],**preset['input_sha256']}
        with self.studio.lock:
            if any(j['status'] in ['queued','running'] for j in self.studio.jobs.values()):raise ValueError('当前有处理任务，请结束后再核验帧归属')
        if not self.studio.processing.acquire(blocking=False):raise ValueError('正在读取点云或处理数据，请稍后核验')
        review_id=uuid.uuid4().hex[:16];folder=self.reviews/review_id
        try:
            folder.mkdir(parents=True);save(folder/'binding.json',binding)
            plan,audit=build_fragment_plan(index_path.parent,folder/'binding.json',alignment['directory'],candidate,self.mapper)
            save(folder/'fragment-plan.json',plan)
            review=dict(id=review_id,status='ready',created_at=now(),scan_id=scan_id,alignment_id=alignment['id'],candidate=candidate,
                decoded=str(index_path.parent),plan_sha256=file_sha256(folder/'fragment-plan.json'),
                binding_sha256=file_sha256(folder/'binding.json'),summary=audit,
                source_frame_ids=[str(i) for i in selected['source']],target_frame_ids=[str(i) for i in selected['target']],
                roi=binding.get('selection_roi_original_scan_mm'),execution_origin='web_form_request_not_proof_of_human_review',
                fusion_parameters=dict(voxel_mm=.6,truncation_mm=2.4,edge_threshold_mm=3.,weight_threshold=3.))
            save(folder/'review.json',review);return dict(review,review_sha256=file_sha256(folder/'review.json'))
        except Exception as error:
            if folder.is_dir():save(folder/'review.json',dict(id=review_id,status='rejected',scan_id=scan_id,error=str(error),created_at=now()))
            if isinstance(error,(ValueError,KeyError,TypeError,OSError,EOFError,zipfile.BadZipFile)):
                raise ValueError('原帧核验未通过：'+str(error)) from error
            raise
        finally:self.studio.processing.release()

    def load_review(self, review_id, expected, review_sha):
        if not isinstance(review_id,str) or not re.fullmatch('[0-9a-f]{16}',review_id):raise ValueError('未知帧归属核验记录')
        folder=self.reviews/review_id;raw=(folder/'review.json').read_bytes()
        if not isinstance(review_sha,str) or hashlib.sha256(raw).hexdigest()!=review_sha:raise ValueError('核验记录已变化，请重新核验')
        record=json.loads(raw.decode('utf-8'))
        if record.get('id')!=review_id:raise ValueError('核验记录身份不一致')
        if record.get('status')!='ready' or record.get('job_id'):raise ValueError('此核验已提交或未通过，请重新核验后执行')
        plan_path=folder/'fragment-plan.json'
        if expected!=record['plan_sha256'] or file_sha256(plan_path)!=expected:raise ValueError('核验计划已变化，请重新核验')
        index_path,_,_,_=self._index(record['scan_id']);decoded=self.mapper.resolve(record['decoded'])
        if decoded!=index_path.parent:raise ValueError('核验记录不属于当前工程原帧目录')
        plan,index,pins=load_fragment_inputs(plan_path,decoded/'index.json',self.mapper)
        if plan['decoded_index_sha256']!=pins[str(decoded/'index.json')]:raise ValueError('工程索引已变化，请重新核验')
        return folder,record,raw

    def submitted(self, folder, record, job_id, expected):
        if file_sha256(folder/'review.json')!=expected:raise ValueError('核验记录在提交期间发生变化')
        record=dict(record,status='submitted',job_id=job_id,submitted_at=now());save(folder/'review.json',record)

"""Replay a completed pinned frame binding with default fusion settings.

Creates a fresh review and task, never reuses a submitted execution token or
creates editing drafts. Resume uses the same recorded review/job IDs.
"""

import argparse
import http.client
import json
from pathlib import Path
import time

from reconstruction_probe.fusion_settings import fusion_settings
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.web_fragments import expression


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8877);p.add_argument('--from-job',required=True);p.add_argument('--out',required=True);p.add_argument('--resume',action='store_true');args=p.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(args.out)
    if root/'reports' not in out.parents or (out.exists() and not args.resume):p.error('Use a new local reports folder or explicitly resume')
    out.mkdir(parents=True,exist_ok=args.resume)
    def save(name,value):(out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    def read(name):return json.loads((out/name).read_text(encoding='utf-8'))
    def api(path,body=None,expected=200):
        c=http.client.HTTPConnection('127.0.0.1',args.port,timeout=120);c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body).encode(),{} if body is None else {'Content-Type':'application/json'});r=c.getresponse();raw=r.read();status=r.status;c.close()
        if status!=expected:raise ValueError((status,path,raw[:1200]))
        return json.loads(raw)
    source=api('/api/jobs/'+args.from_job)
    if source['status']!='completed' or source['kind']!='fragment_fusion':raise ValueError('Use a completed frame-fusion source task')
    folder=mapper.resolve(source['folder']);review_path=folder/'review-original.json';raw=review_path.read_bytes()
    if file_sha256(review_path)!=source['reviewed_record_sha256']:raise ValueError('Source review copy changed')
    original=json.loads(raw.decode('utf-8'));binding=mapper.record(json.loads((folder/'binding.json').read_text(encoding='utf-8')))
    if file_sha256(folder/'binding.json')!=original['binding_sha256']:raise ValueError('Source binding changed')
    context=api('/api/fragments/context?scan='+source['scan_id']);alignment=next((a for a in context['alignments'] if a['id']==original['alignment_id']),None)
    if alignment is None or alignment['sha256']!=binding['alignment_summary_sha256'] or context['index_sha256']!=binding['decoded_index_sha256']:raise ValueError('Source index or alignment revision changed')
    settings=fusion_settings();request=dict(scan_id=source['scan_id'],index_sha256=context['index_sha256'],alignment_id=alignment['id'],alignment_sha256=alignment['sha256'],candidate=original['candidate'],mode='frame_id',source_frames=expression(binding['source']['frame_ids']),target_frames=expression(binding['target']['frame_ids']),source_basis=binding['source']['basis'],target_basis=binding['target']['basis'],decision='Automated default-parameter control of pinned task '+args.from_job+'; not new human correspondence approval.',coordinate_confirmed=True,roi=binding.get('selection_roi_original_scan_mm'),fusion_parameters=settings)
    if (out/'request.json').exists():
        if read('request.json')!=request:raise ValueError('Replay arguments differ from the existing journal')
    else:save('request.json',request)
    if (out/'review.json').exists():review=read('review.json')
    else:review=api('/api/fragments/reviews',request,201);save('review.json',review)
    if (out/'job.json').exists():job=read('job.json')
    else:job=api('/api/jobs',dict(kind='fragment_fusion',review_id=review['id'],plan_sha256=review['plan_sha256'],review_sha256=review['review_sha256']),202);save('job.json',job)
    while True:
        job=api('/api/jobs/'+job['id']);save('job-progress.json',job)
        if job['status'] not in ['queued','running']:break
        print(json.dumps(dict(job_id=job['id'],status=job['status'])),flush=True);time.sleep(5)
    if job['status']!='completed':raise ValueError('Control task failed: '+str(job.get('error')))
    result=json.loads((mapper.resolve(job['folder'])/'result/summary.json').read_text(encoding='utf-8'));source_result=json.loads((folder/'result/summary.json').read_text(encoding='utf-8'))
    if result['fusion_parameters']!=settings or result['selected_depth_with_frame_ids_sha256']!=source_result['selected_depth_with_frame_ids_sha256'] or result['selected_frames']!=source_result['selected_frames']:raise ValueError('Control parameters or selected source pixels changed')
    record=dict(job_id=job['id'],review_id=review['id'],source_job_id=args.from_job,settings=settings,selected_frames=result['selected_frames'],source_pixel_sha256=result['selected_depth_with_frame_ids_sha256'],source_pins={str(review_path):source['reviewed_record_sha256'],str(folder/'binding.json'):original['binding_sha256']},code_sha256=file_sha256(Path(__file__)),result=result)
    save('summary.json',record);print(json.dumps({k:record[k] for k in ['job_id','review_id','settings','selected_frames','source_pixel_sha256']}))


if __name__=='__main__':main()

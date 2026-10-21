"""Replay a previously frozen real segment correction through the generic bridge.

This is an automated existing-candidate replay, not human landmark selection
and not a new accuracy experiment. All original scan files remain read-only.
"""

import os
os.environ.setdefault('OMP_NUM_THREADS', '4')

import argparse
import json
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile

import numpy as np
from scipy.spatial import cKDTree
from PIL import Image, ImageDraw, ImageFont

from reconstruction_probe.fragment_plan import compile_fragment_plan
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.ply_layout import map_ply_vertices
from reconstruction_probe.workflow import run_workflow
from build_workflow_run_report import build
from build_studio_comparison import build as build_comparison


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def xyz(path):
    records, _ = map_ply_vertices(path)
    return np.column_stack([records[key] for key in ['x', 'y', 'z']]).astype(float)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, default=Path('reports/range2-study-20261018'))
    parser.add_argument('--out', required=True)
    parser.add_argument('--node', default=shutil.which('node'))
    args = parser.parse_args()
    if not args.node:parser.error('Supply a Node executable with --node')
    root = Path(__file__).resolve().parents[1]; mapper = PathMapper(root)
    study = mapper.resolve(args.study); out = mapper.resolve_output(args.out)
    if out.exists() or root/'reports' not in out.parents:
        parser.error('Use a new directory strictly within workspace/reports')
    prior = study/'experiments/cup-first-segment-component'
    old_plan_path = prior/'fragment-plan.json'; old_plan = read(old_plan_path)
    graph_path = study/'experiments/cup-segment-pose-graph/summary.json'; graph = read(graph_path)
    decoded = study/'decoded'/old_plan['scan_id']; index_path = decoded/'index.json'; index = read(index_path)
    compile_fragment_plan(old_plan, index['scan_id'], file_sha256(index_path), [row['id'] for row in index['frames']])
    for name, expected in old_plan['input_sha256'].items():
        if file_sha256(mapper.resolve(name)) != expected:
            raise ValueError('Frozen experiment provenance changed: '+name)
    fragments = {row['fragment_id']:row for row in old_plan['fragments']}
    if set(fragments) != {0, 1} or fragments[1]['parent_fragment_id'] != 0 or not np.array_equal(fragments[0]['transform_to_parent_mm'], np.eye(4)):
        raise ValueError('Expected the previously frozen 1->0 local component')
    segments = {row['fragment_id']:row for row in graph['segments']}
    for rid in [0, 1]:
        if fragments[rid]['frame_ids'] != segments[rid]['all_frame_ids']:
            raise ValueError('Frozen plan disagrees with segmentation ownership')
    paths = {side:mapper.resolve(segments[rid]['path']) for side,rid in [('target',0),('source',1)]}
    out.mkdir(parents=True)
    matrix = fragments[1]['transform_to_parent_mm']
    reference = out/'candidates/summary.json'
    save(reference, dict(unit='mm', candidates=[dict(label='frozen_training_1_to_0',transform=matrix)],
        provenance='Previously frozen training correction; scripted replay, not manual landmark selection',
        input_sha256={str(p):file_sha256(p) for p in [old_plan_path, graph_path]}))
    session = dict(format_version=1, unit='mm', kind='existing_candidate',
        source=dict(path=str(paths['source']),sha256=file_sha256(paths['source']),fragment_id=1),
        target=dict(path=str(paths['target']),sha256=file_sha256(paths['target']),fragment_id=0),
        candidate_label='frozen_training_1_to_0',candidate_reference=dict(path=str(reference),sha256=file_sha256(reference)),
        transform_source_to_target=matrix,
        provenance='Automated replay of a frozen existing candidate; no human correspondence selection was performed')
    session_path = out/'replay-session.json';save(session_path, session)
    subprocess.run([sys.executable,'-m','reconstruction_probe.path_mapping','--workspace',str(root),
        '--session',str(session_path),'--out',str(out/'alignment')], cwd=root, check=True)
    subprocess.run([sys.executable,str(root/'scripts/build_landmark_workbench.py'),
        '--target-cloud',str(paths['target']),'--source-cloud',str(paths['source']),
        '--unit','mm','--registration',str(reference.parent),'--out',str(out/'workbench.html'),
        '--notes','失败工程片段1→0的已冻结候选回放。没有代替人工选点；原帧归属另见binding.json。'],cwd=root,check=True)
    alignment = out/'alignment'
    binding = dict(format_version=1,unit='mm',scan_id=index['scan_id'],decoded_index_sha256=file_sha256(index_path),
        alignment_summary_sha256=file_sha256(alignment/'summary.json'),
        decision='Reproduce the frozen 114-frame exploratory component via the generic binding bridge. Scripted candidate replay, not human point selection, not whole-scan repair or new accuracy evidence.',
        selection_roi_original_scan_mm=old_plan['selection_roi_original_scan_mm'],
        input_sha256={str(p):file_sha256(p) for p in [old_plan_path, graph_path]})
    for side,rid in [('target',0),('source',1)]:
        binding[side] = dict(path=str(paths[side]),sha256=file_sha256(paths[side]),
            frame_ids=fragments[rid]['frame_ids'],coordinate_frame='saved_scan_mm',
            basis='segment-%d-training-mm.ply was generated from the frozen graph training subset in original saved scan coordinates; apply to the explicit all_frame_ids of the same rigid fragment. All selected frames now enter the demonstration.' % rid)
    binding_path=out/'binding.json';save(binding_path,binding)
    workflow=dict(format_version=1,name='真实片段：核验对应点结果→原帧绑定→两组重融合',
        input_sha256={str(p):file_sha256(p) for p in [binding_path,index_path,alignment/'summary.json']},nodes=[
            dict(id='bind',tool='fragments.plan',parameters=dict(decoded=str(decoded),alignment=str(alignment),binding=str(binding_path),candidate='selected_frozen_training_1_to_0')),
            dict(id='saved',tool='fragments.fuse',parameters=dict(decoded=str(decoded),plan=dict(node='bind',path='fragment-plan.json'),saved_control=True)),
            dict(id='corrected',tool='fragments.fuse',parameters=dict(decoded=str(decoded),plan=dict(node='bind',path='fragment-plan.json')))])
    save(out/'workflow-plan.json',workflow)
    state=run_workflow(workflow,root,out/'workflow',on_event=lambda event:print(json.dumps(event,ensure_ascii=False),flush=True))
    build(out/'workflow')
    if state['status']!='completed':
        raise ValueError('Real bridge workflow did not complete; inspect its recorded logs')
    results=[read(out/'workflow/nodes'/label/'summary.json') for label in ['saved','corrected']]
    old_results=read(prior/'summary.json')['results']
    for key in ['selected_frames','selected_frame_ids','selected_depth_with_frame_ids_sha256']:
        if results[0][key]!=results[1][key] or results[0][key]!=old_results[0][key]:
            raise ValueError('Source frame/pixel contract differs across arms or frozen reference: '+key)
    reproductions=[]
    for label,row,old in zip(['saved','corrected'],results,old_results):
        actual=xyz(Path(row['path'])); previous=xyz(mapper.resolve(old['path']))
        forward=cKDTree(previous).query(actual,workers=1)[0]; reverse=cKDTree(actual).query(previous,workers=1)[0]
        max_distance=float(max(forward.max(),reverse.max()))
        reproductions.append(dict(label=label,points=len(actual),previous_points=len(previous),
            full_bidirectional_max_distance_mm=max_distance,equivalent_within_001mm=max_distance<=.001,
            meaning='numerical reproduction of the prior output, not physical scan accuracy'))
    if not all(row['equivalent_within_001mm'] for row in reproductions):
        raise ValueError('Bridge changed the frozen reconstruction; retain outputs for investigation')
    summary=dict(status='real_saved_frame_bridge_reproduced_frozen_component',execution='scripted_existing_candidate_replay_not_manual_selection',
        scan_id=index['scan_id'],selected_frames=results[0]['selected_frames'],omitted_original_frames=len(index['frames'])-results[0]['selected_frames'],
        selected_depth_with_frame_ids_sha256=results[0]['selected_depth_with_frame_ids_sha256'],
        same_original_frames_and_roi_pixels=True,reproductions=reproductions,results=results,
        input_sha256={str(p):file_sha256(p) for p in [old_plan_path,graph_path,binding_path,alignment/'summary.json',out/'workflow-plan.json']},
        limitations=['This reproduces a prior partial result through a new generic execution path; it is not new geometric improvement.',
            'All 114 selected frames are integrated; previous heldout labels are no longer independent evaluation for these demonstration surfaces.',
            'Other 222 saved records remain untouched. The full failed 336-record scan is still unresolved.',
            'The Web manual frame-binding editor, multi-project binding and project undo history remain unimplemented.'])
    payload=build_comparison(['原位姿控制组='+results[0]['path'],'片段校正候选='+results[1]['path']],
        out/'review.html','失败杯子片段0的保存扫描坐标',
        '同一114帧、同一原始ROI像素，完整重走通用桥接。复现已有局部结果，未新增人工选点；其余222帧未合并，失败扫描尚未整体修复。',
        '对应点结果→原帧绑定→重融合')
    raster_controls=[];cache=root/'.cache';cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fragment-bridge-render-',dir=cache) as temporary:
        temporary=Path(temporary)
        for i,row in enumerate(payload['clouds']):
            fixture=temporary/f'{i}.json';raw=temporary/f'{i}.rgba';save(fixture,row)
            result=subprocess.run([args.node,'tests/check_point_viewer_cpu.cjs',str(fixture),str(raw),'depth'],cwd=root,capture_output=True,text=True,encoding='utf-8',check=True)
            control=json.loads(result.stdout);raster_controls.append(control['actual_http_payload'])
            Image.frombytes('RGBA',(800,600),raw.read_bytes()).convert('RGB').save(out/f'cpu-view-{i}.png')
    image=Image.new('RGB',(1200,570),(12,20,32));draw=ImageDraw.Draw(image)
    font=lambda size:ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',size)
    draw.text((18,10),'114帧真实重融合 · 通用桥接复现',font=font(24),fill='#e2edf9')
    draw.text((18,47),'相同原始像素；这是实际统一查看器的CPU绘制，非浏览器截图或新增精度证据。',font=font(15),fill='#aac5db')
    for i,row in enumerate(payload['clouds']):
        draw.text((i*600+15,82),row['label']+f" · {row['originalPoints']:,} 点",font=font(19),fill='#9cddc5')
        with Image.open(out/f'cpu-view-{i}.png') as picture:image.paste(picture.resize((580,435)),(i*600+10,115))
    image.save(out/'comparison.png')
    summary['display_verification']=dict(source='generated embedded payload -> actual shared PointViewer -> CPU pixels',
        cases=raster_controls,actual_browser_verified=False,actual_gpu_verified=False)
    summary['implementation_sha256']={str(p.relative_to(root)).replace(chr(92),'/'):file_sha256(p) for p in [
        root/'scripts/check_fragment_bridge_live.py',root/'scripts/build_fragment_plan_from_alignment.py',
        root/'scripts/reconstruct_fragment_plan.py',root/'src/reconstruction_probe/fragment_bridge.py',
        root/'src/reconstruction_probe/fragment_plan.py',
        root/'web/studio/point_viewer.js',root/'scripts/build_studio_comparison.py']}
    save(out/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ['status','selected_frames','same_original_frames_and_roi_pixels','reproductions']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()

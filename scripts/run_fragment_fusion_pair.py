"""Execute the reviewed plan as a saved-pose control and a corrected fusion."""

import argparse
import json
from pathlib import Path

from reconstruction_probe.fragment_plan import load_fragment_inputs
from reconstruction_probe.fusion_settings import fusion_settings
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.workflow import run_workflow
from build_workflow_run_report import build as build_report
from build_studio_comparison import build as build_comparison


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['decoded','plan','plan-sha256','out']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--cancel-file');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root)
    decoded=mapper.resolve(args.decoded);plan_path=mapper.resolve(args.plan);out=mapper.resolve_output(args.out)
    if out.exists() or root/'reports' not in out.parents:parser.error('Use a new folder strictly within workspace/reports')
    if file_sha256(plan_path)!=args.plan_sha256:raise ValueError('Reviewed fragment plan changed before execution')
    plan,index,pins=load_fragment_inputs(plan_path,decoded/'index.json',mapper)
    if pins[str(plan_path)]!=args.plan_sha256:raise ValueError('Reviewed plan changed during loading')
    parameters=fusion_settings(plan.get('fusion_parameters'))
    for fragment in plan['fragments']:
        for rid in fragment['frame_ids']:
            for name in ['frame.npz','pose_optimized.npy']:
                payload=str((decoded/f'frame_{rid:010d}'/name).resolve())
                if payload not in pins:raise ValueError('Reviewed payload pins do not belong to the selected decoded directory')
    workflow=dict(format_version=1,name='已核验原帧：原位姿控制与片段校正重融合',input_sha256=pins,nodes=[
        dict(id='saved',tool='fragments.fuse',parameters=dict(decoded=str(decoded),plan=str(plan_path),saved_control=True)),
        dict(id='corrected',tool='fragments.fuse',parameters=dict(decoded=str(decoded),plan=str(plan_path)))])
    state=run_workflow(workflow,root,out,mapper.resolve_output(args.cancel_file) if args.cancel_file else None,
        on_event=lambda event:print(json.dumps(event,ensure_ascii=False),flush=True))
    build_report(out)
    if state['status']!='completed':
        print(json.dumps(dict(status=state['status'],comparison_created=False)),flush=True)
        if state['status']=='failed':raise SystemExit(1)
        return
    results=[read(out/'nodes'/label/'summary.json') for label in ['saved','corrected']]
    if any(row.get('fusion_parameters')!=parameters for row in results):raise ValueError('Fusion arms differ from reviewed parameters')
    for key in ['selected_frames','selected_frame_ids','selected_depth_with_frame_ids_sha256']:
        if results[0][key]!=results[1][key]:raise ValueError('Control and corrected arms used different original frames/pixels')
    if file_sha256(plan_path)!=args.plan_sha256:raise ValueError('Reviewed plan changed during fusion')
    build_comparison(['原位姿控制组='+results[0]['path'],'片段校正候选='+results[1]['path']],out/'review.html',
        '显式片段目标保存坐标 · '+index['scan_id'],
        plan['decision']+' 两组使用同一批原帧与原ROI像素；表面变化不单独证明物理精度改善。',
        '原帧重融合 · 控制组与校正组')
    summary=dict(status='reviewed_fragment_fusion_pair_candidate_not_promoted',scan_id=index['scan_id'],
        fusion_parameters=parameters,selected_frames=results[0]['selected_frames'],same_original_frames_and_roi_pixels=True,
        selected_depth_with_frame_ids_sha256=results[0]['selected_depth_with_frame_ids_sha256'],
        reviewed_plan_sha256=args.plan_sha256,results=results,
        limitations=['Frame ownership and saved-coordinate basis came from the recorded form; no physical correspondence is inferred.',
            'All selected frames enter these surfaces; they do not form an independent heldout evaluation.',
            'Unselected source records remain unchanged. A completed workflow does not certify geometric accuracy.'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(status=summary['status'],frames=summary['selected_frames'],same_pixels=True)),flush=True)


if __name__=='__main__':main()

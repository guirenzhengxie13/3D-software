"""Complete a frozen 2x2 voxel/truncation experiment without geometry acceptance."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from build_studio_comparison import build
from reconstruction_probe.fusion_settings import executed_fusion_settings,fusion_settings
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.ply_layout import map_ply_vertices


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--v06-t32-job',required=True);p.add_argument('--v08-t24-job',required=True);p.add_argument('--out',required=True);args=p.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(args.out);pins={}
    if out.exists() or root/'reports' not in out.parents:p.error('Use a new local reports folder')
    def pin(path,expected=None):
        path=mapper.resolve(path);digest=file_sha256(path)
        if expected is not None and digest!=expected:raise ValueError('Pinned input changed: '+str(path))
        if str(path) in pins and pins[str(path)]!=digest:raise ValueError('Input changed during analysis')
        pins[str(path)]=digest;return path
    def read(path,expected=None):
        path=pin(path,expected);raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=pins[str(path)]:raise ValueError('Input changed during read')
        return mapper.record(json.loads(raw.decode('utf-8')))
    def xyz(path):
        rows,_=map_ply_vertices(path);points=np.column_stack([rows[k] for k in ['x','y','z']]).astype(float)
        if not len(points) or not np.isfinite(points).all():raise ValueError('Invalid surface')
        return points
    voxel_report=root/'reports/range2-study-20261018/experiments/tsdf-voxel-evidence-20261026'
    observed=read(voxel_report/'summary.json')
    for name,digest in observed['input_sha256'].items():pin(name,digest)
    core_files=['scripts/reconstruct_scans.py','src/reconstruction_probe/tensor_tsdf.py','src/reconstruction_probe/fusion_settings.py']
    for name in core_files:pin(root/name,observed['input_sha256'][str(root/name)])
    configs=[('v06-t24','8a0b007863984e19',.6,2.4),('v06-t32',args.v06_t32_job,.6,3.2),('v08-t24',args.v08_t24_job,.8,2.4),('v08-t32','8197aff465a34cf7',.8,3.2)]
    loaded={};metadata=[]
    for key,jid,voxel,truncation in configs:
        if len(jid)!=16 or any(c not in '0123456789abcdef' for c in jid):raise ValueError('Need recorded job ID')
        folder=root/'reports/web-studio/runs'/jid;job=read(folder/'job.json')
        if job['status']!='completed' or job['kind']!='fragment_fusion':raise ValueError('Use a completed paired fusion')
        review=read(folder/'review-original.json',job['reviewed_record_sha256']);pair=read(folder/'result/summary.json');state=read(folder/'result/state.json');settings=fusion_settings(review['fusion_parameters'])
        if settings!=dict(voxel_mm=voxel,truncation_mm=truncation,edge_threshold_mm=3.,weight_threshold=3.):raise ValueError('Unexpected factorial settings')
        if pair['reviewed_plan_sha256']!=job['reviewed_plan_sha256'] or state['status']!='completed':raise ValueError('Completion/provenance mismatch')
        evidence=[]
        for arm in ['saved','corrected']:
            base=folder/'result/nodes'/arm;node=next(n for n in state['nodes'] if n['id']==arm)
            if node['status']!='completed':raise ValueError('Incomplete workflow node')
            summary=read(base/'summary.json',node['output_sha256']['summary.json']);path=mapper.resolve(summary['path']);pin(path,node['output_sha256'][path.relative_to(base).as_posix()]);points=xyz(path)
            applied=pin(base/'applied-poses.npz',node['output_sha256']['applied-poses.npz'])
            with np.load(applied,allow_pickle=False) as z:poses={k:z[k] for k in z.files}
            payload={name:sha for name,sha in summary['input_sha256'].items() if Path(name).name in ['frame.npz','pose_optimized.npy','index.json']}
            for name,sha in payload.items():pin(name,sha)
            reconstruction=path.parent/'reconstruction.json'
            if key in ['v06-t32','v08-t24']:
                actual=executed_fusion_settings(read(reconstruction,node['output_sha256'][reconstruction.relative_to(base).as_posix()]))
                if actual!=settings or summary['effective_fusion_parameters']!=settings:raise ValueError('Requested and actual parameters differ')
                entry=pin(root/'scripts/reconstruct_fragment_plan.py',node['implementation_sha256'])
                method='actual_volume_diagnostics_and_pinned_workflow_entry'
            else:
                case=next(c for c in observed['cases'] if c['case']==('fine' if voxel==.6 else 'coarse')+'-'+arm)
                replay_path=pin(voxel_report/case['case']/'reconstruction/scan_20261018131222/tsdf_pointcloud_mm.ply');replay=xyz(replay_path)
                distance=max(float(cKDTree(points).query(replay,workers=1)[0].max()),float(cKDTree(replay).query(points,workers=1)[0].max()))
                current=read(voxel_report/case['case']/'reconstruction/scan_20261018131222/reconstruction.json')
                if len(replay)!=len(points) or distance!=0 or case['full_pointset_bidirectional_max_mm']!=0 or executed_fusion_settings(current)!=settings:raise ValueError('Current-core baseline replay differs')
                method='current_core_read_only_replay_exact_whole_pointset'
            if summary['fusion_parameters']!=settings or summary['selected_depth_with_frame_ids_sha256']!=pair['selected_depth_with_frame_ids_sha256']:raise ValueError('Arm source/settings differ')
            loaded[key,arm]=dict(path=path,xyz=points,poses=poses,payload=payload,summary=summary,pair=pair)
            evidence.append(dict(arm=arm,points=len(points),effective_parameters=settings,execution_evidence=method))
        metadata.append(dict(key=key,job=jid,settings=settings,arms=evidence))
    source=loaded['v06-t24','saved'];pixel=source['pair']['selected_depth_with_frame_ids_sha256'];frame_ids=source['summary']['selected_frame_ids']
    for arm in ['saved','corrected']:
        baseline=loaded['v06-t24',arm]
        for key,_,_,_ in configs:
            item=loaded[key,arm]
            if item['payload']!=baseline['payload'] or item['summary']['selected_frame_ids']!=frame_ids or item['pair']['selected_depth_with_frame_ids_sha256']!=pixel:raise ValueError('Source frames/pixels differ')
            if set(item['poses'])!=set(baseline['poses']) or any(not np.array_equal(item['poses'][k],baseline['poses'][k]) for k in baseline['poses']):raise ValueError('Applied poses differ')
    for name in ['scripts/analyze_tsdf_parameter_factorial.py','scripts/build_studio_comparison.py','web/studio/tsdf_parameter_factorial.html','web/studio/comparison.html','web/studio/point_viewer.js','web/landmark-workbench/registration_math.js','web/landmark-workbench/point_raster.js']:pin(root/name)
    out.mkdir(parents=True);arms=[]
    comparisons=[('voxel-t24','voxel_mm','v06-t24','v08-t24'),('voxel-t32','voxel_mm','v06-t32','v08-t32'),('trunc-v06','truncation_mm','v06-t24','v06-t32'),('trunc-v08','truncation_mm','v08-t24','v08-t32')]
    def describe(values):return dict(points=len(values),median_mm=float(np.median(values)),p95_mm=float(np.quantile(values,.95)),maximum_mm=float(values.max()),within_1mm_fraction=float(np.mean(values<=1.)))
    for arm in ['saved','corrected']:
        pairs=[]
        for name,parameter,left,right in comparisons:
            a,b=loaded[left,arm],loaded[right,arm];dist=[cKDTree(b['xyz']).query(a['xyz'],workers=1)[0],cKDTree(a['xyz']).query(b['xyz'],workers=1)[0]]
            settings={c['key']:c['settings'] for c in metadata};changed=[k for k in settings[left] if settings[left][k]!=settings[right][k]]
            if changed!=[parameter]:raise ValueError('Comparison must change exactly one parameter')
            page=out/f'{arm}-{name}.html';notes='相同114条保存记录、ROI像素与应用位姿；只改变'+parameter+'。最近邻距离不是物理误差，预览可能抽样，未接受新模型。'
            build([left+'='+str(a['path']),right+'='+str(b['path'])],page,'same saved scan mm / '+source['summary']['scan_id'],notes,'单参数对照 · '+arm+' · '+name,budget=60000)
            np.savez_compressed(out/f'{arm}-{name}.npz',left_to_right_mm=dist[0],right_to_left_mm=dist[1])
            pairs.append(dict(key=name,parameter=parameter,left=left,right=right,left_points=len(a['xyz']),right_points=len(b['xyz']),point_count_delta=len(b['xyz'])-len(a['xyz']),left_to_right=describe(dist[0]),right_to_left=describe(dist[1]),page=page.name))
        targets=next(c for c in observed['cases'] if c['case']=='coarse-'+arm)['targets'];critical=[]
        for target in targets:
            point=np.array(target['reference_mm']);nearest=[]
            for key,_,_,_ in configs:
                item=loaded[key,arm];distance,index=cKDTree(item['xyz']).query(point,workers=1);nearest.append(dict(config=key,nearest_mm=float(distance),nearest_vertex_id=int(index)))
            critical.append(dict(reference_variant=target['reference_variant'],reference_vertex_id=target['reference_vertex_id'],reference_mm=point.tolist(),nearest=nearest))
        counts={key:len(loaded[key,arm]['xyz']) for key,_,_,_ in configs};interaction=(counts['v08-t32']-counts['v08-t24'])-(counts['v06-t32']-counts['v06-t24'])
        arms.append(dict(arm=arm,counts=counts,comparisons=pairs,critical_locations=critical,count_difference_of_differences=interaction))
    for name,digest in pins.items():
        if file_sha256(Path(name))!=digest:raise ValueError('Input changed while comparing')
    summary=dict(status='frozen_2x2_parameter_response_not_physical_accuracy',selected_frames=len(frame_ids),original_pixel_sha256=pixel,same_applied_pose_arrays=True,source_payload_files_per_arm=len(source['payload']),configs=metadata,arms=arms,input_sha256=pins,limits=['Only voxel or truncation changes along each reported comparison; both historical controls are exactly reproduced by current-core read-only replays.','Workflow nodes record the entry-script SHA; nested core hashes are checked against the read-only observer at analysis time, not claimed as retroactive per-task module attestations.','Point count and nearest surface distances are responses of this fixed component, not geometric truth, true correspondences, heldout accuracy or optimal parameter recommendations.','The difference of count differences is descriptive for one object; no independent repetitions or statistical uncertainty.','All 114 frames enter all surfaces; the remaining 222 saved records are excluded. No whole failed-scan repair or automatic model promotion.'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    template=(root/'web/studio/tsdf_parameter_factorial.html').read_text(encoding='utf-8');html=template.replace('__FACTORIAL_DATA__',json.dumps(summary,ensure_ascii=False,allow_nan=False).replace('<',chr(92)+'u003c'),1);(out/'review.html').write_text(html,encoding='utf-8',newline='\n')
    print(json.dumps(dict(out=str(out),arms=[dict(arm=a['arm'],counts=a['counts'],critical=a['critical_locations'],count_interaction=a['count_difference_of_differences']) for a in arms],pinned_inputs=len(pins))),flush=True)


if __name__=='__main__':main()

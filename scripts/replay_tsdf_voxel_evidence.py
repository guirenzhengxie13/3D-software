"""Observe actual voxel TSDF/weights after each frozen-frame integration.

A process-local read-only observer subclasses the production adapter; original
integration/extraction stays unchanged. Each replay must reproduce its full
reference point set before its diagnostic is published.
"""

import os
os.environ.setdefault('OMP_NUM_THREADS','4')
import argparse
from contextlib import contextmanager
import gc
import hashlib
import json
from pathlib import Path

import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree

from experiment_color_seeded_roi import optical_points
from reconstruct_scans import reconstruct,optical_to_pose_axes
from reconstruction_probe import tensor_tsdf
from reconstruction_probe.fragment_plan import compile_fragment_plan,load_fragment_inputs
from reconstruction_probe.fusion_settings import executed_fusion_settings
from reconstruction_probe.multi_scan import FrameKey,rigid
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.ply_layout import map_ply_vertices
from reconstruction_probe.tsdf_trace import lattice_edges,neighborhood_voxels,read_voxels,edge_evidence


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);p.add_argument('--cases',default='coarse-saved,fine-saved,coarse-corrected,fine-corrected');args=p.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(args.out)
    if out.exists() or root/'reports' not in out.parents:p.error('Use a new local reports folder')
    requested=args.cases.split(',');available={f'{v}-{a}' for v in ['fine','coarse'] for a in ['saved','corrected']}
    if len(set(requested))!=len(requested) or any(c not in available for c in requested):p.error('Unknown/duplicate replay case')
    pins={}
    def pin(path,expected=None):
        path=mapper.resolve(path);sha=file_sha256(path)
        if expected is not None and sha!=expected:raise ValueError('Frozen reference changed: '+str(path))
        if str(path) in pins and pins[str(path)]!=sha:raise ValueError('Input changed during replay')
        pins[str(path)]=sha;return path
    def read(path,expected=None):
        path=pin(path,expected);raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=pins[str(path)]:raise ValueError('Input changed during read')
        return mapper.record(json.loads(raw.decode('utf-8')))
    study=root/'reports/range2-study-20261018/experiments/fusion-setting-response-20261025';baseline=read(study/'summary.json');tail=read(study/'tail-verified/summary.json')
    for path in [Path(__file__),root/'scripts/reconstruct_scans.py',root/'src/reconstruction_probe/tensor_tsdf.py',root/'src/reconstruction_probe/tsdf_trace.py',root/'src/reconstruction_probe/fusion_settings.py',root/'scripts/experiment_color_seeded_roi.py']:pin(path)
    reference=read(root/'.cache/open3d-v0.20.0-reference/manifest.json')
    for row in reference['files']:pin(row['path'],row['sha256'])
    out.mkdir(parents=True);results=[];OriginalVolume=tensor_tsdf.TensorTSDFVolume
    for case in requested:
        variant,arm=case.split('-');folder=out/case;folder.mkdir();job_id=baseline[variant+'_job'];job_folder=root/'reports/web-studio/runs'/job_id;job=read(job_folder/'job.json')
        source_review=read(job_folder/'review-original.json',job['reviewed_record_sha256']);decoded=mapper.resolve(source_review['decoded']);command=job['command_argv'];plan_path=mapper.resolve(command[command.index('--plan')+1]);pin(plan_path,job['reviewed_plan_sha256'])
        plan,index,plan_pins=load_fragment_inputs(plan_path,decoded/'index.json',mapper)
        if plan_pins[str(plan_path)]!=job['reviewed_plan_sha256']:raise ValueError('Parsed plan changed')
        for name,sha in plan_pins.items():pin(name,sha)
        compiled=compile_fragment_plan(plan,index['scan_id'],plan_pins[str(decoded/'index.json')],[r['id'] for r in index['frames']]);settings=compiled['fusion_parameters'];v=settings['voxel_mm'];saved_control=arm=='saved'
        source_pair=read(job_folder/'result/summary.json');source_summary=source_pair['results'][0 if saved_control else 1];reference_path=mapper.resolve(source_summary['path']);state=read(job_folder/'result/state.json');node=next(n for n in state['nodes'] if n['id']==arm);node_root=job_folder/'result/nodes'/arm;pin(reference_path,node['output_sha256'][reference_path.relative_to(node_root).as_posix()])
        targets=next(a for a in tail['arms'] if a['label']==arm)['points'];target_points=[np.array(q['xyz_mm'],float) for q in targets]
        coords=np.unique(np.concatenate([neighborhood_voxels(point,v) for point in target_points]),axis=0);labels=[q['variant'] for q in targets]
        original={rid:rigid(np.load(decoded/f'frame_{rid:010d}/pose_optimized.npy',allow_pickle=False)) for rid in compiled['selected_frame_ids']}
        corrections={fragment:(np.eye(4) if saved_control else matrix) for fragment,matrix in compiled['corrections'].items()};overrides={rid:corrections[compiled['ownership'][FrameKey(index['scan_id'],rid)]]@pose for rid,pose in original.items()}
        bounds=np.array(plan['selection_roi_original_scan_mm'],float);selection_digest=hashlib.sha256();current={'frame':None};captured=[]
        class ObservedVolume(OriginalVolume):
            def __init__(self,*a,**kw):
                super().__init__(*a,**kw);self.observed_frames=[];self.states=[read_voxels(self.grid,coords)];captured.append(self)
            def integrate(self,*a,**kw):
                super().integrate(*a,**kw);self.observed_frames.append(current['frame']);self.states.append(read_voxels(self.grid,coords))
        def selection(depth,pose,rid):
            current['frame']=rid;result=depth.copy();ids,xyz=optical_points(depth,index['intrinsics']['Pl']);native=(xyz*optical_to_pose_axes(index))@original[rid][:3,:3].T+original[rid][:3,3];inside=np.all((native>=bounds[0])&(native<=bounds[1]),axis=1);result.ravel()[ids[~inside]]=0;selection_digest.update(np.array([rid],'<u8').tobytes()+result.astype('<f4').tobytes());return result,int((~inside).sum())
        tensor_tsdf.TensorTSDFVolume=ObservedVolume
        try:
            report=reconstruct(decoded,folder/'reconstruction',settings['voxel_mm'],settings['truncation_mm'],settings['edge_threshold_mm'],1,True,pose_overrides=overrides,frame_depth_filter=selection,evaluate_vendor=False,bounds_override_mm=bounds,tsdf_backend='tensor',tsdf_weight_threshold=settings['weight_threshold'],coordinate_frame='read_only_voxel_observer_'+index['scan_id'],reconstruction_note='Frozen diagnostic replay; observer only reads actual TSDF and weight tensors.')
        finally:tensor_tsdf.TensorTSDFVolume=OriginalVolume
        if len(captured)!=1:raise ValueError('Expected a single observed volume')
        volume=captured.pop();actual=executed_fusion_settings(report)
        if actual!=settings or selection_digest.hexdigest()!=source_pair['selected_depth_with_frame_ids_sha256']:raise ValueError('Actual parameters or source pixels differ')
        if volume.observed_frames!=[r['id'] for r in index['frames'] if r['id'] in set(compiled['selected_frame_ids'])]:raise ValueError('Captured original frame order differs')
        records,_=map_ply_vertices(reference_path);reference_xyz=np.column_stack([records[n] for n in ['x','y','z']]).astype(float);del records
        replay_path=folder/'reconstruction'/index['scan_id']/'tsdf_pointcloud_mm.ply';records,_=map_ply_vertices(replay_path);replay=np.column_stack([records[n] for n in ['x','y','z']]).astype(float);del records
        errors=[cKDTree(reference_xyz).query(replay,workers=1)[0],cKDTree(replay).query(reference_xyz,workers=1)[0]]
        if len(replay)!=len(reference_xyz) or max(e.max() for e in errors)>1e-7:raise ValueError('Read-only observer did not reproduce complete reference point set')
        weights=np.array([s['weight'] for s in volume.states]);tsdfs=np.array([s['tsdf'] for s in volume.states]);allocated=np.array([s['allocated'] for s in volume.states]);frames=volume.observed_frames;final=volume.states[-1];lookup={tuple(c):i for i,c in enumerate(coords)}
        np.savez_compressed(folder/'voxel-timeline.npz',coordinates=coords,tsdf=tsdfs,weight=weights,allocated=allocated,frame_ids=np.array(frames,dtype='<u8'))
        targets_out=[]
        for point,label in zip(target_points,labels):
            local=neighborhood_voxels(point,v);present={tuple(c) for c in local};edges=[]
            for a in local:
                for axis in range(3):
                    b=a.copy();b[axis]+=1
                    if tuple(b) in present:edges.append(dict(axis=axis,start=a.tolist(),end=b.tolist()))
            evaluated=[edge_evidence(e,final,v,settings['weight_threshold'],point) for e in edges]
            counts=dict(local_edges=len(evaluated),allocated_pairs=sum(e['allocated'] for e in evaluated),opposite_sign=sum(e['opposite_sign'] for e in evaluated),strict_weight_gate=sum(e['strict_weight_gate'] for e in evaluated),extractable=sum(e['point_extractable'] for e in evaluated),opposite_but_weight_rejected=sum(e['opposite_sign'] and not e['strict_weight_gate'] for e in evaluated))
            exact=lattice_edges(point,v);ordered=exact+sorted(edges,key=lambda e:(not edge_evidence(e,final,v,settings['weight_threshold'])['point_extractable'],not edge_evidence(e,final,v,settings['weight_threshold'])['opposite_sign'],edge_evidence(e,final,v,settings['weight_threshold'],point)['distance_to_reference_mm'] if edge_evidence(e,final,v,settings['weight_threshold'],point)['distance_to_reference_mm'] is not None else float(np.linalg.norm((np.array(e['start'])+np.array(e['end']))*.5*v-point))))
            chosen=[];seen=set()
            for edge in ordered:
                key=(tuple(edge['start']),edge['axis'])
                if key in seen:continue
                seen.add(key);chosen.append(edge)
                if len(chosen)>=8:break
            selected=[]
            for edge in chosen:
                ids=[lookup[tuple(edge[k])] for k in ['start','end']];evidence=edge_evidence(edge,final,v,settings['weight_threshold'],point)
                timeline=[]
                for n,snapshot in enumerate(volume.states):
                    row=edge_evidence(edge,snapshot,v,settings['weight_threshold'],point);timeline.append(dict(step=n,frame_id=None if n==0 else str(frames[n-1]),tsdf=row['tsdf'],weights=row['weights'],allocated=row['allocated'],opposite_sign=row['opposite_sign'],strict_weight_gate=row['strict_weight_gate'],point_extractable=row['point_extractable']))
                contributors=[]
                for j,idx in enumerate(ids):
                    delta=np.diff(weights[:,idx]);changed=np.flatnonzero(delta>0)
                    if np.any(delta<0) or np.any(np.abs(delta[changed]-1)>1e-6):raise ValueError('Unexpected observed integration weight update')
                    frame_ids=[str(frames[k]) for k in changed];contributors.append(dict(endpoint=j,updates=len(changed),frame_ids=frame_ids))
                    if abs(weights[-1,idx]-len(changed))>1e-6:raise ValueError('Captured weight count differs from actual tensor')
                evidence.update(timeline=timeline,contributors=contributors);selected.append(evidence)
            targets_out.append(dict(reference_variant=label,reference_vertex_id=targets[labels.index(label)]['original_vertex_id'],reference_mm=point.tolist(),exact_lattice_candidates=len(exact),local_counts=counts,edges=selected))
        result=dict(case=case,reference_job=job_id,reference_points=len(reference_xyz),replay_points=len(replay),full_pointset_bidirectional_max_mm=max(float(e.max()) for e in errors),settings=actual,observed_frames=len(frames),original_pixel_sha256=selection_digest.hexdigest(),queried_voxels=len(coords),targets=targets_out,volume_diagnostics=volume.diagnostics(),observer_mutates_grid=False)
        save(folder/'summary.json',result);results.append(result);print(json.dumps(dict(case=case,points=len(replay),reference_reproduction_max_mm=result['full_pointset_bidirectional_max_mm'],counts=[t['local_counts'] for t in targets_out])),flush=True)
        del volume;gc.collect()
    for name,sha in pins.items():
        if file_sha256(Path(name))!=sha:raise ValueError('Input changed while observing volumes: '+name)
    summary=dict(status='actual_voxel_readout_replay_not_geometry_acceptance',open3d_version=o3d.__version__,reference_source=reference,cases=results,input_sha256=pins,limits=['Process-local observer only reads actual tensors after integration; no integration/extraction values are edited.','Each complete replayed point set matches the frozen reference before publication; zero reproduction distance is not physical accuracy.','Local 4x4x4 lattice neighborhoods and selected edges do not describe every voxel in the volume.','Weights count actual integration updates at each sampled lattice voxel, not independent views, physical confidence or the point-projection support count.','Reference source is official v0.20.0 code, not a binary build attestation.','All 114 frames enter these surfaces; no new heldout geometry truth or whole failed-scan repair.'])
    save(out/'summary.json',summary);print(json.dumps(dict(out=str(out),cases=len(results),pinned_inputs=len(pins))),flush=True)


if __name__=='__main__':main()

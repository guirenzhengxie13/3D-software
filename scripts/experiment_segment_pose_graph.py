"""Explore segment corrections for the failed cup scan, using training frames.

Segment boundaries come from previously viewed full-sequence diagnostics, so
the reserved-frame check is exploratory and not an untouched benchmark.
"""

import os
os.environ.setdefault('OMP_NUM_THREADS','4')
os.environ.setdefault('OPENBLAS_NUM_THREADS','4')

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d
from scipy.spatial.transform import Rotation

from analyze_piecewise_holdout import classes,describe,PALETTE
from experiment_color_seeded_roi import optical_points
from reconstruct_scans import clean_depth_edges,optical_to_pose_axes,write_json
from register_scans import preprocess,refine,metrics
from reconstruction_probe.candidate_selection import hypothesis_rms_displacement
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.visibility import depth_observation_deltas


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def correction_to_mm(matrix,center):
    result=np.asarray(matrix).copy();result[:3,3]=center+1000*matrix[:3,3]-matrix[:3,:3]@center
    return result


def edge_check(values,matrix,initial,source):
    a,b=values['source_to_reference']['coverage'],values['reference_to_source']['coverage']
    probes=np.asarray(source.points)[::max(1,len(source.points)//128)]
    change=matrix@np.linalg.inv(initial)
    angle=float(np.rad2deg(Rotation.from_matrix(change[:3,:3]).magnitude()))
    movement=hypothesis_rms_displacement(matrix,initial,probes)
    checks=dict(both_3mm_coverage_ge_25pct=min(a['0.003'],b['0.003'])>=.25,
        one_1_5mm_coverage_ge_60pct=max(a['0.0015'],b['0.0015'])>=.6,
        overlap_abs_normal_median_ge_0_9=(values['overlap_abs_normal_dot_median'] or 0)>=.9,
        additional_rotation_le_15deg=angle<=15.,object_probe_rms_le_15mm=movement<=.015)
    return all(checks.values()),checks,dict(additional_rotation_deg=angle,object_probe_rms_mm=movement*1000)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();study=args.study.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);key='scan_20261018131222';decoded=study/'decoded'/key;index=read(decoded/'index.json');frames=index['frames']
    prior_path=study/'experiments/fixed-axis-depth-prior'/key/'heldout-evidence.npz';transition_path=study/'experiments/depth-sequence-consistency'/key/'neighbor-review-candidates.json'
    transitions=read(transition_path);boundaries=sorted({0,len(frames),*[row['target_ordinal'] for row in transitions if row['bidirectional_observed']>=256 and (row['conflict_fraction_observed_2mm'] or 0)>=.2]})
    with np.load(prior_path,allow_pickle=False) as prior:data={name:prior[name].copy() for name in prior.files}
    training=set(data['training_record_ordinals'].tolist());heldout=data['heldout_record_ordinals'];poses=np.array([np.load(decoded/f"frame_{f['id']:010d}"/'pose_optimized.npy',allow_pickle=False) for f in frames])
    roi_path=study/'experiments/cup-roi'/(key+'-selection.json');roi=read(roi_path);lower=np.array(roi['bounds_min_mm']);upper=np.array(roi['bounds_max_mm']);center=(lower+upper)/2
    point_clouds=[];segments=[];membership=np.full(len(frames),-1,int)
    for fragment,(start,stop) in enumerate(zip(boundaries[:-1],boundaries[1:])):
        ordinals=[i for i in range(start,stop) if i in training]
        if len(ordinals)<3:raise ValueError('Segment has fewer than three training records; manual grouping needed')
        point_parts=[];color_parts=[]
        for ordinal in ordinals:
            rid=frames[ordinal]['id'];folder=decoded/f'frame_{rid:010d}'
            with np.load(folder/'frame.npz',allow_pickle=False) as saved:depth=saved['depth_mm'];rgba=saved['rgba']
            valid=np.flatnonzero(depth.ravel()>0);ids,xyz=optical_points(depth,index['intrinsics']['Pl']);world=(xyz*optical_to_pose_axes(index))@poses[ordinal,:3,:3].T+poses[ordinal,:3,3]
            kept=np.all((world>=lower)&(world<=upper),axis=1);selected=depth.copy();selected.ravel()[ids[~kept]]=0;selected,_=clean_depth_edges(selected,3.)
            available=np.flatnonzero(selected.ravel()>0);chosen=available[np.linspace(0,len(available)-1,min(4096,len(available)),dtype=int)]
            _,xyz=optical_points(selected,index['intrinsics']['Pl'],chosen);world=(xyz*optical_to_pose_axes(index))@poses[ordinal,:3,:3].T+poses[ordinal,:3,3]
            point_parts.append((world-center)/1000);color_parts.append(rgba[np.searchsorted(valid,chosen),:3].astype(float)/255)
        cloud=o3d.geometry.PointCloud();cloud.points=o3d.utility.Vector3dVector(np.concatenate(point_parts));cloud.colors=o3d.utility.Vector3dVector(np.concatenate(color_parts));cloud,preprocessing=preprocess(cloud,.001)
        point_clouds.append(cloud);membership[start:stop]=fragment
        display=copy.deepcopy(cloud).scale(1000,center=(0,0,0)).translate(center);path=out/f'segment-{fragment}-training-mm.ply';o3d.io.write_point_cloud(str(path),display)
        segments.append(dict(fragment_id=fragment,start_ordinal=start,stop_ordinal_exclusive=stop,training_ordinals=ordinals,
            all_frame_ids=[frames[i]['id'] for i in range(start,stop)],training_frame_ids=[frames[i]['id'] for i in ordinals],path=str(path),preprocessing=preprocessing))
    thresholds=[.0015,.003,.006];edges=[];chain=[np.eye(4)];connected=True
    for source_id in range(1,len(segments)):
        target_id=source_id-1;source,target=point_clouds[source_id],point_clouds[target_id]
        initial=np.eye(4);matrix,details=refine(source,target,initial,[.012,.006,.003,.0015],iterations=55)
        values=metrics(source,target,matrix,thresholds);passed,checks,change=edge_check(values,matrix,initial,source)
        edges.append(dict(source=source_id,target=target_id,uncertain=False,accepted=passed,transform_m=matrix.tolist(),training_metrics=values,checks=checks,change=change,**details))
        print(json.dumps(dict(edge=[source_id,target_id],accepted=passed,change=change)),flush=True)
        if not passed:connected=False
        chain.append(chain[-1]@matrix)
    report=dict(scan_id=key,segments=segments,edges=edges,center_original_scan_mm=center.tolist(),
        boundary_provenance='Previously viewed full-depth pair disagreement >=20%; data-driven selection means evaluation is exploratory',
        fitting_uses_training_frames_only=True,training_record_ordinals=sorted(training),heldout_record_ordinals=heldout.tolist(),
        input_sha256={str(p):file_sha256(p) for p in [decoded/'index.json',prior_path,transition_path,roi_path]},
        limitations=['Segment boundaries were proposed using the full sequence, including later checked records; this is not an untouched validation set.',
          'Within each segment original poses are fixed; only a rigid correction per segment is fitted.',
          'Pairwise overlap and normal gates are heuristics and can accept a wrong alignment on symmetric cup surfaces.',
          'Optimization information matrices are algorithm weights, not calibrated physical uncertainty.',
          'Source records, poses and main models remain unchanged.'])
    if not connected:
        report.update(status='insufficient_adjacent_links_needs_fragment_review',results=[]);write_json(out/'summary.json',report);print(json.dumps(dict(status=report['status'],accepted_edges=sum(e['accepted'] for e in edges),edges=len(edges))),flush=True);return
    for source_id in range(2,len(segments)):
        for target_id in range(source_id-1):
            source,target=point_clouds[source_id],point_clouds[target_id];initial=np.linalg.inv(chain[target_id])@chain[source_id]
            matrix,details=refine(source,target,initial,[.006,.003,.0015],iterations=40);values=metrics(source,target,matrix,thresholds);passed,checks,change=edge_check(values,matrix,initial,source)
            edges.append(dict(source=source_id,target=target_id,uncertain=True,accepted=passed,transform_m=matrix.tolist(),training_metrics=values,checks=checks,change=change,**details))
    reg=o3d.pipelines.registration;graph=reg.PoseGraph()
    for matrix in chain:graph.nodes.append(reg.PoseGraphNode(matrix))
    for edge in edges:
        if not edge['accepted']:continue
        matrix=np.array(edge['transform_m']);info=reg.get_information_matrix_from_point_clouds(point_clouds[edge['source']],point_clouds[edge['target']],.003,matrix)
        graph.edges.append(reg.PoseGraphEdge(edge['source'],edge['target'],matrix,info,uncertain=edge['uncertain']))
    reg.global_optimization(graph,reg.GlobalOptimizationLevenbergMarquardt(),reg.GlobalOptimizationConvergenceCriteria(),reg.GlobalOptimizationOption(max_correspondence_distance=.003,edge_prune_threshold=.25,reference_node=0))
    o3d.io.write_pose_graph(str(out/'optimized-pose-graph.json'),graph)
    optimized=[np.array(node.pose) for node in graph.nodes];variants={'saved_poses':poses}
    for name,corrections in [('segment_chain',chain),('segment_pose_graph',optimized)]:
        mm=[correction_to_mm(matrix,center) for matrix in corrections];variants[name]=np.array([mm[membership[i]]@pose for i,pose in enumerate(poses)])
    optical=data['optical_points_mm'];source_ordinals=data['source_record_ordinals'];n=len(optical);views={}
    selected_views=set(heldout[::4].tolist()+[int(heldout[-1])])
    for ordinal in selected_views:
        folder=decoded/f"frame_{frames[ordinal]['id']:010d}"
        with np.load(folder/'frame.npz',allow_pickle=False) as saved:depth=saved['depth_mm']
        views[ordinal]=clean_depth_edges(depth,3.)[0]
    results=[];clouds=[];arrays=dict(optical_points_mm=optical,source_record_ordinals=source_ordinals,frame_ids=data['frame_ids'],pixel_ids=data['pixel_ids'])
    for name,matrices in variants.items():
        xyz=np.einsum('nij,nj->ni',matrices[source_ordinals,:3,:3],optical)+matrices[source_ordinals,:3,3]
        support=np.zeros((2,n),np.uint16);conflict=support.copy();occluded=support.copy();observed=np.zeros(n,np.uint16)
        for ordinal,depth in views.items():
            query=np.flatnonzero(np.abs(source_ordinals-ordinal)>8);ids,delta=depth_observation_deltas(xyz[query],matrices[ordinal],depth,index['intrinsics']['Pl'],optical_to_pose_axes(index));ids=query[ids];observed[ids]+=1
            for j,tolerance in enumerate([2.,4.]):support[j,ids[np.abs(delta)<=tolerance]]+=1;conflict[j,ids[delta>tolerance]]+=1;occluded[j,ids[delta < -tolerance]]+=1
        if name=='saved_poses' and (not np.array_equal(support,data['saved_poses_support']) or not np.array_equal(conflict,data['saved_poses_conflict'])):raise ValueError('Reserved baseline does not reproduce prior evidence')
        values=[]
        for j,tolerance in enumerate([2.,4.]):value=describe(support[j],conflict[j],observed,np.ones(n,bool));value['tolerance_mm']=tolerance;values.append(value)
        results.append(dict(variant=name,thresholds=values));np.savez_compressed(out/(name+'-poses.npz'),**{f"pose_{frame['id']}":matrix for frame,matrix in zip(frames,matrices)})
        for field,value in [('support',support),('conflict',conflict),('occluded',occluded),('observed',observed)]:arrays[name+'_'+field]=value
        pc=o3d.geometry.PointCloud();pc.points=o3d.utility.Vector3dVector(xyz);pc.colors=o3d.utility.Vector3dVector(PALETTE[classes(support[0],conflict[0])]);path=out/(name+'-evidence-mm.ply');o3d.io.write_point_cloud(str(path),pc);clouds.append((name,path))
    np.savez_compressed(out/'reserved-depth-evidence.npz',**arrays)
    report.update(status='exploratory_segment_graph_candidates_not_promoted',edges=edges,accepted_loop_edges=sum(e['accepted'] and e['uncertain'] for e in edges),results=results)
    write_json(out/'summary.json',report)
    command=[sys.executable,'scripts/build_reconstruction_review.py','--unit','mm','--up-axis','x','--invert-up','--allow-overlay','--max-points','20000','--out',str(out/'review.html'),'--notes','数据驱动分段：段内原位姿不变，仅训练帧拟合段间修正。分段边界曾查看全部序列，因此保留帧检查仍属探索。原位姿不覆盖。']
    for label,path in clouds:command+=['--cloud',label+'='+str(path)]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    print(json.dumps(dict(status=report['status'],accepted_loop_edges=report['accepted_loop_edges'],results=results)),flush=True)


if __name__=='__main__':main()

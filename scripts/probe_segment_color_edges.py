"""Explore color constraints on rejected segment links, preserving all trials."""

import os
os.environ.setdefault('OMP_NUM_THREADS','4')
os.environ.setdefault('OPENBLAS_NUM_THREADS','4')

import argparse
import copy
import json
from pathlib import Path

import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree

from experiment_segment_pose_graph import edge_check
from register_scans import metrics,score
from reconstruction_probe.offline import file_sha256


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def photometric_metrics(source,target,transform):
    world=np.asarray(source.points)@transform[:3,:3].T+transform[:3,3]
    distances,ids=cKDTree(np.asarray(target.points)).query(world);kept=distances<=.003
    if not kept.any():return dict(correspondences_3mm=0,median_rgb_mae_255=None)
    rgb=np.asarray(source.colors);reference=np.asarray(target.colors)[ids];error=np.abs(rgb-reference).mean(1)*255
    intensity=rgb.mean(1);contrasted=np.abs(intensity-np.median(intensity))>=.05
    return dict(correspondences_3mm=int(kept.sum()),median_rgb_mae_255=float(np.median(error[kept])),p90_rgb_mae_255=float(np.percentile(error[kept],90)),
        high_contrast_correspondences=int((kept&contrasted).sum()),high_contrast_median_rgb_mae_255=float(np.median(error[kept&contrasted])) if np.any(kept&contrasted) else None)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--graph-study',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();study=args.graph_study.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);previous=read(study/'summary.json');center=np.array(previous['center_original_scan_mm']);segments={row['fragment_id']:row for row in previous['segments']}
    clouds={}
    for group,row in segments.items():
        pc=o3d.io.read_point_cloud(row['path']).translate(-center).scale(.001,center=(0,0,0));clouds[group]=pc
    results=[];thresholds=[.0015,.003,.006]
    for edge in previous['edges']:
        if edge['accepted'] or edge['uncertain']:continue
        source_id,target_id=edge['source'],edge['target'];source,target=clouds[source_id],clouds[target_id]
        levels=[]
        for voxel in [.002,.001]:
            a,b=source.voxel_down_sample(voxel),target.voxel_down_sample(voxel)
            for cloud in [a,b]:cloud.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel*2.5,max_nn=40));cloud.normalize_normals()
            levels.append((voxel,a,b))
        trials=[]
        starts=[('saved_relative_identity',np.eye(4)),('rejected_geometry',np.array(edge['transform_m']))]
        for start_name,start in starts:
            values=metrics(source,target,start,thresholds);passed,checks,change=edge_check(values,start,np.eye(4),source)
            trials.append(dict(label=start_name,transform_m=start.tolist(),passes_same_geometric_gates=passed,checks=checks,change=change,training_metrics=values,training_geometry_score=score(values,thresholds),training_color=photometric_metrics(source,target,start)))
            for weight in [.968,.5]:
                matrix=start.copy();steps=[];error=None
                for voxel,a,b in levels:
                    try:
                        result=o3d.pipelines.registration.registration_colored_icp(a,b,voxel*3,matrix,
                            o3d.pipelines.registration.TransformationEstimationForColoredICP(weight),
                            o3d.pipelines.registration.ICPConvergenceCriteria(relative_fitness=1e-6,relative_rmse=1e-6,max_iteration=60))
                        matrix=np.array(result.transformation,copy=True);steps.append(dict(voxel_m=voxel,fitness=float(result.fitness),geometric_rmse_m=float(result.inlier_rmse)))
                    except RuntimeError as exc:error=str(exc);break
                label=start_name+f'_colored_{weight:g}'
                if error:trials.append(dict(label=label,error=error,passes_same_geometric_gates=False,steps=steps));continue
                values=metrics(source,target,matrix,thresholds);passed,checks,change=edge_check(values,matrix,np.eye(4),source)
                trials.append(dict(label=label,lambda_geometric=weight,transform_m=matrix.tolist(),steps=steps,passes_same_geometric_gates=passed,checks=checks,change=change,
                    training_metrics=values,training_geometry_score=score(values,thresholds),training_color=photometric_metrics(source,target,matrix)))
        passing=[row for row in trials if row['passes_same_geometric_gates']]
        # Selection uses training data only. This remains an exploratory family.
        chosen=max(passing,key=lambda row:row['training_geometry_score']-.005*row['training_color']['median_rgb_mae_255']) if passing else None
        row=dict(source=source_id,target=target_id,trials=trials,selected_training_candidate=chosen['label'] if chosen else None,
                 selected_transform_m=chosen['transform_m'] if chosen else None)
        results.append(row)
        print(json.dumps(dict(edge=[source_id,target_id],passing=len(passing),selected=row['selected_training_candidate'],trials=[dict(label=t['label'],passes=t['passes_same_geometric_gates'],change=t.get('change'),color=t.get('training_color')) for t in trials])),flush=True)
    report=dict(status='exploratory_color_edge_hypotheses_not_promoted',graph_study=str(study),edge_hypotheses=results,
        fitting_uses_training_clouds_only=True,followup_after_viewing_prior_diagnostics=True,geometry_unit='metres around the recorded common object center',
        selection_rule='Among candidates passing unchanged geometry gates, maximize training geometry score minus 0.005*training median RGB MAE /255',
        input_sha256={str(p):file_sha256(p) for p in [study/'summary.json',*[Path(row['path']) for row in segments.values()]]},
        limitations=['Color refinement is exploratory after inspecting previous failures; it is not a preregistered new test.',
          'Exposure, reflections and blurred texture can mislead color optimization; passing gates is not proof of correct correspondence.',
          'No rejected connection is silently forced into a global reconstruction.'])
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


if __name__=='__main__':main()

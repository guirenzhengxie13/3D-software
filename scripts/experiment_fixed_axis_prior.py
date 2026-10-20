"""Test a fixed-axis prior on saved poses using reserved depth-record blocks.

Only training poses fit the axis. Held-out angles still use their own saved
rotations, so this is conditional depth consistency, not independent tracking.
"""

import os
os.environ.setdefault('OMP_NUM_THREADS','4')

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d
from PIL import Image,ImageDraw

from analyze_piecewise_holdout import describe,classes,PALETTE
from build_attribute_study_report import render,font
from experiment_color_seeded_roi import optical_points
from reconstruct_scans import clean_depth_edges,optical_to_pose_axes,write_json
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.turntable import diagnose_fixed_axis,predict_fixed_axis_poses
from reconstruction_probe.visibility import depth_observation_deltas


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--scans',nargs='+',default=['scan_20261018131019','scan_20261018131127','scan_20261018131222'])
    args=parser.parse_args();study=args.study.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);results=[];all_clouds=[];cards=[]
    for key in args.scans:
        decoded=study/'decoded'/key;index=read(decoded/'index.json');frames=index['frames']
        if index.get('color_layout_version')!=2:raise ValueError('Verified cohort color layout required')
        if len({frame['id']>>32 for frame in frames})!=1:raise ValueError('This prior experiment expects one ID group per scan')
        poses=np.array([np.load(decoded/f"frame_{f['id']:010d}"/'pose_optimized.npy',allow_pickle=False) for f in frames]);training=np.array([i for i in range(len(frames)) if (i//16)%2==0]);heldout=np.array([i for i in range(len(frames)) if (i//16)%2==1])
        fitted,_=diagnose_fixed_axis(poses[training],huber_mm=2.);predicted=predict_fixed_axis_poses(poses,fitted['axis_direction_in_scan_frame'],fitted['axis_point_minimum_norm_mm'],poses[training[0]])
        translation_only=poses.copy();translation_only[:,:3,3]=predicted[:,:3,3]
        variants={'saved_poses':poses,'axis_translation_only':translation_only,'axis_full_pose':predicted}
        optical,source_ordinals,source_ids,pixels,source_colors=[],[],[],[],[];views={};rng=np.random.default_rng(20261019)
        selected_views=set(heldout[::4].tolist()+[int(heldout[-1])])
        for ordinal in heldout:
            rid=frames[ordinal]['id'];folder=decoded/f'frame_{rid:010d}'
            with np.load(folder/'frame.npz',allow_pickle=False) as saved:original=saved['depth_mm'];rgba=saved['rgba']
            valid=np.flatnonzero(original.ravel()>0);rgb=rgba[:,:3].astype(float);green=(rgb[:,1]-rgb[:,0]>3)&(rgb[:,1]-rgb[:,2]>8)&(rgb[:,1]>12)
            depth,_=clean_depth_edges(original,3.);eligible=valid[green];eligible=eligible[depth.ravel()[eligible]>0]
            chosen=np.sort(rng.choice(eligible,min(64,len(eligible)),replace=False));_,xyz=optical_points(depth,index['intrinsics']['Pl'],chosen)
            optical.append(xyz*optical_to_pose_axes(index));source_ordinals.append(np.full(len(xyz),ordinal,np.int64));source_ids.append(np.full(len(xyz),rid,np.int64));pixels.append(chosen);source_colors.append(rgba[np.searchsorted(valid,chosen),:3])
            if ordinal in selected_views:views[int(ordinal)]=depth
        optical,source_ordinals,source_ids,pixels,source_colors=map(np.concatenate,(optical,source_ordinals,source_ids,pixels,source_colors));n=len(optical)
        target=out/key;target.mkdir();rows=[];pcs=[];arrays=dict(optical_points_mm=optical,source_record_ordinals=source_ordinals,frame_ids=source_ids,pixel_ids=pixels,training_record_ordinals=training,heldout_record_ordinals=heldout)
        for name,matrices in variants.items():
            points=np.einsum('nij,nj->ni',matrices[source_ordinals,:3,:3],optical)+matrices[source_ordinals,:3,3]
            support=np.zeros((2,n),np.uint16);conflict=support.copy();occluded=support.copy();observed=np.zeros(n,np.uint16)
            for ordinal,depth in views.items():
                chosen=np.flatnonzero(np.abs(source_ordinals-ordinal)>8)
                ids,delta=depth_observation_deltas(points[chosen],matrices[ordinal],depth,index['intrinsics']['Pl'],optical_to_pose_axes(index));ids=chosen[ids];observed[ids]+=1
                for j,tolerance in enumerate([2.,4.]):
                    support[j,ids[np.abs(delta)<=tolerance]]+=1;conflict[j,ids[delta>tolerance]]+=1;occluded[j,ids[delta < -tolerance]]+=1
            metrics=[]
            for j,tolerance in enumerate([2.,4.]):
                values=describe(support[j],conflict[j],observed,np.ones(n,bool));values.update(tolerance_mm=tolerance,occluded_in_three_or_more_views=int((occluded[j]>=3).sum()));metrics.append(values)
            rows.append(dict(variant=name,thresholds=metrics))
            for field,value in [('support',support),('conflict',conflict),('occluded',occluded),('observed',observed)]:arrays[name+'_'+field]=value
            np.savez_compressed(target/(name+'-poses.npz'),**{f"pose_{frame['id']}":matrix for frame,matrix in zip(frames,matrices)})
            pc=o3d.geometry.PointCloud();pc.points=o3d.utility.Vector3dVector(points);pc.colors=o3d.utility.Vector3dVector(PALETTE[classes(support[0],conflict[0])]);path=target/(name+'-heldout-evidence-mm.ply');o3d.io.write_point_cloud(str(path),pc);pcs.append(pc);all_clouds.append((key.removeprefix('scan_')+' '+name,path))
        np.savez_compressed(target/'heldout-evidence.npz',**arrays)
        correction=np.linalg.norm(poses[:,:3,3]-predicted[:,:3,3],axis=1)
        report=dict(scan_id=key,fit_training_pose_records=len(training),heldout_depth_records=len(heldout),source_samples=n,target_views=len(views),
            training_frame_ids=[frames[i]['id'] for i in training],heldout_frame_ids=[frames[i]['id'] for i in heldout],
            green_source_rule='G-R>3, G-B>8, G>12 on verified RGB; source pixels only, target depths remain complete',
            fit=fitted,predicted_origin_change_mm_quantiles=np.percentile(correction,[0,50,90,100]).tolist(),results=rows,
            input_sha256={str(decoded/'index.json'):file_sha256(decoded/'index.json')},
            limitations=['Axis/center fit uses training poses, but heldout angles are extracted from their vendor-derived rotations; this is not independent tracking recovery.',
              'Green source sampling is specific to these cup observations and can exclude real dark or non-green parts.',
              'The model assumes one fixed axis and fixed camera/object relation; real repositioning can legitimately violate it.',
              'Saved-record blocks and views are correlated; source and adjacent +/-8 records are excluded from direct self checks.',
              'No prior is automatically adopted and no source pose is overwritten.'])
        write_json(target/'summary.json',report);results.append(report)
        bounds=(np.min([pc.get_min_bound() for pc in pcs],axis=0),np.max([pc.get_max_bound() for pc in pcs],axis=0))
        picture=Image.new('RGB',(1500,480),(24,33,47));draw=ImageDraw.Draw(picture)
        for i,(row,pc) in enumerate(zip(rows,pcs)):
            draw.text((i*500+12,8),key.removeprefix('scan_')+' '+row['variant'],font=font(16),fill='#edf3fa');picture.paste(render(pc,(490,350),gain=1.,bounds=bounds),(i*500+5,45));m=row['thresholds'][0];draw.text((i*500+12,415),f"支持 {m['supported_in_at_least_two_views']/n:.1%} · 冲突 {m['conflicts_in_at_least_three_views']/n:.1%}",font=font(18),fill='#edf3fa')
        picture.save(target/'comparison.png');cards.append(picture)
        print(json.dumps(dict(scan_id=key,results=[dict(variant=r['variant'],support_2mm=r['thresholds'][0]['supported_in_at_least_two_views'],conflict_2mm=r['thresholds'][0]['conflicts_in_at_least_three_views']) for r in rows],samples=n)),flush=True)
    write_json(out/'summary.json',dict(status='kinematic_prior_experiment_not_promoted',projects=results))
    picture=Image.new('RGB',(1500,480*len(cards)),(24,33,47))
    for i,card in enumerate(cards):picture.paste(card,(0,480*i))
    picture.save(out/'comparison.png')
    command=[sys.executable,'scripts/build_reconstruction_review.py','--unit','mm','--up-axis','x','--invert-up','--max-points','20000','--out',str(out/'review.html'),'--notes','固定轴先验实验：原始、只修平移、同时约束旋转与平移。只用训练位姿拟合轴；留出角度仍来自保存旋转。相同绿色原像素对留出深度检查，非独立跟踪精度。不同工程坐标独立。']
    for label,path in all_clouds:command+=['--cloud',label+'='+str(path)]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)


if __name__=='__main__':main()

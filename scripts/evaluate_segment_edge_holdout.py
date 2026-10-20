"""Check frozen segment connections using reserved raw depth pixels in both directions."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from analyze_piecewise_holdout import classes, describe
from build_attribute_study_report import font
from reconstruct_scans import clean_depth_edges, optical_to_pose_axes, write_json
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.visibility import depth_observation_deltas


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def to_mm(matrix, center):
    result=np.array(matrix,copy=True);result[:3,3]=center+1000*result[:3,3]-result[:3,:3]@center
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();study=args.study.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);graph_path=study/'experiments/cup-segment-pose-graph/summary.json';graph=read(graph_path)
    prior_path=study/'experiments/fixed-axis-depth-prior'/graph['scan_id']/'heldout-evidence.npz';decoded=study/'decoded'/graph['scan_id'];index=read(decoded/'index.json')
    with np.load(prior_path,allow_pickle=False) as saved:
        data={name:saved[name].copy() for name in ['optical_points_mm','source_record_ordinals','frame_ids','pixel_ids','training_record_ordinals','heldout_record_ordinals']}
    training=set(data['training_record_ordinals'].tolist());heldout=set(data['heldout_record_ordinals'].tolist())
    if training & heldout:raise ValueError('Training and heldout records overlap')
    poses=np.array([np.load(decoded/f"frame_{r['id']:010d}"/'pose_optimized.npy',allow_pickle=False) for r in index['frames']])
    segments={s['fragment_id']:s for s in graph['segments']};membership=np.full(len(poses),-1,int)
    for s in segments.values():membership[s['start_ordinal']:s['stop_ordinal_exclusive']]=s['fragment_id']
    signs=optical_to_pose_axes(index);center=np.array(graph['center_original_scan_mm']);results=[]
    depths={}
    for ordinal in heldout:
        with np.load(decoded/f"frame_{index['frames'][ordinal]['id']:010d}"/'frame.npz',allow_pickle=False) as saved:depth=saved['depth_mm']
        depths[ordinal]=clean_depth_edges(depth,3.)[0]
    for edge in graph['edges']:
        source,target=edge['source'],edge['target'];correction=to_mm(edge['transform_m'],center);parts=[];evidence={}
        for direction,query_fragment,view_fragment in [('forward',source,target),('reverse',target,source)]:
            chosen=np.flatnonzero(membership[data['source_record_ordinals']]==query_fragment)
            optical=data['optical_points_mm'][chosen];ordinals=data['source_record_ordinals'][chosen]
            view_ordinals=sorted(i for i in heldout if membership[i]==view_fragment)
            if not len(chosen) or not len(view_ordinals):raise ValueError('No reserved depths for this connection')
            evidence[direction+'_source_frame_ids']=data['frame_ids'][chosen];evidence[direction+'_source_pixel_ids']=data['pixel_ids'][chosen]
            evidence[direction+'_source_record_ordinals']=ordinals;evidence[direction+'_source_optical_mm']=optical
            evidence[direction+'_target_record_ordinals']=np.array(view_ordinals,np.int64)
            digest=hashlib.sha256(data['frame_ids'][chosen].astype('<i8').tobytes()+data['pixel_ids'][chosen].astype('<i8').tobytes()+optical.astype('<f8').tobytes()).hexdigest()
            variants=[];counts_by_variant={}
            for label,transform in [('saved_relative_identity',np.eye(4)),('geometric_training_candidate',correction)]:
                query_poses=poses[ordinals].copy()
                if query_fragment==source:query_poses=np.einsum('ij,njk->nik',transform,query_poses)
                xyz=np.einsum('nij,nj->ni',query_poses[:,:3,:3],optical*signs)+query_poses[:,:3,3]
                n=len(xyz);support=np.zeros((2,n),np.uint16);conflict=support.copy();occluded=support.copy();observed=np.zeros(n,np.uint16)
                for view in view_ordinals:
                    pose=transform@poses[view] if view_fragment==source else poses[view]
                    ids,delta=depth_observation_deltas(xyz,pose,depths[view],index['intrinsics']['Pl'],signs)
                    permitted=np.abs(ordinals[ids]-view)>8;ids=ids[permitted];delta=delta[permitted];observed[ids]+=1
                    for j,tolerance in enumerate([2.,4.]):
                        support[j,ids[np.abs(delta)<=tolerance]]+=1;conflict[j,ids[delta>tolerance]]+=1;occluded[j,ids[delta < -tolerance]]+=1
                for key,array in [('support',support),('conflict',conflict),('occluded',occluded),('observed',observed)]:evidence[direction+'_'+label+'_'+key]=array
                counts_by_variant[label]=(support,conflict,observed)
                variants.append(dict(label=label,thresholds=[dict(tolerance_mm=tolerance,**describe(support[j],conflict[j],observed,np.ones(n,bool))) for j,tolerance in enumerate([2.,4.])]))
            original=counts_by_variant['saved_relative_identity'];candidate=counts_by_variant['geometric_training_candidate'];common=(original[2]>=3)&(candidate[2]>=3);evidence[direction+'_common_observed']=common
            transitions=[]
            for j,tolerance in enumerate([2.,4.]):
                matrix=np.zeros((4,4),int);np.add.at(matrix,(classes(original[0][j],original[1][j]),classes(candidate[0][j],candidate[1][j])),1)
                transitions.append(dict(tolerance_mm=tolerance,all_sample_transitions=matrix.tolist(),
                    original_common=describe(original[0][j],original[1][j],original[2],common),candidate_common=describe(candidate[0][j],candidate[1][j],candidate[2],common)))
            parts.append(dict(direction=direction,query_fragment=query_fragment,view_fragment=view_fragment,samples=len(chosen),
                target_saved_views=len(view_ordinals),source_sample_sha256=digest,variants=variants,transitions=transitions))
        np.savez_compressed(out/f'edge-{source}-to-{target}-evidence.npz',**evidence)
        compact=[]
        for label in ['saved_relative_identity','geometric_training_candidate']:
            values=[next(v for v in part['variants'] if v['label']==label)['thresholds'] for part in parts]
            compact.append(dict(label=label,thresholds=[dict(tolerance_mm=tolerance,samples=sum(p['samples'] for p in parts),
                supported_points=sum(v[j]['supported_in_at_least_two_views'] for v in values),
                repeated_conflict_points=sum(v[j]['conflicts_in_at_least_three_views'] for v in values)) for j,tolerance in enumerate([2.,4.])]))
        results.append(dict(source=source,target=target,passed_training_geometry_gates=edge['accepted'],directions=parts,combined=compact))
        print(json.dumps(dict(edge=[source,target],training_passed=edge['accepted'],combined=compact)),flush=True)
    summary=dict(status='reserved_depth_check_of_frozen_segment_connections_not_promoted',scan_id=graph['scan_id'],edges=results,
        fitting_uses_training_only=True,source_pixels_same_between_variants=True,minimum_support_views=2,minimum_conflict_views=3,
        excluded_index_neighbor_radius=8,input_sha256={str(p):file_sha256(p) for p in [graph_path,prior_path,decoded/'index.json']},
        limitations=['Segment boundaries used previously viewed full-sequence depth diagnostics, including these records; this is not a blind evaluation.',
          'Only one rigid correction is applied across each tested connection; internal segment drift is unchanged.',
          'Some fragments have only four heldout target records, so evidence counts may be weak, unequal or absent after neighbor exclusion.',
          'Green source pixels target this cup cohort; uncolored or printed physical regions may be underrepresented.',
          'Missing/occluded depth is not an error. Support and repeated conflict can both be present.',
          'No global model is reconstructed and no rejected edge is silently accepted.'])
    write_json(out/'summary.json',summary)
    picture=Image.new('RGB',(1500,120+len(results)*125),(24,33,47));draw=ImageDraw.Draw(picture)
    draw.text((12,10),'冻结片段连接：相同预留原深度点，双向检查',font=font(24),fill='#edf3fa');draw.text((12,53),'蓝：原关系；橙：几何候选。支持至少2视图，冲突至少3视图，容差2mm；索引±8排除。',font=font(17),fill='#adbed1')
    for i,row in enumerate(results):
        y=105+i*125;draw.text((12,y),f"{row['source']}→{row['target']} · 训练门槛{'通过' if row['passed_training_geometry_gates'] else '未过'}",font=font(18),fill='#edf3fa')
        for j,value in enumerate(row['combined']):
            stats=value['thresholds'][0];n=stats['samples'];draw.text((300,y+j*42),value['label'],font=font(15),fill='#adbed1')
            draw.text((650,y+j*42),f"支持 {stats['supported_points']/n:.1%} · 冲突 {stats['repeated_conflict_points']/n:.1%} · N={n}",font=font(18),fill='#edf3fa')
    picture.save(out/'comparison.png')
    lines=['# 用预留原深度检查分段连接','','所有变换沿用训练几何拟合，源像素完全相同。正向检查移动段的点投影到固定段预留深度，反向检查固定段点投影到变换后的移动段相机。排除索引±8，使用2/4mm两档。分段边界已看过全数据，因此仍是探索性预留检查。','','![冻结连接对照](comparison.png)','','| 连接 | 训练门槛 | 候选 | 2mm支持 | 2mm重复冲突 | 样本 |','| --- | --- | --- | ---: | ---: | ---: |']
    for row in results:
        for variant in row['combined']:
            v=variant['thresholds'][0];n=v['samples'];lines.append(f"| {row['source']}→{row['target']} | {'通过' if row['passed_training_geometry_gates'] else '未过'} | {variant['label']} | {v['supported_points']/n:.2%} | {v['repeated_conflict_points']/n:.2%} | {n} |")
    lines+=['','训练几何门槛通过不能直接证明预留深度改善。必须同时看支持、冲突、共同可观测点与目标视图数量；一些目标段只有4条预留记录，证据有限。几何候选没有根据此结果重新拟合，也没有用于全局融合。','','[完整双向统计、4mm结果和共同可观测子集](summary.json) · [原分段研究](../cup-segment-pose-graph/README.md)']
    (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':main()

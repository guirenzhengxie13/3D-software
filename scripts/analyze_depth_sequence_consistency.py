"""Compare saved depth records at several index separations, without editing poses."""

import argparse
import csv
from functools import lru_cache
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw
from scipy.spatial.transform import Rotation

from build_attribute_study_report import font
from experiment_color_seeded_roi import optical_points
from reconstruct_scans import clean_depth_edges,optical_to_pose_axes,write_json
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.visibility import depth_observation_deltas


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--scans',nargs='+',default=['scan_20261018131019','scan_20261018131127','scan_20261018131222','scan_20261018131359'])
    args=parser.parse_args();study=args.study.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);projects=[];cards=[]
    for key in args.scans:
        decoded=study/'decoded'/key;index=read(decoded/'index.json');frames=index['frames'];count=len(frames)
        poses=[];samples=[];rng=np.random.default_rng(20261019)
        for frame in frames:
            folder=decoded/f"frame_{frame['id']:010d}"
            with np.load(folder/'frame.npz',allow_pickle=False) as saved:
                depth=saved['depth_mm'];rgba=saved['rgba']
                if int(saved['color_layout_version'])!=2:raise ValueError('Verified physical RGB convention required')
            original_valid=np.flatnonzero(depth.ravel()>0);rgb=rgba[:,:3].astype(float);green=(rgb[:,1]-rgb[:,0]>3)&(rgb[:,1]-rgb[:,2]>8)&(rgb[:,1]>12)
            depth,_=clean_depth_edges(depth,3.);eligible=original_valid[green];eligible=eligible[depth.ravel()[eligible]>0]
            selected=np.sort(rng.choice(eligible,min(512,len(eligible)),replace=False));_,optical=optical_points(depth,index['intrinsics']['Pl'],selected)
            pose=np.load(folder/'pose_optimized.npy',allow_pickle=False);poses.append(pose);samples.append((optical*optical_to_pose_axes(index))@pose[:3,:3].T+pose[:3,3])
        poses=np.array(poses)
        @lru_cache(maxsize=12)
        def depth_at(ordinal):
            folder=decoded/f"frame_{frames[ordinal]['id']:010d}"
            with np.load(folder/'frame.npz',allow_pickle=False) as saved:depth=saved['depth_mm']
            return clean_depth_edges(depth,3.)[0]
        def check(source,target):
            ids,delta=depth_observation_deltas(samples[source],poses[target],depth_at(target),index['intrinsics']['Pl'],optical_to_pose_axes(index))
            return dict(sampled=len(samples[source]),observed=len(ids),support_2mm=int((np.abs(delta)<=2).sum()),conflict_2mm=int((delta>2).sum()),occluded_2mm=int((delta < -2).sum()),support_4mm=int((np.abs(delta)<=4).sum()),conflict_4mm=int((delta>4).sum()))
        rows=[];offset_summaries=[]
        for offset in [1,8,32]:
            current=[]
            for first in range(count-offset):
                second=first+offset;a,b=check(first,second),check(second,first);observed=a['observed']+b['observed']
                relative=poses[second,:3,:3]@poses[first,:3,:3].T
                row=dict(source_ordinal=first,target_ordinal=second,source_frame_id=frames[first]['id'],target_frame_id=frames[second]['id'],index_separation=offset,
                    changes_id_high=(frames[first]['id']>>32)!=(frames[second]['id']>>32),bidirectional_observed=observed,
                    support_fraction_observed_2mm=(a['support_2mm']+b['support_2mm'])/observed if observed else None,
                    conflict_fraction_observed_2mm=(a['conflict_2mm']+b['conflict_2mm'])/observed if observed else None,
                    support_fraction_observed_4mm=(a['support_4mm']+b['support_4mm'])/observed if observed else None,
                    conflict_fraction_observed_4mm=(a['conflict_4mm']+b['conflict_4mm'])/observed if observed else None,
                    relative_rotation_deg=float(np.rad2deg(Rotation.from_matrix(relative).magnitude())),
                    relative_camera_origin_step_mm=float(np.linalg.norm(poses[second,:3,3]-poses[first,:3,3])),forward=a,reverse=b)
                row['review_reasons']=[]
                if observed>=256 and row['conflict_fraction_observed_2mm']>=.2:row['review_reasons'].append('repeated_pair_depth_disagreement')
                if offset==1 and row['relative_rotation_deg']>=20:row['review_reasons'].append('large_relative_rotation_between_index_neighbors')
                if offset==1 and row['changes_id_high']:row['review_reasons'].append('id_high_group_boundary_unknown_meaning')
                rows.append(row);current.append(row)
            valid=[r for r in current if r['bidirectional_observed']>=256]
            conflict=np.array([r['conflict_fraction_observed_2mm'] for r in valid]);support=np.array([r['support_fraction_observed_2mm'] for r in valid])
            offset_summaries.append(dict(index_separation=offset,pairs=len(current),pairs_with_at_least_256_valid_projections=len(valid),
                conflict_fraction_2mm_quantiles=np.percentile(conflict,[0,50,90,100]).tolist() if len(conflict) else None,
                support_fraction_2mm_quantiles=np.percentile(support,[0,50,90,100]).tolist() if len(support) else None,
                pairs_above_20pct_conflict=int((conflict>=.2).sum())))
            print(f'{key}: offset {offset} completed',flush=True)
        target=out/key;target.mkdir();write_json(target/'pairs.json',rows)
        flagged=[r for r in rows if r['index_separation']==1 and r['review_reasons']];write_json(target/'neighbor-review-candidates.json',flagged)
        with (target/'pairs.csv').open('w',encoding='utf-8',newline='') as stream:
            fields=[k for k in rows[0] if k not in ['forward','reverse','review_reasons']];writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows({k:r[k] for k in fields} for r in rows)
        report=dict(scan_id=key,records=count,offset_summaries=offset_summaries,neighbor_review_candidates=len(flagged),
            source_sampling='At most 512 verified green RGB depth points per source record; target depths retain all colors',
            pose_sequence_sha256=hashlib.sha256(poses.astype('<f8').tobytes()).hexdigest(),input_sha256={str(decoded/'index.json'):file_sha256(decoded/'index.json')},
            limitations=['Index separation is not elapsed time; physical frame rate and capture chronology are not established.',
              'Source/target visibility and occlusion affect the statistics. These are descriptive checks, not calibrated error probabilities.',
              'Green source sampling targets this cohort and may miss dark/printed/other true regions.',
              'A large relative pose step can be valid repositioning; no review marker is treated as an invalid frame flag.',
              'Neighbor agreement does not prove long-range consistency, and pair disagreements do not identify which frame is wrong.'])
        write_json(target/'summary.json',report);projects.append(report)
        picture=Image.new('RGB',(1500,390),(24,33,47));draw=ImageDraw.Draw(picture);draw.text((12,8),key.removeprefix('scan_')+' · 双向深度检查，横轴为索引位置',font=font(20),fill='#edf3fa')
        for panel,offset in enumerate([1,8,32]):
            x0,y0,width,height=panel*500+35,90,440,230;draw.text((panel*500+12,47),f'索引间隔 {offset}',font=font(17),fill='#adbed1');draw.rectangle((x0,y0,x0+width,y0+height),outline='#46617d')
            for field,color in [('support_fraction_observed_2mm','#6ccc9b'),('conflict_fraction_observed_2mm','#f08e7f')]:
                chain=[]
                for row in [r for r in rows if r['index_separation']==offset]:
                    if row[field] is None:
                        if len(chain)>1:draw.line(chain,fill=color,width=2)
                        chain=[];continue
                    chain.append((x0+row['source_ordinal']/max(count-1,1)*width,y0+(1-row[field])*height))
                if len(chain)>1:draw.line(chain,fill=color,width=2)
            draw.text((x0-25,y0-5),'1.0',font=font(11),fill='#adbed1');draw.text((x0-25,y0+height-10),'0.0',font=font(11),fill='#adbed1')
        draw.text((12,348),'绿=支持比例，红=自由空间冲突比例；分母为有效投影，不把遮挡算作冲突。不是物理精度或自动删帧规则。',font=font(15),fill='#adbed1');picture.save(target/'comparison.png');cards.append(picture)
        print(json.dumps(dict(scan_id=key,neighbor_review_candidates=len(flagged),offset_summaries=offset_summaries)),flush=True)
        depth_at.cache_clear()
    write_json(out/'summary.json',dict(projects=projects));image=Image.new('RGB',(1500,390*len(cards)),(24,33,47))
    for i,card in enumerate(cards):image.paste(card,(0,390*i))
    image.save(out/'comparison.png')


if __name__=='__main__':main()

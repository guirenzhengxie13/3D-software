"""Replay frozen depth evidence and thin identical target view lists.

Record phases are sensitivity controls, not independent folds or confidence
intervals. No candidate is fitted or accepted and no scan is reconstructed.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from reconstruct_scans import clean_depth_edges,optical_to_pose_axes
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.visibility import depth_observation_deltas


LABELS=['saved_relative_identity','geometric_training_candidate']


def describe(delta,tolerance,mask):
    finite=np.isfinite(delta);support=np.count_nonzero(finite&(np.abs(delta)<=tolerance),axis=0)
    conflict=np.count_nonzero(finite&(delta>tolerance),axis=0);observed=finite.sum(axis=0)
    yes=support>=2;no=conflict>=3
    return dict(points=int(mask.sum()),observed_at_least_once=int(((observed>=1)&mask).sum()),observed_in_three=int(((observed>=3)&mask).sum()),
        support=int((yes&mask).sum()),conflict=int((no&mask).sum()),supported_only=int((yes&~no&mask).sum()),mixed=int((yes&no&mask).sum()),conflict_only=int((~yes&no&mask).sum()),inconclusive=int((~yes&~no&mask).sum()))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(args.out)
    if out.exists() or root/'reports' not in out.parents:parser.error('Use a new output strictly inside workspace/reports')
    base=root/'reports/range2-study-20261018';prior=base/'experiments/cup-segment-edge-holdout';pins={}
    def pin(path,expected=None):
        path=mapper.resolve(path);sha=file_sha256(path)
        if expected is not None and sha!=expected:raise ValueError('Frozen input changed: '+str(path))
        if str(path) in pins and pins[str(path)]!=sha:raise ValueError('Input changed during replay')
        pins[str(path)]=sha;return path
    def read(path):
        path=pin(path);raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=pins[str(path)]:raise ValueError('Input changed during read')
        return mapper.record(json.loads(raw.decode('utf-8')))
    old=read(prior/'summary.json');graph=read(base/'experiments/cup-segment-pose-graph/summary.json')
    for path,sha in old['input_sha256'].items():pin(path,sha)
    decoded=base/'decoded'/old['scan_id'];index=read(decoded/'index.json');signs=optical_to_pose_axes(index)
    for path in [Path(__file__),root/'src/reconstruction_probe/visibility.py',root/'scripts/reconstruct_scans.py',root/'web/studio/view_density_diagnostic.html']:pin(path)
    poses={};depths={}
    def folder(ordinal):return decoded/f"frame_{index['frames'][ordinal]['id']:010d}"
    def pose(ordinal):
        if ordinal not in poses:poses[ordinal]=np.load(pin(folder(ordinal)/'pose_optimized.npy'),allow_pickle=False)
        return poses[ordinal]
    def depth(ordinal):
        if ordinal not in depths:
            with np.load(pin(folder(ordinal)/'frame.npz'),allow_pickle=False) as z:depths[ordinal]=clean_depth_edges(z['depth_mm'],3.)[0]
        return depths[ordinal]
    out.mkdir(parents=True);results=[];exact_checks=0
    for edge in old['edges']:
        source,target=edge['source'],edge['target'];geometry=next(g for g in graph['edges'] if g['source']==source and g['target']==target)
        matrix=np.array(geometry['transform_m'],float);center=np.array(graph['center_original_scan_mm']);matrix[:3,3]=center+1000*matrix[:3,3]-matrix[:3,:3]@center
        with np.load(pin(prior/f'edge-{source}-to-{target}-evidence.npz'),allow_pickle=False) as z:saved={k:z[k] for k in z.files}
        parts=[];arrays={}
        for direction in ['forward','reverse']:
            optics=saved[direction+'_source_optical_mm'];ordinals=saved[direction+'_source_record_ordinals'];views=saved[direction+'_target_record_ordinals'].tolist();n=len(optics);m=len(views)
            ids=saved[direction+'_source_frame_ids'];pixels=saved[direction+'_source_pixel_ids']
            digest=hashlib.sha256(ids.astype('<i8').tobytes()+pixels.astype('<i8').tobytes()+optics.astype('<f8').tobytes()).hexdigest()
            previous=next(p for p in edge['directions'] if p['direction']==direction)
            if digest!=previous['source_sample_sha256']:raise ValueError('Source pixel set changed')
            frames=np.array([pose(int(i)) for i in ordinals]);deltas={}
            for label,transform in zip(LABELS,[np.eye(4),matrix]):
                qp=np.einsum('ij,njk->nik',transform,frames) if direction=='forward' else frames
                points=np.einsum('nij,nj->ni',qp[:,:3,:3],optics*signs)+qp[:,:3,3];values=np.full((m,n),np.nan,dtype=float)
                for row,view in enumerate(views):
                    vp=transform@pose(view) if direction=='reverse' else pose(view)
                    chosen,delta=depth_observation_deltas(points,vp,depth(view),index['intrinsics']['Pl'],signs)
                    permitted=np.abs(ordinals[chosen]-view)>8;values[row,chosen[permitted]]=delta[permitted]
                deltas[label]=values;arrays[direction+'_'+label+'_delta_mm']=values
                observed=np.isfinite(values).sum(0)
                if not np.array_equal(observed,saved[direction+'_'+label+'_observed']):raise ValueError('Observed counts differ from old frozen evidence')
                for j,tol in enumerate([2.,4.]):
                    for name,actual in [('support',np.count_nonzero(np.abs(values)<=tol,axis=0)),('conflict',np.count_nonzero(values>tol,axis=0)),('occluded',np.count_nonzero(values < -tol,axis=0))]:
                        if not np.array_equal(actual,saved[direction+'_'+label+'_'+name][j]):raise ValueError('Full replay differs: '+name)
                        exact_checks+=1
            full_common=np.logical_and.reduce([np.isfinite(v).sum(0)>=3 for v in deltas.values()])
            if not np.array_equal(full_common,saved[direction+'_common_observed']):raise ValueError('Full common population changed')
            profiles=[]
            for stride in [1,2,4,8]:
                for phase in range(min(stride,m)):
                    rows=np.arange(phase,m,stride);sub={k:v[rows] for k,v in deltas.items()};common=np.logical_and.reduce([np.isfinite(v).sum(0)>=3 for v in sub.values()])
                    axes=np.array([pose(views[i])[:3,:3]@(signs*np.array([0.,0.,1.])) for i in rows]);angles=np.degrees(np.arccos(np.clip(axes@axes.T,-1,1)))
                    profiles.append(dict(stride=stride,phase=phase,target_views=len(rows),target_frame_ids=[str(index['frames'][views[i]]['id']) for i in rows],saved_pose_optical_axis_max_separation_deg=float(angles.max()),thresholds=[dict(tolerance_mm=tol,variants=[dict(label=label,all=describe(values,tol,np.ones(n,bool)),frozen_common=describe(values,tol,full_common),current_common=describe(values,tol,common)) for label,values in sub.items()]) for tol in [2.,4.]]))
            arrays[direction+'_source_frame_ids']=ids;arrays[direction+'_source_pixel_ids']=pixels;arrays[direction+'_target_record_ordinals']=np.array(views);arrays[direction+'_frozen_common']=full_common
            parts.append(dict(direction=direction,samples=n,source_sample_sha256=digest,full_target_views=m,profiles=profiles))
        np.savez_compressed(out/f'edge-{source}-to-{target}-per-view.npz',**arrays)
        results.append(dict(source=source,target=target,training_gate_passed=edge['passed_training_geometry_gates'],directions=parts));print(json.dumps(dict(edge=[source,target],source_pixels_verified=True,full_replay_matches=True)),flush=True)
    for path,sha in pins.items():
        if file_sha256(Path(path))!=sha:raise ValueError('Pinned input changed during replay: '+path)
    summary=dict(status='target_view_density_sensitivity_not_new_validation_or_acceptance',scan_id=old['scan_id'],exact_old_count_checks=exact_checks,edges=results,input_sha256=pins,minimum_support_views=2,minimum_conflict_views=3,neighbor_record_exclusion=8,limitations=['Same previously inspected reserved pixels and frozen transforms, not new independent observations or physical ground truth.','Uniform target record strides and phases are deterministic sensitivity controls, not independent validation folds, scanner time or turntable encoder state.','Fixed two-support/three-conflict gates weaken with fewer views; fewer counted conflicts alone is not a better reconstruction.','Frozen common points are fixed by full-list observations; subset common points change population and cannot alone establish improvement.','Support and repeated conflict can overlap. Missing/occluded observations are not counted as free-space errors.','Saved pose optical-axis spread is an estimate under saved registration, not actual camera/turntable metrology.','No candidate, pose, original training gate, source model or fusion output is changed.'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    template=(root/'web/studio/view_density_diagnostic.html').read_text(encoding='utf-8');encoded=json.dumps(summary,ensure_ascii=False,allow_nan=False).replace('<',chr(92)+'u003c')
    (out/'review.html').write_text(template.replace('__VIEW_DENSITY_DATA__',encoded,1),encoding='utf-8',newline='\n')
    print(json.dumps(dict(edges=len(results),exact_old_count_checks=exact_checks,pinned_inputs=len(pins),out=str(out))),flush=True)


if __name__=='__main__':main()

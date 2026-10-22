"""Diagnose local point-to-plane constraints of frozen cup segment candidates.

No candidate is fitted, accepted, or fused here. Local curvature is not a
probability of a correct correspondence or calibrated physical uncertainty.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.ply_layout import map_ply_vertices
from reconstruction_probe.registration_observability import constraint_spectrum


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(args.out)
    if out.exists() or root/'reports' not in out.parents:parser.error('Use a new folder strictly inside workspace/reports')
    study=root/'reports/range2-study-20261018/experiments';pins={}
    def pin(path,expected=None):
        path=mapper.resolve(path);sha=file_sha256(path)
        if expected is not None and sha!=expected:raise ValueError('Frozen reference changed: '+str(path))
        if str(path) in pins and pins[str(path)]!=sha:raise ValueError('Input changed while loading: '+str(path))
        pins[str(path)]=sha;return path
    def read(path):
        path=mapper.resolve(path);raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        if str(path) in pins and pins[str(path)]!=sha:raise ValueError('Input version changed: '+str(path))
        pins[str(path)]=sha;return json.loads(raw.decode('utf-8'))
    graph=read(study/'cup-segment-pose-graph/summary.json');holdout=read(study/'cup-segment-edge-holdout/summary.json')
    for record in [graph,holdout]:
        for path,sha in record['input_sha256'].items():pin(path,sha)
    for path in [Path(__file__),root/'src/reconstruction_probe/registration_observability.py',root/'web/studio/constraint_diagnostic.html']:pin(path)
    if graph['scan_id']!=holdout['scan_id']:raise ValueError('Different scan identities')
    segments={}
    for row in graph['segments']:
        path=pin(row['path']);records,_=map_ply_vertices(path)
        points=np.column_stack([records[n] for n in ['x','y','z']]).astype(float)
        normals=np.column_stack([records[n] for n in ['nx','ny','nz']]).astype(float);del records
        if not np.isfinite(points).all() or not np.isfinite(normals).all() or np.any(np.linalg.norm(normals,axis=1)<1e-12):raise ValueError('Invalid stored geometry or normals')
        normals/=np.linalg.norm(normals,axis=1)[:,None]
        segments[row['fragment_id']]=(points,normals,cKDTree(points))
    out.mkdir(parents=True);results=[]
    for edge in graph['edges']:
        source,target=edge['source'],edge['target'];sp,sn,_=segments[source];tp,tn,tree=segments[target]
        transform=np.array(edge['transform_m'],float);center0=np.array(graph['center_original_scan_mm'])
        transform[:3,3]=center0+1000*transform[:3,3]-transform[:3,:3]@center0
        center=tp.mean(0);length=float(np.sqrt(np.mean(np.sum((tp-center)**2,axis=1))))
        variants={};arrays={}
        for label,matrix in [('saved_relative_identity',np.eye(4)),('geometric_training_candidate',transform)]:
            moved=sp@matrix[:3,:3].T+matrix[:3,3];normal=sn@matrix[:3,:3].T
            distances,neighbors=tree.query(moved,workers=1)
            normal_dot=np.abs(np.einsum('ij,ij->i',normal,tn[neighbors]));reverse=cKDTree(moved).query(tp,workers=1)[0]
            variants[label]=dict(moved=moved,distances=distances,neighbors=neighbors,normal_dot=normal_dot,reverse=reverse)
            for field in ['moved','distances','neighbors','normal_dot']:arrays[label+'_'+field]=variants[label][field]
        thresholds=[]
        for threshold in [1.5,3.,6.]:
            selections={k:(v['distances']<=threshold)&(v['normal_dot']>=np.cos(np.deg2rad(30))) for k,v in variants.items()}
            common=np.logical_and.reduce(list(selections.values()));rows=[]
            for label,v in variants.items():
                selected=selections[label];ids=v['neighbors'][selected]
                spectrum=lambda mask:constraint_spectrum(v['moved'][mask],tn[v['neighbors'][mask]],center,length) if np.count_nonzero(mask)>=6 else None
                rows.append(dict(label=label,correspondences=int(selected.sum()),
                    source_points=len(sp),target_points=len(tp),
                    source_distance_coverage=float(np.mean(v['distances']<=threshold)),
                    target_distance_coverage=float(np.mean(v['reverse']<=threshold)),
                    unique_target_points=int(len(np.unique(ids))),
                    matched_distance_median_mm=float(np.median(v['distances'][selected])) if selected.any() else None,
                    matched_point_to_plane_rms_mm=float(np.sqrt(np.mean(np.einsum('ij,ij->i',v['moved'][selected]-tp[ids],tn[ids])**2))) if selected.any() else None,
                    all_matches=spectrum(selected),common_query_points=spectrum(common)))
            thresholds.append(dict(distance_threshold_mm=threshold,common_query_points=int(common.sum()),variants=rows))
        np.savez_compressed(out/f'edge-{source}-to-{target}.npz',source_points_mm=sp,target_points_mm=tp,target_normals=tn,**arrays)
        old=next(h for h in holdout['edges'] if h['source']==source and h['target']==target)
        prior=[dict(label=v['label'],**v['thresholds'][0]) for v in old['combined']]
        result=dict(source=source,target=target,original_training_gate_passed=edge['accepted'],thresholds=thresholds,
            previously_recorded_reserved_depth_2mm=prior,transform_mm=transform.tolist())
        results.append(result)
        three=thresholds[1]
        print(json.dumps(dict(edge=[source,target],original_gate=edge['accepted'],common=three['common_query_points'],
            candidate_ratio=three['variants'][1]['all_matches']['smallest_to_largest_ratio'],
            candidate_common_ratio=three['variants'][1]['common_query_points']['smallest_to_largest_ratio'] if three['variants'][1]['common_query_points'] else None)),flush=True)
    for path,sha in pins.items():
        if file_sha256(Path(path))!=sha:raise ValueError('Input changed during diagnostic: '+path)
    summary=dict(status='local_constraint_diagnostic_not_acceptance_or_physical_uncertainty',scan_id=graph['scan_id'],
        edges=results,input_sha256=pins,normal_source='Existing training PLY normals, normalized without refitting',
        normalized_jacobian='[cross((transformed_source_mm - target_center_mm)/target_rms_radius_mm, nearest_target_normal), nearest_target_normal]',
        perturbation='rotation radians about target center; translation / target RMS radius',
        gram='mean(J.T @ J); rows may be strongly correlated, no independent-noise likelihood assumed',
        normal_angle_gate_deg=30.,distance_thresholds_mm=[1.5,3.,6.],
        reference='https://www.cs.cmu.edu/~kaess/pub/Zhang16icra.html',
        limitations=['This is our stated normalized point-to-plane local diagnostic, not a reproduction of the cited full estimator.',
          'Fixed nearest-neighbor linearization cannot decide global correctness or uniqueness on a symmetric object.',
          'A well-conditioned local solution may still be a wrong alignment; spectra do not replace manual correspondences or reserved-depth conflict checks.',
          'Common query IDs control source point selection between variants; target associations and normals may still change.',
          'Fragment boundaries and reserved-depth results were previously viewed. No new untouched holdout or physical ground truth is introduced.',
          'The one-percent display line is a sensitivity reference, not an accept/reject gate. Changing normalization length, correspondence threshold, or normal estimation affects ratios.',
          'No source geometry, original pose, accepted-edge decision, fragment plan, or reconstruction is changed.'])
    save(out/'summary.json',summary)
    template=(root/'web/studio/constraint_diagnostic.html').read_text(encoding='utf-8')
    page=template.replace('__CONSTRAINT_DATA__',json.dumps(summary,ensure_ascii=False,allow_nan=False).replace('<',chr(92)+'u003c'))
    (out/'review.html').write_text(page,encoding='utf-8')
    print(json.dumps(dict(status=summary['status'],edges=len(results),out=str(out))),flush=True)


if __name__=='__main__':main()

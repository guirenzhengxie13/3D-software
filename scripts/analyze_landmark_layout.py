"""Synthetic landmark perturbation on a real training cloud; not scanner accuracy."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from reconstruction_probe.marker_refinement import rigid_alignment
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.ply_layout import map_ply_vertices


def farthest_four(points,ids):
    subset=points[ids];chosen=[int(np.argmax(np.sum((subset-subset.mean(0))**2,axis=1)))];distance=np.sum((subset-subset[chosen[0]])**2,axis=1)
    for _ in range(3):
        chosen.append(int(np.argmax(distance)));distance=np.minimum(distance,np.sum((subset-subset[chosen[-1]])**2,axis=1))
    return np.asarray(ids)[chosen]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(args.out)
    if out.exists() or root/'reports' not in out.parents:parser.error('Use a new folder strictly within workspace/reports')
    source=root/'reports/range2-study-20261018/experiments/cup-segment-pose-graph/segment-0-training-mm.ply'
    template=root/'web/studio/landmark_layout_diagnostic.html'
    inputs={str(p):file_sha256(p) for p in [source,Path(__file__),root/'src/reconstruction_probe/marker_refinement.py',template]}
    rows,_=map_ply_vertices(source);points=np.column_stack([rows[n] for n in ['x','y','z']]).astype(float);del rows
    if not np.isfinite(points).all():raise ValueError('Expected finite training geometry')
    center=points.mean(0);origin=int(np.argmin(np.sum((points-center)**2,axis=1)));near=cKDTree(points).query(points[origin],k=16)[1]
    choices=dict(wide=farthest_four(points,np.arange(len(points))),local=farthest_four(points,near))
    random=np.random.default_rng(20261023);standard=random.normal(size=(256,4,3));digest=hashlib.sha256(standard.astype('<f8').tobytes()).hexdigest();layouts=[]
    for label,ids in choices.items():
        anchors=points[ids];cov=np.linalg.eigvalsh(np.cov(anchors,rowvar=False,bias=True))[::-1];ratio=float(cov[1]/cov[0]);radius=float(np.sqrt(cov.sum()))
        if len(set(ids.tolist()))!=4 or ratio<=1e-6:raise ValueError('Layout must pass the existing source noncollinearity check')
        identity=rigid_alignment(anchors,anchors)
        if np.linalg.norm(points@identity[:3,:3].T+identity[:3,3]-points,axis=1).max()>1e-7:raise ValueError('Noiseless identity control failed')
        results=[]
        for sigma in [.1,.2,.5]:
            fit=[];whole=[];frontend_rejections=0
            for error in standard*sigma:
                target=anchors+error;values=np.linalg.eigvalsh(np.cov(target,rowvar=False,bias=True))[::-1]
                if values[1]<=values[0]*1e-6:frontend_rejections+=1
                matrix=rigid_alignment(anchors,target);prediction=anchors@matrix[:3,:3].T+matrix[:3,3];all_points=points@matrix[:3,:3].T+matrix[:3,3]
                fit.append(float(np.sqrt(np.mean(np.sum((prediction-target)**2,axis=1)))))
                whole.append(float(np.sqrt(np.mean(np.sum((all_points-points)**2,axis=1)))))
            results.append(dict(synthetic_target_coordinate_sigma_mm=sigma,trials=len(fit),fitted_landmark_rmse_mm=fit,
                known_identity_full_cloud_rms_displacement_mm=whole,
                fit_median_mm=float(np.median(fit)),full_cloud_median_mm=float(np.median(whole)),full_cloud_p90_mm=float(np.percentile(whole,90)),
                target_layouts_rejected_by_existing_frontend_ratio=frontend_rejections))
        layouts.append(dict(label=label,source_point_ids=ids.tolist(),source_rms_radius_mm=radius,source_second_to_first_variance_ratio=ratio,results=results))
    for p,sha in inputs.items():
        if file_sha256(Path(p))!=sha:raise ValueError('Input changed during perturbation experiment: '+p)
    summary=dict(status='synthetic_landmark_layout_sensitivity_not_scanner_accuracy',source_points=len(points),
        true_transform=np.eye(4).tolist(),source_identity='Original training point IDs; target anchors synthetically perturbed from those same coordinates',
        random_seed=20261023,common_standard_noise_sha256=digest,noise_model='Independent Gaussian target-coordinate perturbations; assumed, not measured user/scanner errors',
        layouts=layouts,input_sha256=inputs,new_physical_scans=0,reference='https://pubmed.ncbi.nlm.nih.gov/9874293/',
        limitations=['This is a controlled counterexample with a known identity mapping, not real cross-fragment landmark approval.',
            'The chosen Gaussian sigma is not a calibrated model of scanner depth noise or human picking uncertainty.',
            'Farthest-point anchors on a real training cloud are not necessarily identifiable physical landmarks.',
            'Global RMS displacement compares the same original point IDs under known synthetic truth; it is not nearest-surface distance or an independent real heldout test.',
            'Only two four-anchor layouts on one existing point cloud are studied. No automatic acceptance threshold, pose correction, or reconstruction is changed.'])
    out.mkdir(parents=True);(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    page=template.read_text(encoding='utf-8').replace('__LAYOUT_DATA__',json.dumps(summary,ensure_ascii=False,allow_nan=False).replace('<',chr(92)+'u003c'))
    (out/'review.html').write_text(page,encoding='utf-8')
    print(json.dumps(dict(status=summary['status'],source_points=len(points),layouts=[dict(label=l['label'],radius_mm=l['source_rms_radius_mm'],fit_median_mm=l['results'][1]['fit_median_mm'],whole_median_mm=l['results'][1]['full_cloud_median_mm'],whole_p90_mm=l['results'][1]['full_cloud_p90_mm']) for l in layouts])),flush=True)


if __name__=='__main__':main()

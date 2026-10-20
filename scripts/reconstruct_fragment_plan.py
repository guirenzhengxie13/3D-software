"""Re-fuse one explicitly selected fragment component from original saved depths."""

import os
os.environ.setdefault('OMP_NUM_THREADS','4')

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from experiment_color_seeded_roi import optical_points
from reconstruct_scans import optical_to_pose_axes, reconstruct, write_json
from reconstruction_probe.fragment_plan import compile_fragment_plan
from reconstruction_probe.multi_scan import FrameKey, rigid
from reconstruction_probe.offline import file_sha256


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--decoded',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--saved-control',action='store_true',help='Same selected frames and original ROI, with every correction set to identity')
    args=parser.parse_args();decoded=args.decoded.resolve();plan_path=args.plan.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    plan=read(plan_path);index_path=decoded/'index.json';index=read(index_path);compiled=compile_fragment_plan(plan,index['scan_id'],file_sha256(index_path),[f['id'] for f in index['frames']])
    if sum(row.get('parent_fragment_id') is None for row in plan['fragments'])!=1:
        parser.error('One rooted fragment component per fusion is required; keep unresolved components separate')
    inputs=[plan_path,index_path]
    for name,digest in plan.get('input_sha256',{}).items():
        path=Path(name)
        if not path.is_file() or file_sha256(path)!=digest:raise ValueError('Fragment-plan reference changed: '+name)
        inputs.append(path)
    original={rid:rigid(np.load(decoded/f'frame_{rid:010d}'/'pose_optimized.npy',allow_pickle=False)) for rid in compiled['selected_frame_ids']}
    corrections={fragment:(np.eye(4) if args.saved_control else matrix) for fragment,matrix in compiled['corrections'].items()}
    overrides={rid:corrections[compiled['ownership'][FrameKey(index['scan_id'],rid)]]@matrix for rid,matrix in original.items()}
    bounds=plan.get('selection_roi_original_scan_mm');digest=hashlib.sha256();selected_count=0
    if bounds is not None:
        bounds=np.asarray(bounds,float)
        if bounds.shape!=(2,3) or not np.isfinite(bounds).all() or np.any(bounds[1]<=bounds[0]):raise ValueError('Invalid original-scan ROI bounds')
    def select_depth(depth,updated_pose,rid):
        nonlocal selected_count
        result=depth.copy();removed=0
        if bounds is not None:
            ids,xyz=optical_points(depth,index['intrinsics']['Pl']);native=(xyz*optical_to_pose_axes(index))@original[rid][:3,:3].T+original[rid][:3,3]
            kept=np.all((native>=bounds[0])&(native<=bounds[1]),axis=1);result.ravel()[ids[~kept]]=0;removed=int((~kept).sum())
        digest.update(np.array([rid],'<u8').tobytes()+result.astype('<f4').tobytes());selected_count+=1
        return result,removed
    result=reconstruct(decoded,out,.6,2.4,3.,1,True,pose_overrides=overrides,frame_depth_filter=select_depth,
        evaluate_vendor=False,bounds_override_mm=bounds,tsdf_backend='tensor',tsdf_weight_threshold=3.,
        coordinate_frame='explicit_fragment_component_'+index['scan_id'],
        reconstruction_note='Explicit fragment plan: '+plan['decision']+('; saved-pose control' if args.saved_control else '; hierarchical corrections applied')+'. All selected depths now integrated, including earlier reserved records; this output is a demonstration, not heldout evaluation.')
    if selected_count!=len(original) or result['integrated_frames']!=len(original):raise ValueError('Selected fragment frames were not integrated exactly once')
    np.savez_compressed(out/'applied-poses.npz',**{f'pose_{rid}':matrix for rid,matrix in overrides.items()})
    summary=dict(status='explicit_fragment_component_candidate_not_promoted',scan_id=index['scan_id'],saved_control=args.saved_control,
        decision=plan['decision'],selected_frames=len(original),selected_frame_ids=compiled['selected_frame_ids'],
        selected_depth_with_frame_ids_sha256=digest.hexdigest(),quality=result['quality'],
        corrections_by_fragment={str(key):value.tolist() for key,value in corrections.items()},
        frame_fragment_ids={str(key.frame_id):fragment for key,fragment in compiled['ownership'].items()},
        path=str(out/index['scan_id']/'tsdf_pointcloud_mm.ply'),input_sha256={str(path):file_sha256(path) for path in inputs},
        limitations=['This manifest selects one explicit connected component; omitted source frames remain available and are not labeled invalid.',
          'All selected frames, including prior reserved frames, now enter this demonstration surface.',
          'Transform provenance and an explicit selection decision are recorded, but do not prove physical correctness.',
          'Spatial selection uses each original pose, so pose corrections do not silently change selected source pixels.',
          'No source scan, original pose or existing model is overwritten.'])
    write_json(out/'summary.json',summary);print(json.dumps(dict(selected_frames=len(original),sha256=digest.hexdigest(),quality=result['quality'])),flush=True)


if __name__=='__main__':main()

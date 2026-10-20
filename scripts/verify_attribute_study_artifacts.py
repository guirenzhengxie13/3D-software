"""Validate completed study provenance, linked files and embedded viewer data."""

import argparse
import base64
import csv
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import numpy as np

from reconstruction_probe.offline import file_sha256


class Links(HTMLParser):
    def __init__(self):super().__init__();self.values=[]
    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if key in ("href","src") and value and not value.startswith(("http:","https:","data:","#")):
                self.values.append(value)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    args=parser.parse_args();root=args.study.resolve();errors=[];models=0;main_frames=0;input_hashes=0;viewers=0;links=0;workbenches=0
    for path in root.rglob("reconstruction.json"):
        report=json.loads(path.read_text(encoding="utf-8"));index=root/"decoded"/report["scan_id"]/"index.json"
        if report.get("decoded_index_sha256") != file_sha256(index):errors.append("model input hash mismatch: "+str(path))
        for name in ("tsdf_pointcloud_mm.ply","tsdf_mesh_mm.ply","tsdf_mesh_mm.obj"):
            if not(path.parent/name).is_file():errors.append("missing model: "+str(path.parent/name))
        models+=1
        if path.parent.parent == root/"reconstruction":main_frames+=report["integrated_frames"]
    for path in root.rglob("summary.json"):
        summary=json.loads(path.read_text(encoding="utf-8"))
        if isinstance(summary,dict):
            for name,digest in summary.get("input_sha256",{}).items():
                input_hashes+=1
                if not Path(name).is_file() or file_sha256(Path(name)) != digest:
                    errors.append("diagnostic input hash mismatch: "+name)
        if isinstance(summary,dict) and "pairs" in summary:
            for row in summary["pairs"]:
                for name,digest in row.get("source_sha256",{}).items():
                    input_hashes+=1
                    if file_sha256(Path(name)) != digest:errors.append("comparison input hash mismatch: "+name)
    for path in root.rglob("*-registration.json"):
        registration=json.loads(path.read_text(encoding="utf-8"))
        for kind in ("source","reference"):
            if kind+"_path" in registration:
                input_hashes+=1
                name=registration[kind+"_path"]
                if file_sha256(Path(name)) != registration[kind+"_sha256"]:
                    errors.append("registration input hash mismatch: "+name)
    for path in root.rglob("*.html"):
        document=path.read_text(encoding="utf-8");parser=Links();parser.feed(document)
        for link in parser.values:
            links+=1
            if not(path.parent/link).exists():errors.append("missing linked artifact: "+str(path.parent/link))
        match=re.search(r'<script id="review-data" type="application/json">(.*?)</script>',document,re.S)
        if match:
            data=json.loads(match[1]);viewers+=1
            for cloud in data["clouds"]:
                xyz=np.frombuffer(base64.b64decode(cloud["xyz"]),"<f4");rgb=np.frombuffer(base64.b64decode(cloud["rgb"]),np.uint8)
                if len(xyz)!=cloud["displayPoints"]*3 or len(rgb)!=len(xyz) or not np.isfinite(xyz).all():
                    errors.append("malformed viewer cloud: "+str(path)+" "+cloud["label"])
        alignment=re.search(r'<script id="alignment-data" type="application/json">(.*?)</script>',document,re.S)
        if alignment:
            data=json.loads(alignment[1]);workbenches+=1
            from reconstruction_probe._open3d import require_open3d
            o3d=require_open3d()
            for cloud in data['clouds']:
                xyz=np.frombuffer(base64.b64decode(cloud['xyz']),'<f4').reshape(-1,3)
                rgb=np.frombuffer(base64.b64decode(cloud['rgb']),np.uint8);ids=np.frombuffer(base64.b64decode(cloud['ids']),'<u4')
                if len(xyz)!=cloud['displayPoints'] or len(rgb)!=len(xyz)*3 or len(ids)!=len(xyz) or not np.isfinite(xyz).all():
                    errors.append('malformed landmark preview: '+str(path));continue
                source=Path(cloud['path']);input_hashes+=1
                if not source.is_file() or file_sha256(source)!=cloud['sourceSha256']:
                    errors.append('landmark source hash mismatch: '+str(source));continue
                actual=np.asarray(o3d.io.read_point_cloud(str(source)).points)
                if len(actual)!=cloud['originalPoints'] or np.any(ids>=len(actual)) or not np.array_equal(actual[ids].astype('<f4'),xyz):
                    errors.append('landmark original point IDs mismatch: '+str(path))
            reference=data['candidateReference'];input_hashes+=1
            if file_sha256(Path(reference['path']))!=reference['sha256']:errors.append('landmark candidate reference changed: '+str(path))
    corrected=0
    for path in (root/"decoded").glob("*/index.json"):
        index=json.loads(path.read_text(encoding="utf-8"))
        for frame in index["frames"]:
            if frame.get("embedded_rgba"):
                with np.load(path.parent/f"frame_{frame['id']:010d}"/"frame.npz",allow_pickle=False) as saved:
                    if int(saved["color_layout_version"])!=2:errors.append("wrong color version: "+str(path))
                corrected+=1
    paired_points=0;paired_targets=0
    paired=root/"experiments/cup-piecewise-crosscheck/summary.json"
    if paired.exists():
        metadata=json.loads(paired.read_text(encoding="utf-8"));previous_samples=None
        for row in metadata["results"]:
            path=paired.parent/(row["target_id"]+"-paired-evidence.npz")
            with np.load(path,allow_pickle=False) as saved:
                ids,pixels,xyz=saved["frame_ids"],saved["pixel_ids"],saved["xyz_source_mm"]
                digest=hashlib.sha256(ids.astype("<i8").tobytes()+pixels.astype("<i8").tobytes()+xyz.astype("<f8").tobytes()).hexdigest()
                if digest!=metadata["source_sample_sha256"] or len(ids)!=metadata["sampled_points"]:
                    errors.append("paired sample digest/size mismatch: "+str(path))
                if previous_samples is not None and any(not np.array_equal(a,b) for a,b in zip(previous_samples,(ids,pixels,xyz))):
                    errors.append("cross-target source sample mismatch: "+str(path))
                previous_samples=(ids.copy(),pixels.copy(),xyz.copy())
                for arm in ("whole_scan_control","piecewise_candidate"):
                    support,conflict,occluded,observed=[saved[arm+"_"+name] for name in ("support","conflict","occluded","observed")]
                    if not np.array_equal(support+conflict+occluded,np.broadcast_to(observed,support.shape)):
                        errors.append("nonexhaustive signed depth evidence: "+str(path))
                    if np.any(support[1]<support[0]) or np.any(conflict[1]>conflict[0]) or np.any(occluded[1]>occluded[0]):
                        errors.append("nonmonotone tolerance evidence: "+str(path))
                expected_common=(saved["whole_scan_control_observed"]>=3)&(saved["piecewise_candidate_observed"]>=3)
                if not np.array_equal(saved["common_observed"],expected_common):
                    errors.append("wrong common-observation mask: "+str(path))
                for threshold in row["thresholds"]:
                    for name,expected in [("all",len(ids)),("common_observed",int(expected_common.sum()))]:
                        if np.sum(threshold["transitions"][name]["rows_before_columns_after"])!=expected:
                            errors.append("paired transition total mismatch: "+str(path))
                paired_targets+=1;paired_points=len(ids)
    coverage_points=0
    for path in root.rglob('coverage-data.npz'):
        with np.load(path,allow_pickle=False) as saved:
            n=len(saved['xyz_scan_mm']);frames=len(saved['frame_ids']);bits=saved['support_view_bits'];expanded=np.unpackbits(bits,axis=1,bitorder='little')
            if np.any(expanded[:,frames:]) or not np.array_equal(expanded[:,:frames].sum(1),saved['support_counts'][0]):
                errors.append('coverage support bitmask mismatch: '+str(path))
            if not np.array_equal(saved['support_counts']+saved['conflict_counts']+saved['occluded_counts'],np.broadcast_to(saved['observed_counts'],(2,n))):
                errors.append('nonexhaustive coverage evidence: '+str(path))
            if not np.array_equal(saved['support_by_id_high'].sum(0),saved['support_counts'][0]):
                errors.append('coverage group support mismatch: '+str(path))
            present=saved['support_counts'][0]>0;angles=saved['first_support_max_separation_deg']
            if not np.isfinite(angles[present]).all() or np.any(angles[present]<0) or np.any(angles[present]>180):errors.append('invalid coverage angles: '+str(path))
            meta=json.loads((path.parent/'summary.json').read_text(encoding='utf-8'))
            from reconstruction_probe._open3d import require_open3d
            actual=np.asarray(require_open3d().io.read_point_cloud(meta['geometry_path']).points)
            ids=saved['source_point_indices']
            if len(np.unique(ids))!=n or np.any(ids>=len(actual)) or not np.array_equal(actual[ids],saved['xyz_scan_mm']):errors.append('coverage surface point provenance mismatch: '+str(path))
            coverage_points+=n
    direct_frames=0;direct_samples=0;direct_candidates=0
    direct=root/'experiments/cup-direct-split'
    if (direct/'split.json').exists():
        split=json.loads((direct/'split.json').read_text(encoding='utf-8'));train=set();heldout=set()
        for group in split['groups']:
            train.update(group['training_ids']);heldout.update(group['heldout_ids'])
            report_path=direct/f"training-group-{group['id_high']}"/split['scan_id']/'reconstruction.json'
            trained=json.loads(report_path.read_text(encoding='utf-8'))
            if {f['id'] for f in trained['frames'] if f['status']=='integrated'}!=set(group['training_ids']):errors.append('training surface uses wrong frame split: '+str(report_path))
        if train&heldout:errors.append('direct fragment train/heldout overlap')
        previous=None
        for name in ['evaluation','color-evaluation']:
            metadata_path=direct/name/'summary.json'
            if not metadata_path.exists():continue
            metadata=json.loads(metadata_path.read_text(encoding='utf-8'))
            with np.load(direct/name/'heldout-evidence.npz',allow_pickle=False) as saved:
                if set(saved['frame_ids'].tolist())!=heldout:errors.append('heldout query uses wrong source frame IDs: '+name)
                arrays=[saved[key] for key in ['frame_ids','pixel_ids','xyz_original_mm']]
                if previous is not None and any(not np.array_equal(a,b) for a,b in zip(previous,arrays)):errors.append('geometric/color heldout samples differ')
                previous=[a.copy() for a in arrays]
                for row in metadata['results']:
                    label=row['label'];support,conflict,occluded,observed=[saved[label+'_'+key] for key in ['support','conflict','occluded','observed']]
                    if not np.array_equal(support+conflict+occluded,np.broadcast_to(observed,support.shape)):errors.append('incomplete direct heldout evidence: '+label)
                    direct_candidates+=1
                direct_samples=len(saved['frame_ids'])
        direct_frames=len(heldout)
    multi_fusions=0;multi_frames=0;multi_samples=0
    workflow_runs=0;workflow_operations=0
    from reconstruction_probe.workflow import inventory
    for path in root.glob('workflow-*/state.json'):
        state=json.loads(path.read_text(encoding='utf-8'));workflow_runs+=1
        if file_sha256(path.parent/'plan.json')!=state['plan_sha256']:errors.append('workflow recipe changed: '+str(path))
        for row in state['nodes']:
            if row['status']!='completed':continue
            workflow_operations+=1
            if inventory(path.parent/'nodes'/row['id'])!=row['output_sha256']:errors.append('workflow output revision changed: '+row['id'])
            for name,digest in row['input_sha256'].items():
                if file_sha256(Path(name))!=digest:errors.append('workflow input revision changed: '+name)
    multi=root/'experiments/cup-multi-scan-tsdf'
    if (multi/'summary.json').exists():
        metadata=json.loads((multi/'summary.json').read_text(encoding='utf-8'));joint={s['scan_id']:s for s in metadata['results'][-1]['source_contributions']}
        expected_compound=set()
        for source in joint.values():
            index=json.loads((Path(source['decoded_directory'])/'index.json').read_text(encoding='utf-8'))
            expected_compound.update((source['scan_id'],f['id']) for f in index['frames'])
        for result in metadata['results']:
            report_path=multi/result['label']/'fusion-report.json';actual=json.loads(report_path.read_text(encoding='utf-8'))
            if actual!=result:errors.append('multi-scan fusion report mismatch: '+str(report_path))
            for name,digest in actual['output_sha256'].items():
                if file_sha256(report_path.parent/name)!=digest:errors.append('multi-scan output hash mismatch: '+str(report_path.parent/name))
            with (report_path.parent/'frame-contributions.csv').open(encoding='utf-8',newline='') as stream:records=list(csv.DictReader(stream))
            keys=[(r['scan_id'],int(r['frame_id'])) for r in records]
            if len(keys)!=len(set(keys)) or len(keys)!=actual['integrated_frames']:errors.append('multi-scan compound frame collision/count error')
            if any(r['capture_timestamp']!='' for r in records):errors.append('invented multi-scan capture timestamp')
            for source in actual['source_contributions']:
                if source!=joint[source['scan_id']]:errors.append('single/joint source input contribution mismatch')
                count=sum(r['scan_id']==source['scan_id'] for r in records)
                if count!=source['frame_count']:errors.append('multi-scan per-source count mismatch')
            if result['label']=='joint_raw_depth':
                if set(keys)!=expected_compound:errors.append('multi-scan missing/extra compound source frames')
                multi_frames=len(keys)
            multi_fusions+=1
        for result in metadata['results']:
            path=multi/'depth-evidence'/(result['label']+'-evidence.npz')
            if not path.exists():continue
            with np.load(path,allow_pickle=False) as saved:
                n=len(saved['xyz_shared_mm']);observed=saved['observed_counts'];support=saved['support_counts'];conflict=saved['conflict_counts'];occluded=saved['occluded_counts']
                if not np.array_equal(support+conflict+occluded,np.broadcast_to(observed[:,None,:],(2,2,n))):errors.append('nonexhaustive multi-scan depth evidence')
                if np.any(support[:,1]<support[:,0]) or np.any(conflict[:,1]>conflict[:,0]) or np.any(occluded[:,1]>occluded[:,0]):errors.append('nonmonotone multi-scan tolerance evidence')
                frames=len(saved['frame_ids']);flags=np.unpackbits(saved['support_view_bits'],axis=1,bitorder='little')
                if flags[:,frames:].any():errors.append('nonzero multi-scan bit padding')
                for source_index in range(2):
                    if not np.array_equal(flags[:,:frames][:,saved['frame_scan_indices']==source_index].sum(1),support[source_index,0]):errors.append('multi-scan per-source support bitmask mismatch')
                supported=support[:,0]>=2;category=np.full(n,3,np.uint8);category[supported[0]&supported[1]]=0;category[supported[0]&~supported[1]]=1;category[~supported[0]&supported[1]]=2
                if not np.array_equal(category,saved['categories']) or not np.array_equal((conflict[:,0]>=3).any(0),saved['repeated_conflict_mask']):errors.append('multi-scan class evidence mismatch')
                from reconstruction_probe._open3d import require_open3d
                original=np.asarray(require_open3d().io.read_point_cloud(str(multi/result['label']/'tsdf_pointcloud_mm.ply')).points)
                if not np.array_equal(original[saved['source_point_indices']],saved['xyz_shared_mm']):errors.append('multi-scan surface vertex provenance mismatch')
                if {(saved['source_scan_ids'][i],int(rid)) for i,rid in zip(saved['frame_scan_indices'],saved['frame_ids'])}!=expected_compound:errors.append('multi-scan evidence missing source frames')
                multi_samples+=n
        sensitivity=multi/'pixel-sensitivity/pixel-sensitivity.npz'
        if sensitivity.exists():
            with np.load(sensitivity,allow_pickle=False) as data:
                total=data['center_conflict_counts'];stable=data['unanimous_neighborhood_conflict_counts']
                mixed=data['mixed_neighborhood_counts'];sparse=data['sparse_neighborhood_counts'];near=data['near_depth_neighbor_counts']
                if not np.array_equal(total,stable+mixed+sparse) or np.any(near>mixed) or np.any(stable>total):errors.append('pixel footprint accounting mismatch')
                with np.load(multi/'depth-evidence/joint_raw_depth-evidence.npz',allow_pickle=False) as original:
                    if not np.array_equal(total,original['conflict_counts']) or not np.array_equal(data['xyz_shared_mm'],original['xyz_shared_mm']):errors.append('pixel sensitivity changed original evidence')
    report={"models_checked":models,"multi_scan_fusions_checked":multi_fusions,"multi_scan_compound_frames_checked":multi_frames,"multi_scan_surface_samples_checked":multi_samples,"workflow_runs_checked":workflow_runs,"workflow_completed_operations_checked":workflow_operations,"main_baseline_integrated_frames":main_frames,"comparison_input_hashes_checked":input_hashes,
        "provenance_input_hashes_checked":input_hashes,"paired_source_samples_checked":paired_points,"paired_depth_targets_checked":paired_targets,
        "standalone_colored_viewers_checked":viewers,"landmark_workbenches_checked":workbenches,"coverage_surface_samples_checked":coverage_points,
        "direct_heldout_frames_checked":direct_frames,"direct_heldout_source_samples_checked":direct_samples,"direct_candidate_evaluations_checked":direct_candidates,
        "local_links_checked":links,"corrected_color_frames":corrected,
        "errors":errors,"actual_webgl_gpu_verified":False,
        "browser_limitation":"Browser app access approval timed out; available in-app browser URL policy rejected file:// navigation."}
    (root/"artifact-validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    if errors:raise SystemExit(1)


if __name__=="__main__":main()

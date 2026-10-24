"""Compare two settings on the identical frozen component and entry script.

Full-surface nearest distances describe disagreement between reconstructions,
never physical error. Optional historical default control checks compatibility.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from build_studio_comparison import build
from reconstruction_probe.fusion_settings import fusion_settings
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.ply_layout import map_ply_vertices


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fine-job',required=True);p.add_argument('--coarse-job',required=True);p.add_argument('--historical-job',default='465fdb3b59b740b2');p.add_argument('--out',required=True);args=p.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);out=mapper.resolve_output(args.out)
    if out.exists() or root/'reports' not in out.parents:p.error('Use a new local report folder')
    pins={}
    def pin(path,expected=None):
        path=mapper.resolve(path);sha=file_sha256(path)
        if expected is not None and sha!=expected:raise ValueError('Recorded output changed: '+str(path))
        if str(path) in pins and pins[str(path)]!=sha:raise ValueError('Input changed during study')
        pins[str(path)]=sha;return path
    def read(path,expected=None):
        path=pin(path,expected);raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=pins[str(path)]:raise ValueError('Input changed during read')
        return mapper.record(json.loads(raw.decode('utf-8')))
    def load(jid):
        if len(jid)!=16 or any(c not in '0123456789abcdef' for c in jid):raise ValueError('Need a recorded job ID')
        folder=root/'reports/web-studio/runs'/jid;job=read(folder/'job.json')
        if job['kind']!='fragment_fusion' or job['status']!='completed':raise ValueError('Use completed paired fragment fusions')
        review=read(folder/'review-original.json',job['reviewed_record_sha256']);pair=read(folder/'result/summary.json');state=read(folder/'result/state.json')
        if state['status']!='completed' or pair['reviewed_plan_sha256']!=job['reviewed_plan_sha256']:raise ValueError('Task completion/provenance mismatch')
        config=fusion_settings(review.get('fusion_parameters'));arms=[]
        for i,label in enumerate(['saved','corrected']):
            node=next(n for n in state['nodes'] if n['id']==label);base=folder/'result/nodes'/label
            if node['status']!='completed':raise ValueError('Incomplete arm')
            summary=read(base/'summary.json',node['output_sha256']['summary.json']);path=mapper.resolve(summary['path']);pin(path,node['output_sha256'][path.relative_to(base).as_posix()]);applied=pin(base/'applied-poses.npz',node['output_sha256']['applied-poses.npz'])
            if summary.get('fusion_parameters',config)!=config:raise ValueError('Arm settings differ from reviewed values')
            if summary['selected_depth_with_frame_ids_sha256']!=pair['selected_depth_with_frame_ids_sha256'] or bool(summary['saved_control'])!=(i==0):raise ValueError('Arm source pixels or identity mismatch')
            records,_=map_ply_vertices(path);xyz=np.column_stack([records[n] for n in ['x','y','z']]).astype(float);del records
            if not np.isfinite(xyz).all() or not len(xyz):raise ValueError('Invalid surface')
            payload={k:v for k,v in summary['input_sha256'].items() if k.endswith(('/frame.npz','/pose_optimized.npy','/index.json')) or k.endswith((chr(92)+'frame.npz',chr(92)+'pose_optimized.npy',chr(92)+'index.json'))}
            for name,sha in payload.items():pin(name,sha)
            with np.load(applied,allow_pickle=False) as z:poses={k:z[k] for k in z.files}
            arms.append(dict(path=path,xyz=xyz,summary=summary,poses=poses,payload=payload,implementation=node['implementation_sha256']))
        return dict(id=jid,config=config,pair=pair,arms=arms)
    fine=load(args.fine_job);coarse=load(args.coarse_job);historical=load(args.historical_job)
    if not fine['config']['voxel_mm']<coarse['config']['voxel_mm']:raise ValueError('Fine voxel must be smaller than coarse')
    for key in ['scan_id','selected_frames','selected_depth_with_frame_ids_sha256']:
        if fine['pair'][key]!=coarse['pair'][key] or fine['pair'][key]!=historical['pair'][key]:raise ValueError('Different source component')
    for path in [Path(__file__),root/'scripts/build_studio_comparison.py',root/'web/studio/setting_sensitivity.html',root/'web/studio/comparison.html',root/'web/studio/point_viewer.js',root/'web/landmark-workbench/registration_math.js',root/'web/landmark-workbench/point_raster.js']:pin(path)
    out.mkdir(parents=True);results=[];palette=np.array([[74,205,180],[180,223,114],[248,185,95],[241,111,114]],np.uint8)
    def describe(dist):return dict(points=len(dist),median_mm=float(np.median(dist)),p90_mm=float(np.quantile(dist,.9)),p95_mm=float(np.quantile(dist,.95)),p99_mm=float(np.quantile(dist,.99)),maximum_mm=float(dist.max()),within=[dict(distance_mm=d,points=int(np.count_nonzero(dist<=d)),fraction=float(np.mean(dist<=d))) for d in [.25,.5,1.,2.]])
    def colored(path,xyz,dist):
        rows=np.empty(len(xyz),dtype=[('x','<f8'),('y','<f8'),('z','<f8'),('red','u1'),('green','u1'),('blue','u1'),('source_vertex_id','<u4')]);rgb=palette[np.searchsorted([.25,.5,1.],dist,side='left')]
        for j,n in enumerate(['x','y','z']):rows[n]=xyz[:,j]
        for j,n in enumerate(['red','green','blue']):rows[n]=rgb[:,j]
        rows['source_vertex_id']=np.arange(len(xyz),dtype='<u4');header='ply\nformat binary_little_endian 1.0\nelement vertex '+str(len(xyz))+'\nproperty double x\nproperty double y\nproperty double z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nproperty uint source_vertex_id\nend_header\n'
        with path.open('wb') as stream:stream.write(header.encode());stream.write(rows.tobytes())
        check,_=map_ply_vertices(path);actual=np.column_stack([check[n] for n in ['x','y','z']]);assert np.array_equal(actual,xyz);assert np.array_equal(check['source_vertex_id'],np.arange(len(xyz)));del check
    for i,label in enumerate(['saved','corrected']):
        a,b,h=fine['arms'][i],coarse['arms'][i],historical['arms'][i]
        if a['implementation']!=b['implementation']:raise ValueError('Two parameter runs used different entry-script bytes')
        if a['payload']!=b['payload'] or a['summary']['selected_frame_ids']!=b['summary']['selected_frame_ids']:raise ValueError('Source frame payloads differ')
        if set(a['poses'])!=set(b['poses']) or any(not np.array_equal(a['poses'][k],b['poses'][k]) for k in a['poses']):raise ValueError('Applied poses differ')
        distances=[cKDTree(b['xyz']).query(a['xyz'],workers=1)[0],cKDTree(a['xyz']).query(b['xyz'],workers=1)[0]]
        legacy=[cKDTree(h['xyz']).query(a['xyz'],workers=1)[0],cKDTree(a['xyz']).query(h['xyz'],workers=1)[0]]
        if len(h['xyz'])!=len(a['xyz']) or max(d.max() for d in legacy)>1e-7:raise ValueError('Current default did not reproduce the historical surface; investigate before comparing settings')
        pages={}
        notes='同一114帧、相同原ROI像素与应用位姿；体素和截断共同变化。最近邻距离只描述两份表面差异，不是物理误差；两模型顶点编号不构成跨模型对应。'
        for mode in ['surface','distance']:
            paths=[a['path'],b['path']]
            if mode=='distance':
                paths=[out/f'{label}-fine-distance.ply',out/f'{label}-coarse-distance.ply']
                for path,arm,dist in zip(paths,[a,b],distances):colored(path,arm['xyz'],dist)
            page=out/f'{label}-{mode}.html';build([str(fine['config']['voxel_mm'])+'mm / '+str(fine['config']['truncation_mm'])+'mm='+str(paths[0]),str(coarse['config']['voxel_mm'])+'mm / '+str(coarse['config']['truncation_mm'])+'mm='+str(paths[1])],page,'相同保存扫描毫米坐标 · '+fine['pair']['scan_id'],notes+(' 原色为最近邻距离分档伪彩，不是物体RGB。' if mode=='distance' else ''),'同帧参数响应 · '+label,budget=60000);pages[mode]=page.name
        np.savez_compressed(out/f'{label}-nearest-distances.npz',fine_to_coarse_mm=distances[0],coarse_to_fine_mm=distances[1])
        result=dict(label=label,fine_points=len(a['xyz']),coarse_points=len(b['xyz']),retained_point_fraction=len(b['xyz'])/len(a['xyz']),fine_to_coarse=describe(distances[0]),coarse_to_fine=describe(distances[1]),same_applied_pose_arrays=True,same_original_payload_files=len(a['payload']),implementation_sha256=a['implementation'],historical_default_bidirectional_max_mm=max(float(d.max()) for d in legacy),historical_default_points=len(h['xyz']),pages=pages);results.append(result);print(json.dumps({k:result[k] for k in ['label','fine_points','coarse_points','historical_default_bidirectional_max_mm']}),flush=True)
    for name,sha in pins.items():
        if file_sha256(Path(name))!=sha:raise ValueError('Study input changed: '+name)
    summary=dict(status='fixed_component_parameter_response_not_physical_accuracy',scan_id=fine['pair']['scan_id'],fine_job=fine['id'],coarse_job=coarse['id'],historical_job=historical['id'],fine_settings=fine['config'],coarse_settings=coarse['config'],changed_parameters=[k for k in fine['config'] if fine['config'][k]!=coarse['config'][k]],selected_frames=fine['pair']['selected_frames'],original_roi_pixel_sha256=fine['pair']['selected_depth_with_frame_ids_sha256'],arms=results,input_sha256=pins,limitations=['Both voxel and truncation change together; differences cannot be assigned to only one parameter.','Nearest distances between two derived surfaces are not physical accuracy, true corresponding points, independent evaluation or missing-geometry recovery.','Same applied pose arrays, selected source pixels and input payload hashes; no additional registration or candidate acceptance.','The current default reproduces each historical surface as a point set, not a claim of zero physical error.','Only 114 of 336 records enter all these surfaces; other 222 remain excluded.','Distance colors are derived display data, not physical RGB; full arrays are compared, browser previews may be sampled.'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    template=(root/'web/studio/setting_sensitivity.html').read_text(encoding='utf-8');(out/'review.html').write_text(template.replace('__SETTING_DATA__',json.dumps(summary,ensure_ascii=False,allow_nan=False).replace('<',chr(92)+'u003c'),1),encoding='utf-8',newline='\n')
    print(json.dumps(dict(out=str(out),pinned_inputs=len(pins),changed_parameters=summary['changed_parameters'])))


if __name__=='__main__':main()

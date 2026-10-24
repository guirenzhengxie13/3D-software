"""Locate extreme inter-surface differences and query contributing raw depths.

This reuses training/integration views, not independent validation, TSDF voxel
weight provenance or physical ground truth. No geometry or pose is changed.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re

import numpy as np
from scipy.spatial import cKDTree

from experiment_color_seeded_roi import optical_points
from reconstruct_scans import clean_depth_edges,optical_to_pose_axes
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper
from reconstruction_probe.ply_layout import map_ply_vertices
from reconstruction_probe.visibility import project_depth_observations
from reconstruction_probe.web_studio import pack


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--study',required=True);p.add_argument('--out',required=True);args=p.parse_args()
    root=Path(__file__).resolve().parents[1];mapper=PathMapper(root);study=mapper.resolve(args.study);out=mapper.resolve_output(args.out)
    if out.exists() or root/'reports' not in out.parents:p.error('Use a new local report folder')
    pins={}
    def pin(path,expected=None):
        path=mapper.resolve(path);sha=file_sha256(path)
        if expected is not None and sha!=expected:raise ValueError('Study input changed: '+str(path))
        if str(path) in pins and pins[str(path)]!=sha:raise ValueError('Input changed during trace')
        pins[str(path)]=sha;return path
    def read(path):
        path=pin(path);raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=pins[str(path)]:raise ValueError('Input changed during read')
        return mapper.record(json.loads(raw.decode('utf-8')))
    record=read(study/'summary.json')
    for name,sha in record['input_sha256'].items():pin(name,sha)
    for path in [Path(__file__),root/'src/reconstruction_probe/visibility.py',root/'scripts/reconstruct_scans.py',root/'scripts/experiment_color_seeded_roi.py']:pin(path)
    jobs=[root/'reports/web-studio/runs'/record[k] for k in ['fine_job','coarse_job']]
    pairs=[read(j/'result/summary.json') for j in jobs];review=read(jobs[0]/'review-original.json');decoded=mapper.resolve(review['decoded']);index=read(decoded/'index.json');signs=optical_to_pose_axes(index);cal=index['intrinsics']['Pl'];roi=np.array(review['roi'],float) if review.get('roi') is not None else None
    selected=pairs[0]['results'][0]['selected_frame_ids'];frames=[row['id'] for row in index['frames'] if row['id'] in set(selected)];depths={};pixel_digest=hashlib.sha256()
    if len(frames)!=len(selected):raise ValueError('Selected source IDs differ from index')
    for rid in frames:
        folder=decoded/f'frame_{rid:010d}';original=np.load(pin(folder/'pose_optimized.npy'),allow_pickle=False)
        with np.load(pin(folder/'frame.npz'),allow_pickle=False) as z:depth=z['depth_mm'].copy()
        if roi is not None:
            ids,xyz=optical_points(depth,cal);native=(xyz*signs)@original[:3,:3].T+original[:3,3];inside=np.all((native>=roi[0])&(native<=roi[1]),axis=1);depth.ravel()[ids[~inside]]=0
        pixel_digest.update(np.array([rid],'<u8').tobytes()+depth.astype('<f4').tobytes())
        depth=clean_depth_edges(depth,record['fine_settings']['edge_threshold_mm'])[0];depth[depth>=2000]=0;depths[rid]=depth
    if pixel_digest.hexdigest()!=record['original_roi_pixel_sha256']:raise ValueError('ROI before edge cleaning differs from actual integration pixels')
    out.mkdir(parents=True);results=[];palette=np.array([[74,205,180],[180,223,114],[248,185,95],[241,111,114]],np.uint8)
    for i,label in enumerate(['saved','corrected']):
        clouds=[]
        for pair in pairs:
            path=pin(pair['results'][i]['path']);rows,_=map_ply_vertices(path);clouds.append(np.column_stack([rows[k] for k in ['x','y','z']]).astype(float));del rows
        with np.load(pin(study/f'{label}-nearest-distances.npz'),allow_pickle=False) as z:distances=[z['fine_to_coarse_mm'],z['coarse_to_fine_mm']]
        direction=int(distances[1].max()>distances[0].max());source_id=int(distances[direction].argmax());target_id=int(cKDTree(clouds[1-direction]).query(clouds[direction][source_id],workers=1)[1]);ids=[source_id,target_id] if direction==0 else [target_id,source_id];points=np.array([clouds[j][ids[j]] for j in [0,1]])
        rows=[]
        for j in [0,1]:
            own=float(cKDTree(clouds[j]).query(points[j],k=2)[0][1]);rows.append(dict(variant='fine' if j==0 else 'coarse',original_vertex_id=ids[j],xyz_mm=points[j].tolist(),nearest_other_vertex_same_surface_mm=own))
        pose_path=pin(jobs[0]/f'result/nodes/{label}/applied-poses.npz')
        with np.load(pose_path,allow_pickle=False) as z:poses={rid:z[f'pose_{rid}'] for rid in frames}
        observations=[[],[]]
        for rid in frames:
            observed=project_depth_observations(points,poses[rid],depths[rid],cal,signs)
            for n,pixel,delta in zip(observed.point_indices,observed.pixel_indices,observed.signed_delta_mm):observations[int(n)].append(dict(frame_id=str(rid),pixel_id=int(pixel),signed_delta_mm=float(delta)))
        for j,row in enumerate(rows):
            delta=np.array([v['signed_delta_mm'] for v in observations[j]]);row['observed_views']=len(delta);row['thresholds']=[dict(tolerance_mm=t,support_views=int(np.count_nonzero(np.abs(delta)<=t)),free_space_conflict_views=int(np.count_nonzero(delta>t)),occluded_views=int(np.count_nonzero(delta < -t))) for t in [1.,2.,4.]]
        source_page=pin(study/f'{label}-distance.html');html=source_page.read_text(encoding='utf-8');match=re.search(r'(<script id="comparison-data" type="application/json">)(.*?)(</script>)',html,re.S);payload=json.loads(match[2]);payload['title']='最大局部差异回查 · '+label
        payload['notes']+=' 本页只调整初始相机范围，完整预览仍保留；两边列出的关键原顶点已强制包含。该区域不是人工确认的错误。'
        payload['boundsMm']=[(points.min(0)-6).tolist(),(points.max(0)+6).tolist()]
        for j,cloud in enumerate(payload['clouds']):
            shown=np.frombuffer(base64.b64decode(cloud['ids']),'<u4').copy();positions=np.frombuffer(base64.b64decode(cloud['xyz']),'<f4').reshape(-1,3).copy();colors=np.frombuffer(base64.b64decode(cloud['rgb']),np.uint8).reshape(-1,3).copy()
            if ids[j] not in shown:
                shown[-1]=ids[j];positions[-1]=points[j];colors[-1]=palette[np.searchsorted([.25,.5,1.],distances[j][ids[j]],side='left')]
            cloud.update(pack(positions,colors,shown));assert ids[j] in shown
        encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False).replace('<',chr(92)+'u003c');focused=re.sub(r'(<script id="comparison-data" type="application/json">).*?(</script>)',lambda m:m[1]+encoded+m[2],html,count=1,flags=re.S);page=out/f'{label}-focus.html';page.write_text(focused,encoding='utf-8',newline='\n')
        result=dict(label=label,direction='fine_to_coarse' if direction==0 else 'coarse_to_fine',distance_mm=float(distances[direction][source_id]),selected_frames=len(frames),points=rows,page=page.name,depth_trace_is_integration_data_not_holdout=True);results.append(result)
        (out/f'{label}-observations.json').write_text(json.dumps(dict(points=rows,observations=observations),ensure_ascii=False,indent=2),encoding='utf-8',newline='\n');print(json.dumps(result),flush=True)
    for name,sha in pins.items():
        if file_sha256(Path(name))!=sha:raise ValueError('Trace input changed: '+name)
    summary=dict(status='extreme_parameter_disagreement_depth_recheck_not_error_label',original_roi_pixel_sha256=pixel_digest.hexdigest(),roi_before_clean_matches_integration=True,arms=results,fine_settings=record['fine_settings'],coarse_settings=record['coarse_settings'],input_sha256=pins,limits=['Reuses all 114 integration frames; these are not independent heldout measurements.','Projection uses the applied pose and exact ROI-before-3mm-edge-clean order; raw depth beyond 2m is excluded.','Nearest-pixel depth support is not a TSDF interpolation/weight trace or a physical accuracy certificate.','Distance pseudocolors and focused camera bounds do not edit source geometry; full point IDs remain local to each model.'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    page="""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>参数差异的极端位置回查</title><style>:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#0f1925;color:#dceaf5}body{max-width:1380px;margin:auto;padding:22px}p{line-height:1.6}.notice{background:#293249;border-left:4px solid #efbd75;padding:12px}select{padding:9px;background:#24374d;color:inherit}iframe{width:100%;height:760px;border:1px solid #455e76}table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:10px;border-bottom:1px solid #3c5065;text-align:left}.scroll{overflow:auto}a{color:#9cd9eb}</style><h1>平均差异很小，极端位置仍需回查</h1><p class="notice">这些位置是两份参数结果差异最大处，不是已确认的物理错误。原深度回查重用了参与融合的114帧，既不是独立评测，也不是TSDF体素权重追踪。</p><label>位置 <select id="arm"><option value="0">原位姿控制的极端差异</option><option value="1">片段校正的极端差异</option></select></label><p id="facts"></p><div class="scroll"><table><thead><tr><th>表面</th><th>原顶点编号与XYZ mm</th><th>本表面最近其它点 mm</th><th>观测视图</th><th>1mm 支持/冲突/遮挡</th><th>2mm 支持/冲突/遮挡</th><th>4mm 支持/冲突/遮挡</th></tr></thead><tbody id="rows"></tbody></table></div><p>下方相机聚焦两个位置，仍保留完整预览与两侧关键原编号。距离着色请在双栏中选择“原顶点色”，青绿≤0.25mm、浅绿≤0.5mm、橙≤1mm、红&gt;1mm。</p><iframe id="focus" title="极端差异的局部聚焦双栏"></iframe><p><a href="summary.json">完整数值与SHA</a> · <a href="../review.html">完整参数响应</a> · <a href="/">工作台</a></p><script id="tail-data" type="application/json">__TAIL_DATA__</script><script>(()=>{'use strict';const $=id=>document.getElementById(id),data=JSON.parse($('tail-data').textContent);function el(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}function show(){const arm=data.arms[Number($('arm').value)];$('facts').textContent='方向 '+arm.direction+'；两表面距离 '+arm.distance_mm.toFixed(3)+' mm。回查按原ROI筛选后清边，再用应用位姿投影到相同有效深度。';$('rows').replaceChildren();for(const point of arm.points){const row=el('tr','');for(const value of [(point.variant==='fine'?data.fine_settings.voxel_mm:data.coarse_settings.voxel_mm)+'mm表面','#'+point.original_vertex_id+' · '+point.xyz_mm.map(v=>v.toFixed(3)).join(', '),point.nearest_other_vertex_same_surface_mm.toFixed(3),String(point.observed_views),...point.thresholds.map(t=>[t.support_views,t.free_space_conflict_views,t.occluded_views].join(' / '))])row.append(el('td',value));$('rows').append(row);}$('focus').src=arm.page;}$('arm').onchange=show;show();})();</script></html>"""
    (out/'review.html').write_text(page.replace('__TAIL_DATA__',json.dumps(summary,ensure_ascii=False,allow_nan=False).replace('<',chr(92)+'u003c'),1),encoding='utf-8',newline='\n')


if __name__=='__main__':main()

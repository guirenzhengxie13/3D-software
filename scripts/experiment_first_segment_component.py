"""Demonstrate one frozen local segment correction, with unchanged input pixels."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d
from PIL import Image,ImageDraw

from build_attribute_study_report import font,render
from reconstruct_scans import write_json
from reconstruction_probe.offline import file_sha256


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();study=args.study.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);graph_path=study/'experiments/cup-segment-pose-graph/summary.json';graph=read(graph_path);key=graph['scan_id']
    decoded=study/'decoded'/key;index_path=decoded/'index.json';edge=next(row for row in graph['edges'] if row['source']==1 and row['target']==0)
    center=np.array(graph['center_original_scan_mm']);matrix=np.array(edge['transform_m']);matrix[:3,3]=center+1000*matrix[:3,3]-matrix[:3,:3]@center
    segments={row['fragment_id']:row for row in graph['segments']};roi_path=study/'experiments/cup-roi'/(key+'-selection.json');roi=read(roi_path)
    holdout_path=study/'experiments/cup-segment-edge-holdout/summary.json'
    plan=dict(format_version=1,unit='mm',scan_id=key,decoded_index_sha256=file_sha256(index_path),
        decision='Exploratory demonstration of frozen training geometric correction 1->0 after reviewing reserved-depth evidence; not a blind test or promoted whole-scan repair.',
        selection_roi_original_scan_mm=[roi['bounds_min_mm'],roi['bounds_max_mm']],fragments=[
          dict(fragment_id=0,parent_fragment_id=None,frame_ids=segments[0]['all_frame_ids'],transform_to_parent_mm=np.eye(4).tolist()),
          dict(fragment_id=1,parent_fragment_id=0,frame_ids=segments[1]['all_frame_ids'],transform_to_parent_mm=matrix.tolist())],
        input_sha256={str(p):file_sha256(p) for p in [graph_path,roi_path,holdout_path]})
    write_json(out/'fragment-plan.json',plan);results=[];clouds=[]
    for label,control in [('saved_component',True),('corrected_component',False)]:
        command=[sys.executable,'scripts/reconstruct_fragment_plan.py','--decoded',str(decoded),'--plan',str(out/'fragment-plan.json'),'--out',str(out/label)]
        if control:command.append('--saved-control')
        subprocess.run(command,check=True)
        result=read(out/label/'summary.json');results.append(dict(label=label,**result));clouds.append((label,o3d.io.read_point_cloud(result['path'])))
    same=all(results[0][k]==results[1][k] for k in ['selected_frame_ids','selected_frames','selected_depth_with_frame_ids_sha256'])
    if not same:raise ValueError('Component controls used different source pixels or frames')
    write_json(out/'summary.json',dict(status='partial_component_demonstration_not_whole_scan_repair',same_selected_source_pixels=same,
        results=results,input_sha256={str(p):file_sha256(p) for p in [out/'fragment-plan.json',graph_path,holdout_path]},
        limitations=['Only the first 114 of 336 saved records are included, as an explicit local component; omitted records remain intact.',
          'All selected records, including previously reserved depths, now enter this demonstration model.',
          'The selected connection reduced 2mm conflicts in both directions, but reverse 4mm conflicts increased slightly; it is not unconditionally better.',
          'The other segments are not forced into this component and no whole-project success is claimed.']))
    command=[sys.executable,'scripts/build_reconstruction_review.py','--unit','mm','--up-axis','x','--invert-up','--allow-overlay','--max-points','40000','--out',str(out/'review.html'),'--notes','失败工程仅片段0+1，共114帧；原位姿与冻结小校正使用相同原始ROI像素。全部114帧已用于演示融合，不是留出测试，也不是336帧整体修复。']
    for result in results:command+=['--cloud',result['label']+'='+result['path']]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    bounds=(np.min([pc.get_min_bound() for _,pc in clouds],axis=0),np.max([pc.get_max_bound() for _,pc in clouds],axis=0))
    picture=Image.new('RGB',(1000,950),(24,33,47));draw=ImageDraw.Draw(picture)
    for i,((label,pc),row) in enumerate(zip(clouds,results)):
        draw.text((i*500+12,10),label,font=font(21),fill='#edf3fa')
        for j,(yaw,pitch) in enumerate([(1.2,.15),(3.8,.6)]):picture.paste(render(pc,(490,360),yaw=yaw,pitch=pitch,bounds=bounds,gain=1.8),(i*500+5,48+j*380))
        draw.text((i*500+12,830),f"{row['selected_frames']} 帧 · {row['quality']['point_count']:,} 点",font=font(18),fill='#edf3fa')
        draw.text((i*500+12,865),f"主连通面 {row['quality']['largest_component_triangle_fraction']:.1%}",font=font(18),fill='#adbed1')
    draw.text((12,913),'固定原ROI、相同114帧；仅一个局部组件的演示，不能代表全部失败扫描已修好。',font=font(16),fill='#adbed1');picture.save(out/'comparison.png')
    lines=['# 失败工程中一个局部连接的独立融合','','只取片段0和1，共114条保存深度。每条帧的选区由原位姿确定，原关系与冻结小校正使用同一批原始像素，再以0.6mm体素、2.4mm截断和提取权重3融合。其他222条记录保留，不强行加入。','','![相同原像素局部融合](comparison.png)','','| 候选 | 表面点数 | 主连通面 |','| --- | ---: | ---: |']
    for row in results:lines.append(f"| {row['label']} | {row['quality']['point_count']:,} | {row['quality']['largest_component_triangle_fraction']:.2%} |")
    lines+=['','此候选的先前预留检查在2mm下支持增加、冲突减少；反向4mm冲突有小幅增加，不能称为无条件改善。这里的所有114帧已参与融合，模型本身不是留出评测。','','[三维对照](review.html) · [明确帧归属与层级变换](fragment-plan.json) · [全部参数与输入一致性](summary.json) · [预留原深度检查](../cup-segment-edge-holdout/README.md)']
    (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(dict(same_source_pixels=same,results=[dict(label=r['label'],quality=r['quality']) for r in results])),flush=True)


if __name__=='__main__':main()

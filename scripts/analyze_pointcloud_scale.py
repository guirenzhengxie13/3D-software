"""Measure current raw observations, derived surfaces, disk use and RAM bounds."""

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw
import psutil

from build_attribute_study_report import font
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.ply_layout import inspect_ply


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def quantiles(values):
    return dict(zip(['min','p25','median','p75','p90','p95','max'],np.percentile(values,[0,25,50,75,90,95,100]).tolist())) if values else None


def memory_estimates(points):
    return dict(xyz_float32_bytes=points*12,xyz_float64_bytes=points*24,
        xyz_and_rgb_float64_bytes=points*48,xyz_rgb_normals_float64_bytes=points*72,
        xyz_f32_rgb_u8_scan_u32_frame_u64_pixel_u32_bytes=points*31)


def cohort(decoded):
    scans=[];frames=[];source_files={};source_clouds={};indices={}
    for path in sorted(decoded.glob('*/index.json')):
        index=read(path);indices[str(path.resolve())]=file_sha256(path);items=[f for f in index['frames'] if f.get('depth_status')=='decoded']
        points=[f['points'] for f in items];total=sum(points)
        if total!=index['status']['valid_depth_points']:raise ValueError('Frame/index measurement counts differ: '+str(path))
        dense_pixels=sum(f['width']*f['height'] for f in items);npz_bytes=0;jpeg_bytes=0;on_disk_frames=0
        for frame in items:
            folder=path.parent/f"frame_{frame['id']:010d}";npz=folder/'frame.npz';jpeg=folder/'rgb_original.jpg'
            if npz.is_file():npz_bytes+=npz.stat().st_size;on_disk_frames+=1
            if jpeg.is_file():jpeg_bytes+=jpeg.stat().st_size
        if on_disk_frames!=len(items):raise ValueError('Missing decoded frame containers')
        source=Path(index['source_directory'])
        for name in index.get('source_hashes_before',{}):
            original=Path(name)
            if original.is_file():source_files[str(original.resolve())]=original.stat().st_size
        for cloud in source.rglob('*.ply'):
            layout=inspect_ply(cloud);source_clouds[str(cloud.resolve())]=dict(points=layout.vertex_count,faces=layout.face_count,bytes=cloud.stat().st_size)
        scans.append(dict(scan_id=index['scan_id'],frame_count=len(items),valid_depth_observations=total,dense_raster_pixels=dense_pixels,
            occupancy_fraction=total/dense_pixels if dense_pixels else None,frame_point_quantiles=quantiles(points),
            dense_depth_float32_materialized_bytes=dense_pixels*4,decoded_frame_npz_bytes=npz_bytes,verbatim_jpeg_bytes=jpeg_bytes,
            flattened_memory_estimates=memory_estimates(total),index_path=str(path.resolve())))
        frames.extend(points)
    nonempty=[s for s in scans if s['frame_count']];total=sum(s['valid_depth_observations'] for s in scans)
    return dict(decoded_directory=str(decoded.resolve()),projects=len(scans),nonempty_projects=len(nonempty),frames=len(frames),
        valid_depth_observations=total,frame_point_quantiles=quantiles(frames),
        per_scan_observation_quantiles=quantiles([s['valid_depth_observations'] for s in nonempty]),
        dense_depth_float32_materialized_bytes=sum(s['dense_depth_float32_materialized_bytes'] for s in scans),
        decoded_frame_npz_bytes=sum(s['decoded_frame_npz_bytes'] for s in scans),verbatim_jpeg_bytes=sum(s['verbatim_jpeg_bytes'] for s in scans),
        original_unique_files=len(source_files),original_unique_file_bytes=sum(source_files.values()),
        flattened_memory_estimates=memory_estimates(total),scans=scans,original_ply_files=source_clouds,input_sha256=indices)


def gib(value):return value/2**30


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--study',type=Path,required=True)
    parser.add_argument('--old-study',type=Path,default=Path('reports/four-scans'));parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();study=args.study.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);latest=cohort(study/'decoded');older=cohort(args.old_study.resolve()/'decoded')
    main_surfaces=[];derived=[];inputs={**latest['input_sha256'],**older['input_sha256']}
    for path in sorted((study/'reconstruction').glob('*/reconstruction.json')):
        report=read(path);ply=path.parent/'tsdf_pointcloud_mm.ply';layout=inspect_ply(ply)
        if layout.vertex_count!=report['quality']['point_count']:raise ValueError('Surface count/report mismatch')
        inputs[str(path.resolve())]=file_sha256(path)
        main_surfaces.append(dict(scan_id=report['scan_id'],points=layout.vertex_count,mesh_vertices=report['quality']['mesh_vertices'],
            mesh_triangles=report['quality']['mesh_triangles'],ply_bytes=ply.stat().st_size,actual_voxel_mm=report['voxel_mm'],path=str(ply.resolve())))
    for base in [study,args.old_study.resolve()]:
        for path in sorted(base.rglob('tsdf_pointcloud_mm.ply')):
            layout=inspect_ply(path);derived.append(dict(path=str(path.resolve()),points=layout.vertex_count,bytes=path.stat().st_size))
    memory=psutil.virtual_memory();joint=study/'experiments/cup-multi-scan-tsdf/summary.json';joint_report=read(joint) if joint.is_file() else None
    total=latest['valid_depth_observations']+older['valid_depth_observations']
    summary=dict(measured_at_utc=datetime.now(timezone.utc).isoformat(),latest=latest,older=older,
        all_input_cohorts=dict(frames=latest['frames']+older['frames'],valid_depth_observations=total,flattened_memory_estimates=memory_estimates(total)),
        latest_main_surfaces=dict(models=len(main_surfaces),total_points=sum(r['points'] for r in main_surfaces),
            point_quantiles=quantiles([r['points'] for r in main_surfaces]),models_detail=main_surfaces),
        all_derived_surface_files=dict(files=len(derived),points_sum_including_repeated_candidates=sum(r['points'] for r in derived),
            point_quantiles=quantiles([r['points'] for r in derived]),files_detail=derived),
        host_snapshot=dict(logical_cpus=os.cpu_count(),physical_ram_bytes=memory.total,available_ram_bytes=memory.available,
            disk_free_bytes=psutil.disk_usage(study.anchor).free,available_memory_is_transient=True),
        input_sha256=inputs,limitations=['Raw observation counts include repeated measurements of the same physical surface; they are not unique surface points.',
          'Derived-candidate file counts include repeated experiments and must not be added to raw input as new observations.',
          'Array memory estimates exclude temporary copies, spatial indices, library overhead, TSDF voxel blocks, meshes and operating-system caches.',
          'All projects are not assumed to be the same object. Their total is a corpus scale, not one valid joint reconstruction.',
          'Dense raster size includes zero/invalid depth pixels. Nonzero observations and raster pixels are deliberately counted separately.',
          'CPU/backend and actual WebGL GPU display performance are separate; no GPU frame-rate claim is made.'])
    if joint_report:summary['two_scan_joint_example']=dict(raw_frames=joint_report['results'][-1]['integrated_frames'],
        raw_observations=sum(s['raw_valid_pixels'] for s in joint_report['results'][-1]['source_contributions']),
        joint_surface_points=joint_report['results'][-1]['quality']['point_count'])
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    lines=['# 当前点云数量级与内存分析','','这里把传感器保存的逐帧有效深度观测，与融合后的表面点分开计算。前者大量重复观察同一表面，不能当成物体上互不重复的点。','','| 层级 | 数量 |','| --- | ---: |',
        f"| 新批单帧中位数 | {latest['frame_point_quantiles']['median']:,.0f} 点 |",f"| 新批单帧最大 | {latest['frame_point_quantiles']['max']:,.0f} 点 |",
        f"| 新批全部 | {latest['frames']:,} 帧，{latest['valid_depth_observations']:,} 次观测 |",
        f"| 旧四份工程 | {older['frames']:,} 帧，{older['valid_depth_observations']:,} 次观测 |",
        f"| 全部已解包输入 | {summary['all_input_cohorts']['frames']:,} 帧，{total:,} 次观测 |",
        f"| 新批26份主融合表面合计 | {summary['latest_main_surfaces']['total_points']:,} 点 |",
        f"| 单份主融合表面范围 | {min(r['points'] for r in main_surfaces):,}–{max(r['points'] for r in main_surfaces):,} 点 |",'',
        '## 杯子实际工作负载','','| 扫描 | 帧 | 重复深度观测 |','| --- | ---: | ---: |']
    for s in latest['scans']:
        if s['scan_id'] in ['scan_20261018131019','scan_20261018131127','scan_20261018131222','scan_20261018131359']:
            lines.append(f"| {s['scan_id'].removeprefix('scan_')} | {s['frame_count']} | {s['valid_depth_observations']:,} |")
    if joint_report:
        j=summary['two_scan_joint_example'];lines+=['',f"前两份联合输入 {j['raw_observations']:,} 次深度观测，实际联合提取 {j['joint_surface_points']:,} 个表面点。"]
    lines+=['','## 把原始观测一次性展开的成本','','以下均是数组内容估算，不包含任何算法临时副本、KD-tree、网格或 TSDF。RGB 与法向按每点三分量计算；无颜色数据不必实际分配 RGB。','','| 数组布局 | 新批 2.67亿观测 | 新旧全部观测 |','| --- | ---: | ---: |']
    for key,label in [('xyz_float32_bytes','XYZ float32'),('xyz_float64_bytes','XYZ float64'),('xyz_and_rgb_float64_bytes','XYZ＋RGB float64'),('xyz_rgb_normals_float64_bytes','XYZ＋RGB＋法向 float64')]:
        lines.append(f"| {label} | {gib(latest['flattened_memory_estimates'][key]):.2f} GiB | {gib(summary['all_input_cohorts']['flattened_memory_estimates'][key]):.2f} GiB |")
    lines+=['',f"主机物理内存约 {gib(memory.total):.2f} GiB，本次采样可用约 {gib(memory.available):.2f} GiB；可用值随其他程序变化。新批全部密集深度图解压成 float32 约 {gib(latest['dense_depth_float32_materialized_bytes']):.2f} GiB，其中包含大量无效零值。",'',
        f"新批原始工程文件去重路径统计约 {gib(latest['original_unique_file_bytes']):.2f} GiB；解包 frame.npz 总计约 {gib(latest['decoded_frame_npz_bytes']):.2f} GiB。压缩文件体积不能当作处理时内存。",'',
        '## 对软件的直接含义','','- 原深度按帧读取和积分，保持单帧工作集；不把几亿次观测全部展开并同时常驻。',
        '- 融合后的单物体表面当前主要为十万点量级，可做完整精度局部处理；多个候选同时显示时仍需预算。',
        '- 配准、概览与精确选点使用不同数据层，但显示点必须保留原模型顶点编号，不能丢失可追溯性。',
        '- 对十万、百万及千万点的加载、空间降采样和索引做实测，再确定预览预算；尚未据此宣称浏览器帧率。',
        '- 所有工程不是同一个物体，不能因为总量可以统计就把它们直接一起融合。','',
        '[全部逐工程统计与字节数](summary.json)']
    (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    picture=Image.new('RGB',(1400,650),(24,33,47));draw=ImageDraw.Draw(picture)
    draw.text((20,15),'原始观测与融合表面是两个数量级',font=font(27),fill='#edf3fa')
    selected=[r for r in latest['scans'] if r['scan_id'] in ['scan_20261018131019','scan_20261018131127','scan_20261018131222','scan_20261018131359']]
    models={r['scan_id']:r for r in main_surfaces}
    for i,s in enumerate(selected):
        y=95+i*105;draw.text((20,y),s['scan_id'].removeprefix('scan_'),font=font(20),fill='#edf3fa')
        for j,(n,color,label) in enumerate([(s['valid_depth_observations'],'#80b6ec','逐帧重复观测'),(models[s['scan_id']]['points'],'#7bc6a1','主基线表面')]):
            width=600*np.log10(max(n,1))/8;draw.rectangle((270,y+j*31,270+width,y+j*31+19),fill=color)
            draw.text((920,y+j*31-2),f'{label} {n:,}',font=font(17),fill='#adbed1')
    draw.text((20,560),'条形长度为 log10 数量；表面数来自既有主基线，部分扫描仍失败，不能按点数评价质量。',font=font(18),fill='#adbed1')
    draw.text((20,602),f'主机物理内存 {gib(memory.total):.2f} GiB；全部新批 XYZ+RGB+法向 float64 数组约 {gib(latest["flattened_memory_estimates"]["xyz_rgb_normals_float64_bytes"]):.2f} GiB。',font=font(18),fill='#adbed1');picture.save(out/'scale.png')
    print(json.dumps(dict(new_frames=latest['frames'],new_observations=latest['valid_depth_observations'],all_frames=summary['all_input_cohorts']['frames'],all_observations=total,
        main_surface_total=summary['latest_main_surfaces']['total_points'],main_surface_range=[min(r['points'] for r in main_surfaces),max(r['points'] for r in main_surfaces)],
        largest_derived_surface=max(derived,key=lambda r:r['points']),host=summary['host_snapshot'])),flush=True)


if __name__=='__main__':main()

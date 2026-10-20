"""Assemble measured scale, paired preview coverage and exact local-query evidence."""

import argparse
import html
import json
from pathlib import Path

import numpy as np
import open3d as o3d
from PIL import Image,ImageDraw
from scipy.spatial import cKDTree

from build_attribute_study_report import font,render
from reconstruction_probe.lod_cache import load_lod_cache
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.ply_layout import map_ply_vertices


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def gib(value):return value/2**30
def mib(value):return value/2**20


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);args=parser.parse_args();root=args.root.resolve()
    inventory=read(root/'summary.json');operations=read(root/'operations-verified/summary.json');lods={p.parent.name:read(p) for p in sorted((root/'lod').glob('*/summary.json'))}
    indices={p.parent.name:read(p) for p in sorted((root/'spatial-index').glob('*/summary.json'))};latest=inventory['latest'];older=inventory['older'];all_inputs=inventory['all_input_cohorts'];host=inventory['host_snapshot']
    paired=[];picture=Image.new('RGB',(1400,3*540+70),(24,33,47));draw=ImageDraw.Draw(picture)
    labels=[('joint-cup-40k','杯子联合表面'),('fine-figure-40k','高分辨率人偶'),('legacy-preview-40k','旧样例原预览')]
    for row,(key,label) in enumerate(labels):
        cache=root/'lod'/key;meta=lods[key];source=Path(meta['source_path']);preview=load_lod_cache(cache,source,verify_original_rows=True)
        records,layout=map_ply_vertices(source);sample_ids=np.linspace(0,len(records)-1,min(100000,len(records)),dtype=np.uint64)
        xyz=np.column_stack([records[name][sample_ids] for name in ['x','y','z']]).astype(float);uniform_ids=np.linspace(0,len(records)-1,len(preview['ids']),dtype=np.int64)
        uniform=np.column_stack([records[name][uniform_ids] for name in ['x','y','z']]).astype(np.float32);del records
        uniform_distance,_=cKDTree(uniform).query(xyz);spatial_distance,_=cKDTree(preview['xyz']).query(xyz)
        np.savez_compressed(root/(key+'-paired-sampling.npz'),original_vertex_ids=sample_ids,source_xyz_mm=xyz.astype(np.float32),
            row_uniform_representation_distance_mm=uniform_distance.astype(np.float32),spatial_representation_distance_mm=spatial_distance.astype(np.float32))
        paired.append(dict(label=key,source_path=str(source),source_sha256=meta['source_sha256'],sample_count=len(sample_ids),
            sample_ids_sha256=__import__('hashlib').sha256(sample_ids.astype('<u8').tobytes()).hexdigest(),
            same_original_queries_for_both_previews=True,row_uniform_points=len(uniform),spatial_points=len(preview['ids']),
            source_rows_verified=True,payload_sha256=file_sha256(root/(key+'-paired-sampling.npz'))))
        draw.text((15,row*540+10),f"{label} · {layout.vertex_count:,} → {len(preview['ids']):,} 个显示点",font=font(22),fill='#edf3fa')
        bounds=(np.array(meta['bounds_min_mm']),np.array(meta['bounds_max_mm']))
        for col,(name,distance) in enumerate([('按行号均匀抽样',uniform_distance),('空间体素代表点',spatial_distance)]):
            color=np.tile(np.array([88,159,223])/255,(len(distance),1));color[distance>.5]=np.array([85,200,126])/255;color[distance>1]=np.array([239,182,90])/255;color[distance>2]=np.array([192,106,220])/255
            pc=o3d.geometry.PointCloud();pc.points=o3d.utility.Vector3dVector(xyz);pc.colors=o3d.utility.Vector3dVector(color)
            picture.paste(render(pc,(680,400),yaw=1.2,pitch=.15,gain=1.,bounds=bounds),(col*700+10,row*540+55))
            full=meta['same_count_row_uniform_control']['coverage'] if col==0 else meta['spatial_coverage']
            draw.text((col*700+18,row*540+470),f"{name}：全点最大 {full['full_maximum_representation_distance_mm']:.2f} mm",font=font(20),fill='#edf3fa')
            draw.text((col*700+18,row*540+503),f"固定抽样 p99 {np.percentile(distance,99):.2f} mm；源点到预览的表示距离",font=font(16),fill='#adbed1')
    draw.text((15,3*540+12),'蓝≤0.5 mm · 绿≤1 mm · 橙≤2 mm · 紫>2 mm；同一原点查询对照。不是扫描精度。',font=font(19),fill='#adbed1');picture.save(root/'preview-coverage.png')
    (root/'sampling-comparisons.json').write_text(json.dumps(dict(pairs=paired),ensure_ascii=False,indent=2),encoding='utf-8')
    memory_rows=[('主机物理内存',host['physical_ram_bytes'],'#7bc6a1'),('新批密集深度 float32 全部展开',latest['dense_depth_float32_materialized_bytes'],'#80b6ec'),
        ('新批全部 XYZ float64',latest['flattened_memory_estimates']['xyz_float64_bytes'],'#80b6ec'),('新批 XYZ+RGB+法向 float64',latest['flattened_memory_estimates']['xyz_rgb_normals_float64_bytes'],'#edb877'),
        ('新旧全部 XYZ+RGB+法向 float64',all_inputs['flattened_memory_estimates']['xyz_rgb_normals_float64_bytes'],'#d29ee5')]
    memory_picture=Image.new('RGB',(1400,520),(24,33,47));d=ImageDraw.Draw(memory_picture);d.text((20,15),'一次性展开全部原始观测的数组成本',font=font(26),fill='#edf3fa')
    largest=max(v for _,v,_ in memory_rows)
    for i,(name,value,color) in enumerate(memory_rows):
        y=86+i*72;d.text((20,y),name,font=font(19),fill='#edf3fa');width=620*value/largest;d.rectangle((500,y,500+width,y+27),fill=color);d.text((1150,y),f'{gib(value):.2f} GiB',font=font(21),fill='#edf3fa')
    d.text((20,475),'数组估算未含临时副本、KD-tree、TSDF、网格、库开销或系统缓存；原始观测大量重复。',font=font(18),fill='#adbed1');memory_picture.save(root/'memory-budget.png')
    lines=['# 当前点云规模、内存与交互分层实测','','目前的主要结论：原始重复观测达到亿级，融合表面主要在十万至百万级。这两个数据层应使用不同处理策略。已有逐帧融合保持流式；新增空间预览与磁盘局部索引可把概览和精确选点分开。','','| 数据层 | 实际数量 |','| --- | ---: |',
        f"| 新批单帧中位数 / 最大 | {latest['frame_point_quantiles']['median']:,.0f} / {latest['frame_point_quantiles']['max']:,.0f} 点 |",
        f"| 新批逐帧有效观测 | {latest['frames']:,} 帧，{latest['valid_depth_observations']:,} 次 |",
        f"| 新旧全部逐帧有效观测 | {all_inputs['frames']:,} 帧，{all_inputs['valid_depth_observations']:,} 次 |",
        f"| 新批26份主融合表面合计 | {inventory['latest_main_surfaces']['total_points']:,} 点 |",
        '| 当前最高分辨率自研候选 | 793,214 点 |','| 旧样例最大原始预览 | 1,519,059 点 |','| 两杯子工程真实联合输入 → 输出 | 7,208,475 次观测 → 190,388 表面点 |','',
        '原始观测会重复测量同一位置。26份工程也不是同一个物体，合计数量不表示应该把它们一起融合。其他实验候选是同源重复结果，不能算成新采集数据。','','## 内存与磁盘','','![数组成本](memory-budget.png)','',
        f"主机物理内存约 {gib(host['physical_ram_bytes']):.2f} GiB。新批 frame.npz 压缩后约 {mib(latest['decoded_frame_npz_bytes']):.1f} MiB，但全部密集深度展开为 float32 约 {gib(latest['dense_depth_float32_materialized_bytes']):.2f} GiB。压缩大小不能当运行内存。",'',
        '新批全部点若同时放入 XYZ、RGB、法向三个 float64 数组，约17.89 GiB；全部新旧观测约24.83 GiB，还没有算索引和临时拷贝。因此原始层应逐帧读取，不能用一个超大点云作为默认工程状态。','','## 完整模型 CPU 操作','','每例由独立进程运行；表中建树含首次 SciPy 导入。缓存、后台程序与线程配置会影响单次结果。法向步骤另设20万点上限，不冒充全模型法向耗时。','','| 数据 | 点数 | 完整读取 | 0.5mm体素降采样 | 完整点KD-tree | 进程峰值工作集 |','| --- | ---: | ---: | ---: | ---: | ---: |']
    for case in operations['cases']:
        stages={s['name']:s['seconds'] for s in case['stages']};peak=case['memory']['process_lifetime_peak_working_set_bytes'] or case['memory']['sampled_peak_rss_bytes']
        lines.append(f"| {case['label']} | {case['input_points']:,} | {stages['open3d_full_cloud_read']:.3f}s | {stages['voxel_down_sample_0_5mm']:.3f}s | {stages['ckdtree_build_full_cloud']:.3f}s | {mib(peak):.1f} MiB |")
    lines+=['','千万点样本由实测人偶点云平移复制构造，明确是合成压力控制，不是真实新增扫描，也不代表所有形状的算法难度。初次千万点操作与LOD构建有并行负载，正式表格采用随后串行复核结果，初次记录保留。中文原文件路径通过既有只读临时副本兼容Open3D。','','## 同数量预览：按行抽样与空间代表点','','每个体素选择一个实际原顶点，保留原编号，不用平均出来的虚构点替代对应点。下表使用相同显示点数比较；最大距离检查完整源点集，分位数最多检查10万固定原行。','','| 数据 | 实际显示点 | 空间预览构建及覆盖核对 | 按行抽样全点最大距离 | 空间预览全点最大距离 |','| --- | ---: | ---: | ---: | ---: |']
    for key,meta in lods.items():
        lines.append(f"| {key} | {meta['preview_points']:,} | {meta['total_elapsed_seconds']:.2f}s | {meta['same_count_row_uniform_control']['coverage']['full_maximum_representation_distance_mm']:.2f} mm | {meta['spatial_coverage']['full_maximum_representation_distance_mm']:.2f} mm |")
    lines+=['','![相同原点的预览表示距离](preview-coverage.png)','','这些是源模型到预览的表示距离，不是扫描精度。空间预览更均匀不证明原模型正确，也不能替代细节区域的完整点读取。浮点预览与最终原点求解分开，缓存绑定源文件SHA256。','','## 不加载完整Open3D点云，也能精确查局部','','索引按空间块保存原顶点编号，每个有效原点保留一次。查询先找相交块，再对候选原点精确检查球形范围。区域过大时明确拒绝，不悄悄抽样后称为完整选择。','','| 数据 | 额外索引 | 建索引 | 开启并核对哈希 | 局部查询中位数 | 穷举中位数 | 点编号完全一致 |','| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for label,record in indices.items():
        build=record['build'];q=record['query_benchmark'];lines.append(f"| {label} | {mib(build['index_bytes']):.2f} MiB | {build['elapsed_seconds']:.2f}s | {q['open_and_hash_validation_seconds']:.3f}s | {q['median_query_seconds']*1000:.2f} ms | {q['median_brute_force_seconds']*1000:.2f} ms | {q['all_exact_original_ids_match']}，12次 |")
    lines+=['','查询耗时不含一次性打开索引和验证哈希。打开后的索引会检查源文件大小和修改时间；原文件或索引内容变化时拒绝复用。这些是后端CPU时延，不是浏览器画面帧率。','','## 已接入的工作流与交互原型','','- [真实三步运行](workflow-spatial-run/index.html)：152万点原预览 → 空间缓存 → 磁盘索引 → 三处局部完整点导出，日志、哈希和状态均保留。',
        '- [同一人偶的缓存对应点工作台](cached-workbench/workbench.html)：官方533,469点与自研793,214点各显示约3.9万原顶点。完整模型保留，缓存点的原编号可交给既有后端核对。',
        '- 旧选点可以通过 `--include-session` 合入新预览；不会因抽样变化就把原编号替换成预览行号。超出显示预算时明确提示。',
        '- 合成端到端控制已验证“缓存 → 生成HTML的模拟交互 → 导出原编号 → 后端原坐标求解”，并覆盖中文源路径。它不是人工实际选点，也没有验证真实GPU。','',
        '## 下一步使用方式','','完整使用方法见[点云规模与局部交互说明](../../docs/pointcloud-scale-and-local-interaction.md)。当前建议把概览控制在数万显示点；精确选点时读取局部完整顶点；融合继续流式处理原深度。统一编辑器和实时视图切换尚未实现，不能把这些后端原型称为完整软件。','',
        '[原始数量清单](summary.json) · [操作实测](operations-verified/summary.json) · [同点配对检查](sampling-comparisons.json)']
    (root/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    def table(headers,rows):return '<table><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>点云规模与局部交互研究</title><style>body{margin:0;background:#0c1420;color:#e2ecf8;font:16px/1.8 system-ui,'Microsoft YaHei',sans-serif}main{max-width:1400px;margin:auto;padding:30px}h1{font-size:30px}h2{margin-top:35px;font-size:23px}a{color:#9bcaff}nav{display:flex;gap:18px;flex-wrap:wrap}img{width:100%;border-radius:8px}table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:12px;border-bottom:1px solid #35475d}.note{padding:18px;background:#203244;border-left:3px solid #8ec6ee;border-radius:5px}.muted{color:#adbed1}.scroll{overflow:auto}</style><main><p class="muted">2026-10-19 · 实测数据与可重复原型</p><h1>亿级原始观测，分层处理与局部精确交互</h1>'''
    page+='<p>新旧输入共11,932帧、370,243,304次有效深度观测，含大量重复。新批26份主融合合计2,047,250点；最高分辨率候选约79万点，旧预览最高约152万点。千万点数据仅为明确标记的合成压力控制。</p><nav><a href="README.md">完整研究与数值</a><a href="workflow-spatial-run/index.html">实际三步工作流</a><a href="cached-workbench/workbench.html">缓存对应点原型</a><a href="../../docs/pointcloud-scale-and-local-interaction.md">使用方法</a></nav><h2>内存边界</h2><img src="memory-budget.png" alt="原始数据不同数组表示的内存估算"><p>压缩包与运行内存分开计算。逐帧融合保持单帧工作集，概览保留数万原顶点，局部选择再回到完整模型。</p><h2>预览覆盖的同数量对照</h2>'
    page+=table(['模型','显示点','按行抽样最大表示距离','空间预览最大表示距离'],[(key,meta['preview_points'],f"{meta['same_count_row_uniform_control']['coverage']['full_maximum_representation_distance_mm']:.2f} mm",f"{meta['spatial_coverage']['full_maximum_representation_distance_mm']:.2f} mm") for key,meta in lods.items()])
    page+='<img src="preview-coverage.png" alt="相同原始点到两种预览的距离对照"><div class="note">表示距离描述预览对原模型的覆盖，不能解释为扫描精度。小距离也不能证明模型正确。原顶点编号、文件哈希、原模型和原深度均保留。</div><h2>局部完整点查询</h2>'
    page+=table(['数据','索引大小','建索引','查询中位数','逐点扫描中位数','结果原编号核对'],[(label,f"{mib(r['build']['index_bytes']):.2f} MiB",f"{r['build']['elapsed_seconds']:.2f} s",f"{r['query_benchmark']['median_query_seconds']*1000:.2f} ms",f"{r['query_benchmark']['median_brute_force_seconds']*1000:.2f} ms",'12次全部一致') for label,r in indices.items()])
    page+='<p>单次CPU后端实测；不含索引初次打开及哈希核对，不代表GPU帧率。统一编辑器和实时切换仍待实现，实际WebGL/GPU画面尚未验证。<a href="sampling-comparisons.json">配对点与来源记录</a>。</p></main></html>'
    (root/'index.html').write_text(page,encoding='utf-8')
    inputs=[root/'summary.json',root/'operations-verified/summary.json',*[root/'lod'/key/'summary.json' for key in lods],*[root/'spatial-index'/key/'summary.json' for key in indices],root/'workflow-spatial-run/state.json']
    (root/'report-provenance.json').write_text(json.dumps(dict(input_sha256={str(p):file_sha256(p) for p in inputs},paired_same_source_samples=paired,actual_gpu_verified=False),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(root/'index.html'),raw_observations=all_inputs['valid_depth_observations'],spatial_previews=len(lods),paired_queries=sum(r['sample_count'] for r in paired),local_query_cases=len(indices))),flush=True)


if __name__=='__main__':main()

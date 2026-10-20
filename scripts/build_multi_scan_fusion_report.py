"""Build a reviewable report for real two-project depth TSDF integration."""

import argparse
import json
from pathlib import Path

import numpy as np
import open3d as o3d
from PIL import Image, ImageDraw

from analyze_multi_scan_fusion import LABELS
from build_attribute_study_report import font, render


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--fusion', type=Path, required=True)
    args = parser.parse_args(); root = args.fusion.resolve(); summary = read(root / 'summary.json'); evidence = read(root / 'depth-evidence/summary.json')
    lines = ['# 两份工程的原始深度联合融合', '',
        '本次把 13:10:19 的 208 帧与 13:11:27 的 255 帧，共 463 帧原始深度直接积分到同一个稀疏 TSDF。输入是解包的深度、对齐 RGB、每工程内参和保存的优化位姿；没有把已融合点云当深度再融合。', '',
        '每个测量由 `(scan_id, frame_id)` 标识。工程间变换固定为此前配准候选，未根据本次结果再次拟合。三个实验统一使用 0.6 mm 体素、2.4 mm 截断、3 mm 深度边缘跳变过滤和提取权重阈值 3。', '',
        '单独与联合实验按每来源核对深度数组、物理 RGB 和最终相机位姿的有序 SHA256，全部一致。内部运算单位为米，PLY/网格输出为毫米。', '',
        '![同参数单独与联合结果](comparison.png)', '',
        '| 实验 | 原深度帧 | 表面点数 | 最大连通面 | 文件 |', '| --- | ---: | ---: | ---: | --- |']
    for row in summary['results']:
        label = row['label']; q = row['quality']
        lines.append(f"| {label} | {row['integrated_frames']} | {q['point_count']:,} | {q['largest_component_triangle_fraction']:.2%} | [PLY]({label}/tsdf_pointcloud_mm.ply) · [网格]({label}/tsdf_mesh_mm.ply) · [输入贡献]({label}/frame-contributions.csv) |")
    lines += ['', '静态观察可见，联合结果同时保留第一份较完整的杯身以及第二份补充的杯底外侧等表面。仍有孔洞、零散点与局部边缘不一致；当前没有补洞或凭空生成缺失面。点数和连通性不是准确度。', '',
        '[三维彩色对照](review.html) · [全部参数、变换、来源哈希](summary.json)', '',
        '## 表面来自哪份扫描', '',
        '每个模型各自抽样 40,000 点，再投影回两份工程的保存深度。绿表示两工程各至少两视图支持，蓝表示仅第一份，橙表示仅第二份，灰表示支持不足。任一工程有至少三次自由空间冲突时优先显示紫色，底层仍单独保留支持状态。容差为 2 mm。', '',
        '![逐工程支持和冲突](depth-evidence/comparison.png)', '',
        '| 模型 | 双方支持 | 仅第一份 | 仅第二份 | 支持不足 | 有重复冲突 |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for row in evidence['surface_results']:
        n = row['sample_count']; values = [row['category_counts'][name] / n for name in LABELS]
        lines.append(f"| {row['label']} | " + ' | '.join(f'{v:.2%}' for v in values) + f" | {row['repeated_conflict_samples']/n:.2%} |")
    lines += ['', '这些是各自模型表面的内部诊断。不同模型的点集不同，不能把上述比例作为逐点准确度排名；两份工程共同支持的点也可能与另一些帧冲突。', '',
        '| 原单独模型 | 原点距联合表面 >2 mm | 原点总数 | 原点→联合表面中位距离 |', '| --- | ---: | ---: | ---: |']
    for row in evidence['surface_retention_distances']:
        value = row['single_to_joint']; lines.append(f"| {row['single_label']} | {value['farther_than_2mm']:,} | {value['count']:,} | {value['median_mm']:.3f} mm |")
    joint_new = evidence['surface_retention_distances'][0]['joint_to_single']['farther_than_2mm']
    lines += ['', f'联合模型有 {joint_new:,} 个点距第一份单独表面超过 2 mm，说明表示范围增加；这些点是否属于正确新表面，还需结合来源支持和原帧审阅。', '',
        '[三维证据着色](depth-evidence/review.html) · [各工程支持与冲突计数](depth-evidence/summary.json)', '',
        '## 回查具体原帧', '']
    for name, label in [('source_only', '第二份补充的区域'), ('target_only', '第一份保留的区域'), ('repeated_conflict', '仍有冲突的区域'), ('unanimous_neighbor_conflict','有效邻域仍一致冲突的区域')]:
        trace = root / ('trace-' + name)
        if (trace / 'summary.json').exists():
            row = read(trace / 'summary.json'); counts = row['source_observation_counts']
            lines.append(f"- [{label}](trace-{name}/README.md)：抽样点 {row['sample_index']}。第一份支持/冲突/遮挡 {counts[0]['support']}/{counts[0]['free_space_conflict']}/{counts[0]['occluded']}；第二份 {counts[1]['support']}/{counts[1]['free_space_conflict']}/{counts[1]['occluded']}。")
    lines += ['', '代表点由已看过的分类区域中选择，并非盲测。回查保留具体工程、帧号、深度像素、测量深度、预测深度和对齐颜色。黑色表示该位置没有深度，不是完整原 JPEG。']
    if (root/'pixel-sensitivity/summary.json').exists():
        sensitivity=read(root/'pixel-sensitivity/summary.json')
        lines += ['', '## 单个像素会不会影响冲突判断', '',
            f"对原来的 {sensitivity['repeated_center_conflict_samples']:,} 个重复冲突点检查 3×3 邻域，要求至少 5 个有效像素全部仍显示冲突，并且至少重复于 3 个视图，剩下 {sensitivity['repeated_unanimous_neighbor_conflict_samples']:,} 个点满足条件。差异主要提示像素位置或边界敏感性，不能据此证明其余点正确。", '',
            '[邻域敏感性分析与三维着色](pixel-sensitivity/README.md)。原单像素结果和融合模型不变。']
    if (root/'local-plane-evidence/summary.json').exists():
        local=read(root/'local-plane-evidence/summary.json')
        lines += ['', '## 沿视线距离与垂直表面距离', '',
            f"对原冲突点周围的实测深度拟合局部平面，{local['repeated_additional_normal_discrepancy_points']:,} 个点还在至少三处合格平面上显示超过 2 mm 的正法向距离。斜面会放大轴向差，而点到平面的距离也不能限制切向滑动，两者都需保留。", '',
            '[局部表面距离、平面合格条件与分布](local-plane-evidence/README.md)。未成功拟合的平面另存，不当作误差消失。']
    lines += ['',
        '## 当前边界', '',
        '工程间变换没有通过此前完整重叠门槛，且两份绿色杯子的物理身份尚未独立确认。因此结果继续作为可审阅候选，没有替换主重建。原位姿、源工程和单独结果均保留。', '',
        '全部深度参与了重建或此前配准，支持计数不能当独立精度测量；来源缺少支持可能是遮挡或无深度。导出的 OBJ 为几何，不带烘焙纹理；PLY 保留顶点颜色。实际 GPU 三维画面仍待验证。', '',
        '## 复现', '', '项目根目录 PowerShell；计算输出须使用新的空目录。', '', '```powershell',
        r"$study = 'reports\range2-study-20261018'", r"$fusion = 'reports\multi-scan-reproduce'",
        r"& '.\.venv\Scripts\python.exe' scripts\experiment_multi_scan_tsdf.py `",
        r'  --study $study --registration "$study\experiments\cup-registration\summary.json" --out $fusion',
        r"& '.\.venv\Scripts\python.exe' scripts\analyze_multi_scan_fusion.py `", r'  --fusion $fusion --out "$fusion\depth-evidence"',
        r"& '.\.venv\Scripts\python.exe' scripts\trace_multi_scan_surface_point.py `", r'  --fusion $fusion --category source_only --out "$fusion\trace-source_only"',
        r"& '.\.venv\Scripts\python.exe' scripts\build_multi_scan_fusion_report.py --fusion $fusion", '```', '',
        '可把 `--category` 换成 `target_only` 或 `repeated_conflict`，也可通过 `--sample-index` 指定已有抽样点编号。']
    (root / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    # Refresh only presentation, without recomputing unchanged evidence arrays.
    rows = [(r['label'], o3d.io.read_point_cloud(str(root / 'depth-evidence' / (r['label'] + '-source-evidence-mm.ply')))) for r in evidence['surface_results']]
    bounds = (np.min([pc.get_min_bound() for _, pc in rows], axis=0), np.max([pc.get_max_bound() for _, pc in rows], axis=0))
    picture = Image.new('RGB', (1500, 560), (24, 33, 47)); draw = ImageDraw.Draw(picture)
    for i, ((label, cloud), row) in enumerate(zip(rows, evidence['surface_results'])):
        draw.text((i*500+12, 10), label, font=font(19), fill='#edf3fa')
        picture.paste(render(cloud, (490, 390), yaw=1.2, pitch=.15, bounds=bounds, gain=1.), (i*500+5, 45))
        draw.text((i*500+12, 450), f"双方支持 {row['category_counts'][LABELS[0]]/row['sample_count']:.1%}", font=font(18), fill='#edf3fa')
        draw.text((i*500+12, 480), f"重复冲突 {row['repeated_conflict_samples']/row['sample_count']:.1%}", font=font(18), fill='#adbed1')
    draw.text((12, 525), '绿双方 · 蓝第一份 · 橙第二份 · 灰不足 · 紫冲突；不同模型抽样，不能当逐点精度排名。', font=font(16), fill='#adbed1')
    picture.save(root / 'depth-evidence/comparison.png'); print(json.dumps(dict(report=str(root / 'README.md'))))


if __name__ == '__main__':
    main()

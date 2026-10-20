"""Document failed-scan diagnosis, including attempts that were not adopted."""

import argparse
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, lines):
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args(); root = args.study.resolve() / 'experiments'
    axis = root / 'fixed-axis-depth-prior'; sequence = root / 'depth-sequence-consistency'
    graph = root / 'cup-segment-pose-graph'; color = root / 'cup-segment-color-edges'
    axis_report = read(axis / 'summary.json'); sequence_report = read(sequence / 'summary.json')
    graph_report = read(graph / 'summary.json'); color_report = read(color / 'summary.json')
    lines = ['# 转台固定轴先验：未采用的实验', '',
        '用户说明这些数据主要通过转台扫描。实验用交替 16 条记录块划分训练与留出，仅用训练位姿拟合固定轴，然后比较原位姿、只修正平移、修正完整位姿。留出角度仍来自官方旋转，所以并非独立的视觉跟踪算法。', '',
        '每条留出记录最多取 64 个经实物颜色核对的绿色物体深度点。投影到其他留出深度，排除索引相邻 ±8 条记录。支持要求至少两视图；冲突要求至少三视图；容差 2 mm。支持与冲突可同时成立。', '',
        '| 工程 | 候选 | 样本 | 有支持 | 有重复冲突 |', '| --- | --- | ---: | ---: | ---: |']
    for project in axis_report['projects']:
        for row in project['results']:
            value = row['thresholds'][0]; n = project['source_samples']
            lines.append(f"| {project['scan_id'].removeprefix('scan_')} | {row['variant']} | {n:,} | {value['supported_in_at_least_two_views']/n:.2%} | {value['conflicts_in_at_least_three_views']/n:.2%} |")
    lines += ['', '失败工程 13:12:22 的完整固定轴候选增加了深度冲突。轨迹更接近理想圆周，不表示物体表面对得更准。本实验没有替换保存位姿或主重建。', '',
        '![同一深度样本对照](comparison.png)', '', '[三维证据](review.html) · [完整数据](summary.json)', '',
        '索引间隔不是时间。绿色取样可能漏掉印花、暗部等真实表面；遮挡与无深度不视为冲突。']
    save(axis / 'README.md', lines)
    lines = ['# 保存深度的序列一致性', '',
        '在记录索引间隔 1、8、32 分别双向投影。每帧最多 512 个绿色深度点；目标保留所有颜色的有效深度。边缘跳变阈值 3 mm，支持/自由空间冲突容差 2 mm。以下只统计至少 256 次有效投影的记录对。', '',
        '| 工程 | 索引间隔 | 可比较对数 | 冲突至少 20% 的对数 |', '| --- | ---: | ---: | ---: |']
    for project in sequence_report['projects']:
        for row in project['offset_summaries']:
            lines.append(f"| {project['scan_id'].removeprefix('scan_')} | {row['index_separation']} | {row['pairs_with_at_least_256_valid_projections']} | {row['pairs_above_20pct_conflict']} |")
    lines += ['', '13:12:22 相邻记录有 7 处明显分歧，间隔 8、32 时分别有 82、97 对达到同一冲突门槛。正常对照相同条件下没有达到门槛的记录对。局部相邻帧一致不能保证更长范围的姿态一致。', '',
        '![失败工程序列检查](scan_20261018131222/comparison.png)', '',
        '13:13:59 的两组 ID 交界处有约 117.65° 的相对旋转，但深度关系主要表现为遮挡而非自由空间冲突；因此单看冲突比例会漏掉值得审阅的分组。', '',
        '这些是审阅线索，不能确定哪一帧有错，更不能据此自动删帧。索引排列没有被证明为物理采集时间；大幅姿态变化也可能是合法移位。', '',
        '[13:12:22 待审阅相邻对](scan_20261018131222/neighbor-review-candidates.json) · [所有记录对 CSV](scan_20261018131222/pairs.csv) · [完整统计](summary.json)']
    save(sequence / 'README.md', lines)
    lines = ['# 失败工程的分段连接实验', '',
        '将 13:12:22 按已观察的 7 处相邻深度分歧分为 8 段。分段使用了全序列诊断，包含之后检查的记录，因此本实验不是盲测。只用原有训练记录生成各段点云；每段内部保存位姿不变，只尝试段间刚体校正。', '',
        '| 移动→固定段 | 旋转校正 | 物体探针位移 RMS | 当前门槛 |', '| --- | ---: | ---: | --- |']
    for edge in graph_report['edges']:
        lines.append(f"| {edge['source']} → {edge['target']} | {edge['change']['additional_rotation_deg']:.2f}° | {edge['change']['object_probe_rms_mm']:.2f} mm | {'通过' if edge['accepted'] else '未通过'} |")
    lines += ['', '仅 3/7 条相邻自动连接通过。程序在连接不足时停止：没有进行全局位姿图优化，也没有生成冒充修复成功的新融合模型。', '',
        '门槛为双向 3 mm 覆盖均至少 25%、至少一向 1.5 mm 覆盖达到 60%、重叠绝对法向点积中位数至少 0.9、旋转改动至多 15°、物体探针 RMS 至多 15 mm。它们是实验启发式条件，不是正确配准概率。', '',
        '[四处几何候选的对应点工作台](manual-workbenches/README.md) · [颜色约束后续实验](../cup-segment-color-edges/README.md) · [完整记录](summary.json)', '',
        '后续颜色实验发现 4→3 的原始关系已经通过同一门槛，而自动精修使它变差。因此该工作台仍保留历史失败候选用于对照，不表示原始关系也必须人工修正。剩余三处不能自动可靠连接。']
    save(graph / 'README.md', lines)
    lines = ['# 颜色能否救回失败连接', '',
        '对四条未通过几何精修门槛的连接，同时保留原始相对关系、原几何候选，以及各自启动的颜色 ICP。2 mm、1 mm 两级处理，几何权重分别尝试 0.968 与 0.5；几何门槛与原实验相同。此为看过前次结果后的探索。', '',
        '| 连接 | 通过的候选 | 处理结论 |', '| --- | --- | --- |']
    for edge in color_report['edge_hypotheses']:
        passed = [row['label'] for row in edge['trials'] if row['passes_same_geometric_gates']]
        lines.append(f"| {edge['source']} → {edge['target']} | {', '.join(passed) or '无'} | {'保留原始关系' if passed == ['saved_relative_identity'] else '待对应点审阅'} |")
    lines += ['', '没有颜色精修候选通过全部条件。4→3 唯一通过的是未调整的原始关系。不能默认后处理总会改善，也不能仅凭颜色误差降低选择候选：匹配点骤减也会使颜色误差看起来降低。', '',
        '颜色受曝光、反射和纹理模糊影响。试验保留匹配数量、几何覆盖、颜色误差及失败信息；没有放宽门槛强行补全连接。', '', '[所有候选与失败信息](summary.json) · [分段研究](../cup-segment-pose-graph/README.md)']
    save(color / 'README.md', lines)
    print(json.dumps(dict(reports=[str(p / 'README.md') for p in [axis, sequence, graph, color]])))


if __name__ == '__main__':
    main()

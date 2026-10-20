"""Keep a compact, relocatable research snapshot without scan payloads."""
import argparse
import json
from pathlib import Path
import shutil

from reconstruction_probe.offline import file_sha256


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty snapshot directory')
    if root not in out.parents:parser.error('Keep the snapshot inside this workspace')
    out.mkdir(parents=True,exist_ok=True)
    scale=read(root/'reports/pointcloud-scale-20261019/summary.json');web=read(root/'reports/web-studio/validation.json')
    operations=read(root/'reports/pointcloud-scale-20261019/operations-verified/summary.json')
    summary=dict(snapshot_date='2026-10-20',raw_observations=scale['all_input_cohorts'],
        latest_frames=scale['latest']['frames'],latest_observations=scale['latest']['valid_depth_observations'],
        earlier_frames=scale['older']['frames'],earlier_observations=scale['older']['valid_depth_observations'],
        latest_single_frame_quantiles=scale['latest']['frame_point_quantiles'],
        main_fused_surfaces=dict(models=scale['latest_main_surfaces']['models'],total_points=scale['latest_main_surfaces']['total_points'],point_quantiles=scale['latest_main_surfaces']['point_quantiles']),
        memory=dict(physical_ram_bytes=scale['host_snapshot']['physical_ram_bytes'],latest_dense_depth_float32_bytes=scale['latest']['dense_depth_float32_materialized_bytes'],latest_array_estimates=scale['latest']['flattened_memory_estimates']),
        verification=web,limitations=['Raw observations repeat the same physical surfaces and cannot be counted as unique geometry.',
            'The figures and summaries are research evidence; original scans, decoded frames and full models are not included.',
            'Actual Chrome/GPU rendering remains unverified; CPU pixel and HTTP checks are explicitly separate.',
            'SDK/realtime and the generic correspondence-to-original-fragment-fusion bridge remain deferred or incomplete.'])
    (out/'research-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    compact=[]
    for case in operations['cases']:
        compact.append({key:case[key] for key in ['label','input_points','stages','memory']})
    (out/'cpu-operation-measurements.json').write_text(json.dumps(dict(cases=compact,method='Independent CPU workers; KD-tree stage includes first SciPy import; 10M input is synthetic.'),ensure_ascii=False,indent=2),encoding='utf-8')
    images=[
        ('memory-budget.png','reports/pointcloud-scale-20261019/memory-budget.png'),
        ('preview-coverage.png','reports/pointcloud-scale-20261019/preview-coverage.png'),
        ('official-and-own-color.png','reports/range2-study-20261018/color-comparison.png'),
        ('all-main-reconstructions.png','reports/range2-study-20261018/reconstruction-overview.png'),
        ('direct-fragment-fusion.png','reports/range2-study-20261018/experiments/cup-direct-split/full-reconstruction/comparison.png'),
        ('two-scan-depth-fusion.png','reports/range2-study-20261018/experiments/cup-multi-scan-tsdf/comparison.png'),
        ('workbench-cpu-raster.png','reports/web-studio/compatibility/workbench-canvas.png')]
    provenance=[]
    for name,relative in images:
        source=root/relative;destination=out/name;shutil.copyfile(source,destination)
        provenance.append(dict(snapshot_file=name,source_relative_path=relative,sha256=file_sha256(destination),bytes=destination.stat().st_size))
    (out/'figure-provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    text='''# 2026-10-20 研究成果快照

此目录随代码备份，保存已完成工作的关键数量、验证边界与真实结果图。完整扫描工程、逐帧数据、模型和运行环境继续保留在本机，不在此快照中。

新旧输入共 **11,932帧、370,243,304次有效深度观测**。新批26份主融合表面合计2,047,250点；精细人偶候选793,214点。观测包含大量重复，不能视为同样数量的独立表面点。

Web原型已接入33份工程、6个对应点工作台和22类实验。123项Python检查通过；已有真实HTTP处理与CPU像素检查。**实际Chrome画面与GPU仍待核验。**

| 已实现或研究内容 | 结果与边界 |
| --- | --- |
| 离线解析 | 深度、保存/优化位姿、颜色与标记；不能证明全部物理传感器帧都保存 |
| 独立与多扫描融合 | 同一工程片段358帧演示、两工程463帧联合深度融合；孔洞、重影与冲突继续保留 |
| 对应点与局部交互 | 原顶点编号、空间预览、磁盘索引、局部完整点；原坐标核对后另存对齐模型 |
| Web工作流 | 模型/原始帧/实验浏览、对应点提交、固定工具任务和日志；尚无模型Agent服务 |
| SDK与实时引导 | 暂时后置；补扫方向当前是离线建议 |

## 点云规模与预览

![内存成本](memory-budget.png)

![同数量预览覆盖对照](preview-coverage.png)

以上距离描述预览覆盖原模型的程度，不是物理扫描精度。

## 独立融合与官方同源结果

![颜色与融合对照](official-and-own-color.png)

![26份主融合总览](all-main-reconstructions.png)

官方输出也不是独立物理真值，当前尚未证明自研结果全面优于官方。

## 片段与多扫描融合候选

![原两片段全帧融合候选](direct-fragment-fusion.png)

![两工程原始深度联合融合](two-scan-depth-fusion.png)

## 对应点兼容绘制

![对应点CPU绘制像素](workbench-cpu-raster.png)

此图由生成页面的CPU绘制代码输出，明确不是Chrome截图。

详细数量见 [research-summary.json](research-summary.json)，CPU实测见 [cpu-operation-measurements.json](cpu-operation-measurements.json)，图像来源与哈希见 [figure-provenance.json](figure-provenance.json)。恢复方法见 [备份与恢复说明](../../../docs/backup-and-restore.md)。
'''
    (out/'README.md').write_text(text,encoding='utf-8')
    print(json.dumps(dict(snapshot=str(out),files=len(list(out.iterdir())),bytes=sum(p.stat().st_size for p in out.iterdir())),ensure_ascii=True))


if __name__=='__main__':main()

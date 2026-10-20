"""Summarize the direct fragment, reserved-frame and color experiments."""

import argparse
import json
import os
from pathlib import Path

import numpy as np


def read(path):return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--root",type=Path,required=True)
    args=parser.parse_args();root=args.root.resolve()
    split=read(root/"split.json");geometric=read(root/"registration/summary.json");evaluation=read(root/"evaluation/summary.json")
    color=read(root/"color-registration/summary.json");color_eval=read(root/"color-evaluation/summary.json");fusion=read(root/"full-reconstruction/summary.json")
    labels={"saved_relative_identity":"原保存片段关系","direct_best_training":"训练几何最佳","direct_alternative_1":"几何备选 1","direct_alternative_2":"几何备选 2","colored_from_best":"最佳初值＋颜色精修","colored_from_alternative_1":"备选 1＋颜色精修"}
    fit_counts=[len(row["training_ids"]) for row in split["groups"]];holdout_counts=[len(row["heldout_ids"]) for row in split["groups"]]
    best=np.array(geometric["candidates"][1]["transform"]);angle=float(np.rad2deg(np.arccos(np.clip((np.trace(best[:3,:3])-1)/2,-1,1))))
    lines=["# 同一扫描片段直接配准：不用外部参考模型","",
        "此前用另一份扫描作参考可以改善局部指标，但存在参考依赖和阈值敏感。这次直接在 13:13:59 的两个片段之间配准，没有读取其他扫描的几何来拟合变换。", "",
        f"按每组完整帧 ID 的索引顺序，以 {split['block_size']} 条记录分块：偶数块训练、奇数块留出。两组训练 {fit_counts[0]}＋{fit_counts[1]}＝{sum(fit_counts)} 帧，留出 {holdout_counts[0]}＋{holdout_counts[1]}＝{sum(holdout_counts)} 帧，交集为零。索引不代表真实时间；此前 ROI 使用过全部源帧，因此这不是完全盲测。", "",
        "训练阶段每组单独作 0.6 mm Tensor TSDF，截断 2.4 mm、提取权重 3；然后用 PCA/FPFH 初值和稳健多级 ICP 直接把组 1 对到组 0。29 个粗候选按训练几何排序，并保留在实际物体区域内移动明显不同的 6 个位置作精修，避免被重复结果挤占。", "",
        f"训练最佳估计旋转约 {angle:.2f}°，与此前需要检查翻面的方向一致；它是估计的刚体变换，不是已经解码出的物理操作记录。原先严格完整重叠门槛仍未通过，不能称为无条件成功。", "",
        "## 留出帧检查", "",
        f"仅从 {sum(holdout_counts)} 帧留出记录抽取 {evaluation['source_sampled_points']:,} 个相同原始点。每个点由另一组的留出深度检查。候选先由训练几何固定，留出分数没有用于重新选择训练胜者。", "",
        "![相同留出像素的证据着色](evaluation/comparison.png)", "",
        "| 候选 | 2 mm 支持 | 2 mm 冲突 | 4 mm 支持 | 4 mm 冲突 |", "| --- | --- | --- | --- | --- |"]
    for row in evaluation["results"]:
        n=row["sampled_points"];values=[]
        for item in row["thresholds"]:
            values += [f"{item['supported_in_at_least_two_views']/n:.2%}",f"{item['conflicts_in_at_least_three_views']/n:.2%}"]
        lines.append("| "+" | ".join([labels[row["label"]],*values])+" |")
    lines += ["", "训练最佳在两档阈值下都显著减少重复冲突，支持也增加；备选 1 获得更多支持，但留下更多冲突。仍有近半点未达到支持门槛，不能把低冲突解释为完整正确。共同可观测点的统计也单独保留。", "",
        "同组内部对照排除了源帧与前后 8 条索引记录。2 mm 下组 0 支持约 92.3%、冲突约 0.32%；组 1 支持约 55.7%、冲突约 0.56%。不同覆盖会改变支持比例，不能直接由此判断设备精度。", "",
        "[留出三维审阅](evaluation/review.html) · [全部分组计数和限制](evaluation/summary.json) · [训练配准候选](registration/review.html)", "",
        "## 颜色精修探索", "",
        "颜色精修使用相同训练表面，将坐标转为米后执行三尺度 Colored ICP，固定几何权重 0.968，再把位姿平移转回毫米。方法依据 [Open3D 官方文档](https://www.open3d.org/docs/latest/tutorial/pipelines/colored_pointcloud_registration.html)。颜色可补充切向约束；本研究不预设光照、曝光变化下颜色一定可靠。", "",
        "这项尝试是在查看几何留出结果后追加的。虽然拟合仍只使用训练帧，后续结果必须作为探索性分析，不能称为未见测试。", "",
        "| 初值/精修 | 训练颜色 MAE 中位数 /255 | 留出 2 mm 支持 | 留出 2 mm 冲突 |", "| --- | --- | --- | --- |"]
    evaluated={row["label"]:row for row in color_eval["results"]}
    for row in color["candidates"]:
        if row["label"] not in ["direct_best_training","direct_alternative_1","colored_from_best","colored_from_alternative_1"]:continue
        item=evaluated[row["label"]];n=item["sampled_points"];values=item["thresholds"][0]
        lines.append(f"| {labels[row['label']]} | {row['training_color_metrics']['median_rgb_mae_255']:.2f} | {values['supported_in_at_least_two_views']/n:.2%} | {values['conflicts_in_at_least_three_views']/n:.2%} |")
    lines += ["", "两个初值在颜色精修后收敛到几乎相同的位置；它降低了备选 1 的颜色差异，却没有比原几何最佳取得更高的 2 mm 留出支持。不能把颜色优化或收敛一致本身当成更准确。", "",
        "[颜色尝试的留出检查](color-evaluation/summary.json) · [方法与拟合输入](color-registration/summary.json)", "",
        "## 用冻结候选重新融合全部 358 帧", "",
        "这是最终展示候选，包含之前的留出帧，因此不能拿该模型再当作留出测试。四边原始 ROI 深度数组 SHA256 完全相同：", "", "```text",fusion["results"][0]["selected_depth_array_sha256"],"```", "",
        "都是同样 358 帧、7,910,368 个读入有效深度，原 ROI 排除 442,401 个像素，固定 0.6 mm、2.4 mm 截断及权重 3。只改变组间变换，原位姿文件不覆盖。", "",
        "![全帧重新融合的实际颜色](full-reconstruction/comparison.png)", "",
        "| 候选 | 表面点数 | 主连通面 |", "| --- | --- | --- |"]
    for row in fusion["results"]:lines.append(f"| {labels[row['label']]} | {row['quality']['point_count']:,} | {row['quality']['largest_component_triangle_fraction']:.2%} |")
    lines += ["", "静态图中原保存关系出现的重复杯柄轮廓，在直接对齐候选中减少；但孔洞、碎片和边缘残差仍存在。正确地把互相矛盾的表面分开，可能降低最大连通面比例，因此该比例不能单独作为修复排名。", "",
        "[全帧三维模型对照](full-reconstruction/review.html) · [完整 PLY 路径、参数和同像素核对](full-reconstruction/summary.json)", "",
        "本实验没有替换主基线。下一步的交互入口是：保留多个候选，让用户以杯柄连接处、杯口/杯底等有辨识力的区域修正对应关系，再按相同输入重新融合。浏览器页面已做数据/脚本检查，真实 GPU 画面仍待验证。"]
    workspace=Path(__file__).resolve().parents[1]
    manual_doc=Path(os.path.relpath(workspace/'docs/landmark-workbench.md',root)).as_posix()
    guidance_doc=Path(os.path.relpath(workspace/'docs/offline-coverage-guidance.md',root)).as_posix()
    if (root/'landmark-workbench.html').exists():
        lines += ['',f'[对应点配准工作台](landmark-workbench.html) · [使用方法与接回融合]({manual_doc})。']
    if (root/'view-coverage/summary.json').exists():
        lines += ['',f'[保存视角覆盖](view-coverage/README.md) · [点到原帧回查](point-trace-weak-region/README.md) · [离线补扫方向](scan-view-proposals/README.md) · [链路说明]({guidance_doc})。']
    lines += ['', '## 复现本轮片段研究', '', '以下在项目根目录运行，依赖已有解包与原 ROI。使用新的输出目录；所有阶段保留独立结果。', '', '```powershell',
        "$study = 'reports\\range2-study-20261018'", "$direct = 'reports\\direct-fragment-reproduce'",
        "& '.\\.venv\\Scripts\\python.exe' scripts\\prepare_direct_group_study.py --study $study --out $direct",
        "& '.\\.venv\\Scripts\\python.exe' scripts\\fit_direct_group_registration.py --prepared $direct --out \"$direct\\registration\"",
        "& '.\\.venv\\Scripts\\python.exe' scripts\\evaluate_direct_group_holdout.py --prepared $direct --registration \"$direct\\registration\" --out \"$direct\\evaluation\"",
        "& '.\\.venv\\Scripts\\python.exe' scripts\\fit_direct_group_color.py --prepared $direct --geometric \"$direct\\registration\" --out \"$direct\\color-registration\"",
        "& '.\\.venv\\Scripts\\python.exe' scripts\\evaluate_direct_group_holdout.py --prepared $direct --registration \"$direct\\color-registration\" --out \"$direct\\color-evaluation\"",
        "& '.\\.venv\\Scripts\\python.exe' scripts\\reconstruct_direct_group_candidates.py --prepared $direct --registration \"$direct\\color-registration\" --labels saved_relative_identity direct_best_training direct_alternative_1 colored_from_best --out \"$direct\\full-reconstruction\"",
        "& '.\\.venv\\Scripts\\python.exe' scripts\\build_landmark_workbench.py --prepared $direct --registration \"$direct\\color-registration\" --out \"$direct\\landmark-workbench.html\"",
        "& '.\\.venv\\Scripts\\python.exe' scripts\\analyze_surface_view_coverage.py --prepared $direct --fusion \"$direct\\full-reconstruction\" --out \"$direct\\view-coverage\"",
        "& '.\\.venv\\Scripts\\python.exe' scripts\\propose_offline_scan_views.py --coverage \"$direct\\view-coverage\" --out \"$direct\\scan-view-proposals\"",
        "& '.\\.venv\\Scripts\\python.exe' scripts\\trace_surface_point.py --coverage \"$direct\\view-coverage\" --proposal-plan \"$direct\\scan-view-proposals\\summary.json\" --proposal-region 1 --out \"$direct\\point-trace-weak-region\"",
        "& '.\\.venv\\Scripts\\python.exe' scripts\\build_direct_group_study_report.py --root $direct", '```']
    (root/"README.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(root/"README.md")


if __name__=="__main__":main()

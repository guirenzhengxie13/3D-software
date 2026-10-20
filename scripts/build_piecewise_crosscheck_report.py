"""Render and explain frozen paired-point evidence without refitting anything."""

import argparse
import json
from pathlib import Path

import numpy as np
import open3d as o3d
from PIL import Image, ImageDraw

from analyze_piecewise_holdout import read, classes
from build_attribute_study_report import render, font


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crosscheck",type=Path,required=True)
    parser.add_argument("--controls",type=Path,required=True)
    args=parser.parse_args();root=args.crosscheck.resolve();report=read(root/"summary.json");controls=read(args.controls/"summary.json")
    diagnostics=[];clouds=[]
    for row in report["results"]:
        key=row["target_id"]
        with np.load(root/(key+"-paired-evidence.npz"),allow_pickle=False) as z:
            common=z["common_observed"]
            before=classes(z["whole_scan_control_support"][0],z["whole_scan_control_conflict"][0])
            after=classes(z["piecewise_candidate_support"][0],z["piecewise_candidate_conflict"][0])
            changed=(before==2)&(after==3)&common
            diagnostics.append(dict(target_id=key,
                common_observed_conflict_only_to_inconclusive_at_2mm=int(changed.sum()),
                those_with_three_or_more_candidate_occluded_views=int((changed&(z["piecewise_candidate_occluded"][0]>=3)).sum()),
                thresholds=[dict(tolerance_mm=float(t),arms={arm:dict(occluded_in_three_or_more_views=int((z[arm+"_occluded"][j]>=3).sum()),
                    common_observed_occluded_in_three_or_more_views=int(((z[arm+"_occluded"][j]>=3)&common).sum()))
                    for arm in ["whole_scan_control","piecewise_candidate"]}) for j,t in enumerate(z["tolerances_mm"])]))
        for arm in ["whole_scan_control","piecewise_candidate"]:
            clouds.append(o3d.io.read_point_cloud(str(root/(key+"-"+arm+"-evidence-mm.ply"))))
    bounds=(np.min([c.get_min_bound() for c in clouds],axis=0),np.max([c.get_max_bound() for c in clouds],axis=0))
    picture=Image.new("RGB",(1200,1020),(24,33,47));draw=ImageDraw.Draw(picture)
    for row_index,row in enumerate(report["results"]):
        y=row_index*480
        title="拟合参考 13:10:19" if row_index==0 else "额外扫描 13:11:27（未参与分组变换拟合）"
        draw.text((15,y+8),title,font=font(22),fill="#edf3fa")
        for arm_index,(arm,values) in enumerate(row["thresholds"][0]["arms"].items()):
            label="整扫描统一变换" if arm_index==0 else "两组分别变换候选"
            draw.text((arm_index*600+15,y+43),label,font=font(18),fill="#adbed1")
            picture.paste(render(clouds[row_index*2+arm_index],(590,350),yaw=1.2,pitch=.15,gain=1.,bounds=bounds),(arm_index*600+5,y+75))
            n=values["points"]
            draw.text((arm_index*600+15,y+432),f"支持 {values['supported_in_at_least_two_views']/n:.1%} · 冲突 {values['conflicts_in_at_least_three_views']/n:.1%}",font=font(18),fill="#edf3fa")
    draw.text((15,965),"同一批原始深度像素；2 mm 着色：绿=支持，紫=支持与冲突并存，红=冲突，灰=未定。",font=font(17),fill="#b1c5db")
    draw.text((15,990),"4 mm 统计见表格；阈值敏感、参考估计有误差，候选未纳入主结果。",font=font(16),fill="#b1c5db")
    picture.save(root/"evidence-comparison.png")
    (root/"diagnostics.json").write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2),encoding="utf-8")
    internal={row["source_id"]:row for row in controls["results"] if row["source_id"]==row["target_id"]}
    first_control,second_control=[internal[key] for key in ("scan_20261018131019","scan_20261018131127")]
    first_rate=first_control["thresholds"][0]["conflicts_in_at_least_three_views"]/first_control["sampled_points"]
    second_rates=[row["conflicts_in_at_least_three_views"]/second_control["sampled_points"] for row in second_control["thresholds"]]
    lines=["# 相同原始像素的分组变换交叉检查","",
        f"每帧固定抽样最多 {report['points_per_frame']} 个边缘处理后、原 ROI 内的深度点，共 {report['sampled_points']:,} 个。整扫描与分组变换使用相同帧 ID 和像素 ID；未重新配准、未重新融合。", "",
        "13:10:19 曾参与分组变换拟合。13:11:27 未参与该拟合，其到参考的既有配准保持固定，但它已在早期实验中被查看，所以这是有条件的额外数据检查，不能称为盲测或物理精度验证。这几份绿色杯子按同物体候选研究，物理身份尚未独立确认，差异也可能来自物体本身。", "",
        "![同一批原始深度点的证据着色](evidence-comparison.png)", "",
        "| 检查深度 | 阈值 mm | 点数 | 至少两视图支持：整段→分组 | 至少三视图冲突：整段→分组 |", "| --- | --- | --- | --- | --- |"]
    for row in report["results"]:
        for threshold in row["thresholds"]:
            a,b=threshold["arms"].values();n=row["points"]
            lines.append(f"| {row['target_id'].removeprefix('scan_20261018')} | {threshold['tolerance_mm']:g} | {n:,} | {a['supported_in_at_least_two_views']/n:.1%} → {b['supported_in_at_least_two_views']/n:.1%} | {a['conflicts_in_at_least_three_views']/n:.1%} → {b['conflicts_in_at_least_three_views']/n:.1%} |")
    lines += ["", "**不能只看冲突下降。** 原参考上，相同原始点的支持比例反而下降；额外扫描上，2 mm 冲突增加，而 4 mm 冲突减少，结论对阈值敏感。它与之前融合表面点的统计口径不同：这里逐帧原始观测有重复权重，不能直接拿两个比例互相比精度。", "",
        "还限制在两种变换下都至少三次投影得到有效深度的相同点中比较，避免把移出可观测范围误认为改善：", "",
        "| 检查深度 | 共同可观测点 | 2 mm 冲突：整段→分组 | 4 mm 冲突：整段→分组 |", "| --- | --- | --- | --- |"]
    for row in report["results"]:
        values=[]
        for threshold in row["thresholds"]:
            a,b=threshold["arms"].values();a,b=a["common_observed_subset"],b["common_observed_subset"]
            values.append(f"{a['conflicts_in_at_least_three_views']:,} → {b['conflicts_in_at_least_three_views']:,}")
        lines.append(f"| {row['target_id'].removeprefix('scan_20261018')} | {row['paired_common_observed_at_least_three']:,} | {values[0]} | {values[1]} |")
    d=diagnostics[0]
    lines += ["",f"在原参考的共同可观测点中，有 {d['common_observed_conflict_only_to_inconclusive_at_2mm']:,} 点从“重复冲突且支持不足”变成“未定”，其中 {d['those_with_three_or_more_candidate_occluded_views']:,} 点在新位置至少三次被前方表面遮挡。冲突消失可能是遮挡关系变化，并不等于这些点获得了真实表面支持。", "",
        "遮挡、支持和冲突来自不同视图，计数可以同时存在。紫色点表示同一点既有支持又有冲突；不能把它们简单算作正确或错误。", "",
        "分类规则：支持至少两视图、重复冲突至少三视图。绿色表示达到支持门槛且未达到重复冲突门槛，并非零冲突；红色表示达到重复冲突门槛且未达到支持门槛，并非绝对零支持。", "",
        f"另做了原深度内部控制：每帧最多 64 点，自己检查自己时排除源帧及前后 8 条索引记录。索引按完整帧 ID 升序，不代表真实时间。13:10:19 在 2 mm 下约 {first_rate:.2%} 点有重复冲突；13:11:27 约 {second_rates[0]:.2%}，在 4 mm 下约 {second_rates[1]:.2%}。因此不能把后一工程当作没有误差的裁判，也不能因此忽略候选的明显残余冲突。两个扫描间的重复观测检查另有各自误差。", "",
        f"内部对照见 [原始深度重复性检查](../{args.controls.name}/README.md)。", "",
        "本轮结论：保留分段候选，暂不自动采用。软件需要保留阈值扫描、支持/冲突/遮挡的多份证据，并让用户检查杯口、杯底和杯柄等有辨识力的区域。", "",
        "[三维审阅](review.html) · [全部分组、转移矩阵与限制](summary.json) · [遮挡补充统计](diagnostics.json) · [逐帧变化](per-frame.csv)"]
    (root/"README.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(diagnostics,ensure_ascii=False))


if __name__=="__main__":main()

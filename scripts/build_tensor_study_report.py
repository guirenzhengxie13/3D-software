"""Compare fixed-resolution tensor experiments with the existing baseline."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image,ImageDraw

from reconstruction_probe._open3d import require_open3d
from build_attribute_study_report import render,font


def read(path):return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    args=parser.parse_args();root=args.study.resolve();out=root/"experiments/tensor-tsdf";out.mkdir(parents=True,exist_ok=True)
    key="scan_20261018122607";variants=[("uniform","Uniform 基线",root/"reconstruction",root/"official-fusion-comparison")]
    for name,label in [("tensor-tsdf","Tensor · 权重阈值 0"),("tensor-weight3","Tensor · 权重阈值 3")]:
        folder=root/"experiments"/name;comparison=folder/"official-fusion-comparison"
        if not(comparison/"summary.json").exists():
            subprocess.run([sys.executable,"scripts/compare_project_previews.py","--decoded",str(root/"decoded"),"--reconstruction",str(folder/"reconstruction"),"--reference-kind","saved-fusion","--out",str(comparison)],check=True)
        variants.append((name,label,folder/"reconstruction",comparison))
    rows,pairs,clouds=[],[],[]
    for name,label,reconstruction,comparison in variants:
        report=read(reconstruction/key/"reconstruction.json");payload=read(comparison/"comparison-data.json")
        pair=payload["pairs"][0];pair["id"]=name;pair["label"]=label+" vs 官方保存融合"
        pair["metadata"]["notes"].append("同一组深度、优化位姿、边缘阈值和 3.750457 mm TSDF 截断；后端、体素格位置、提取方法及权重门槛可能不同。")
        pairs.append(pair);stats=pair["stats"]["1"]
        rows.append({"variant":name,"label":label,"integrated_frames":report["integrated_frames"],"effective_voxel_mm":report["voxel_mm"],
            "sdf_truncation_mm":report["sdf_truncation_mm"],"surface_points":report["quality"]["point_count"],"quality":report["quality"],
            "tensor_diagnostics":report.get("tensor_diagnostics"),"own_to_official_median_mm":stats["medianOwn"],"official_to_own_median_mm":stats["medianOfficial"],
            "own_supported_fraction_at_1mm":stats["own"]["commonFraction"],"official_supported_fraction_at_1mm":stats["official"]["commonFraction"],
            "decoded_index_sha256":report["decoded_index_sha256"]})
        clouds.append((label,reconstruction/key/"tsdf_pointcloud_mm.ply"))
    payload["pairs"]=pairs;payload["initialPair"]="tensor-weight3"
    (out/"comparison-data.json").write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    subprocess.run([sys.executable,"scripts/build_fusion_comparison.py","--data",str(out/"comparison-data.json"),"--out",str(out/"comparison.html")],check=True,stdout=subprocess.DEVNULL)
    index=read(root/"decoded"/key/"index.json");official=Path(index["source_directory"])/"pointclouds/Fused 1018_1 (0.40mm).ply"
    clouds.append(("官方保存融合",official))
    command=[sys.executable,"scripts/build_reconstruction_review.py","--unit","mm","--up-axis","x","--invert-up","--allow-overlay","--max-points","25000","--out",str(out/"review.html"),"--notes","同一 563 帧与优化位姿。Uniform 实际体素约 0.938 mm，Tensor 固定 0.4 mm。更多表面点不代表更准确；权重门槛会影响低观测区域。官方融合参数写为 0.4 mm，算法不相同。"]
    for label,path in clouds:command += ["--cloud",label+"="+str(path)]
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    o3d=require_open3d();pcs=[o3d.io.read_point_cloud(str(p)) for _,p in clouds]
    xyz=np.asarray(pcs[-1].points);bounds=(xyz.min(0),xyz.max(0));picture=Image.new("RGB",(1500,440),(24,33,47));d=ImageDraw.Draw(picture)
    for i,((label,_),pc) in enumerate(zip(clouds,pcs)):
        d.text((i*375+9,10),label,font=font(16),fill="#edf3fa")
        picture.paste(render(pc,(365,350),yaw=1.2,pitch=.15,bounds=bounds),(i*375+5,40))
    d.text((12,405),"统一观察方向与范围，显示增亮；评估细节请查看完整 PLY。固定体素与支持阈值的变化不等于精度证明。",font=font(15),fill="#adbed1")
    picture.save(out/"comparison.png")
    summary={"scan_id":key,"unit":"mm","variants":rows,
        "same_decoded_index":len({row["decoded_index_sha256"] for row in rows})==1,
        "interpretation":"Higher resolution changes density and support in both directions; it is not evidence of superior physical accuracy. Default baseline unchanged.",
        "reference_documentation":"https://www.open3d.org/docs/latest/tutorial/t_reconstruction_system/voxel_block_grid.html"}
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# 固定 0.4 mm 稀疏融合实验\n","[三色对比](comparison.html) · [彩色三维审阅](review.html)\n","同一份人偶工程的 563 帧、相同优化位姿、相同 3 mm 深度边缘规则和 3.750457 mm 截断。Tensor 使用 CPU VoxelBlockGrid；旧 ScalableTSDF 在本机平面控制中仍返回空，但这不等于所有稀疏后端不可用。\n","| 方案 | 实际体素 mm | 表面点数 | 自研→官方距离中位数 | 官方→自研中位数 | 1 mm 双向支持 |","| --- | ---: | ---: | ---: | ---: | --- |"]
    for row in rows:lines.append(f"| {row['label']} | {row['effective_voxel_mm']:.3f} | {row['surface_points']:,} | {row['own_to_official_median_mm']:.3f} | {row['official_to_own_median_mm']:.3f} | {row['own_supported_fraction_at_1mm']:.2%} / {row['official_supported_fraction_at_1mm']:.2%} |")
    lines += ["\n分析按共同固定原点的 0.5 mm 体素进行双向最近邻，不额外对齐。官方保存融合不是独立真值。后端、格点位置、表面提取和权重门槛都可能造成差异，不能只把增加的点数当成改善。默认 26 份主基线保留。\n","权重阈值是融合中的观测累积门槛，不是厂商置信度或独立概率。过高会去掉真实的少视角细节。\n","参考：[Open3D Voxel Block Grid 官方说明](https://www.open3d.org/docs/latest/tutorial/t_reconstruction_system/voxel_block_grid.html)。本机数值控制与实际样本结果另存 JSON。\n"]
    (out/"README.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":main()

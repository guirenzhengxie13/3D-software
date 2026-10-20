"""Build local tables, static renderings and an index for the 2026-10-18 study.

This assembles completed analyses; it never changes source scans or poses.
Static panels use orthographic point rendering with a declared display gain.
"""

import argparse
from collections import Counter
import html
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.spatial import cKDTree

from reconstruction_probe._open3d import require_open3d


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def font(size):
    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render(cloud, size=(440, 340), yaw=-1.15, pitch=.2, gain=1.8, bounds=None):
    xyz = np.asarray(cloud.points)
    selected = np.linspace(0, len(xyz)-1, min(100000, len(xyz)), dtype=np.int64)
    xyz = xyz[selected]
    if not len(xyz):
        return Image.new("RGB", size, (17, 25, 38))
    lower, upper = (xyz.min(0), xyz.max(0)) if bounds is None else bounds
    q = xyz - (lower + upper) / 2
    # Same negative-X-up view as the review page. Coordinates are unchanged.
    direction = np.array([-np.sin(pitch), np.cos(yaw)*np.cos(pitch), np.sin(yaw)*np.cos(pitch)])
    right = np.cross(direction, [-1., 0, 0]); right /= np.linalg.norm(right)
    up = np.cross(right, direction)
    uv = np.column_stack((q @ right, q @ up))
    corners = np.array([[x,y,z] for x in (lower[0],upper[0]) for y in (lower[1],upper[1]) for z in (lower[2],upper[2])])
    corner_uv = np.column_stack(((corners-(lower+upper)/2)@right, (corners-(lower+upper)/2)@up))
    extent = max(np.ptp(corner_uv[:, 0])/size[0], np.ptp(corner_uv[:, 1])/size[1], 1e-6)
    scale = .84/extent
    x = np.rint(uv[:, 0]*scale + size[0]/2).astype(int)
    y = np.rint(-uv[:, 1]*scale + size[1]/2).astype(int)
    rgb = np.asarray(cloud.colors)[selected] if cloud.has_colors() else np.full((len(xyz), 3), .65)
    # Uniform gray exports have no physical color. Keep their normal shading
    # below clipping instead of applying the colored-image display boost.
    if np.max(np.ptp(rgb, axis=0)) < 1/255 and np.ptp(rgb[0]) < 1/255:
        gain = 1.
    if cloud.has_normals():
        lighting = .65 + .35*np.abs(np.asarray(cloud.normals)[selected] @ direction)
        rgb = rgb * lighting[:, None]
    rgb = np.rint(np.clip(rgb*gain, 0, 1)*255).astype(np.uint8)
    pixels = np.empty((size[1], size[0], 3), np.uint8); pixels[:] = [17, 25, 38]
    near_order = np.argsort(-(q @ direction), kind="stable")
    # First in each pixel is the nearest sample. Small splats aid sparse views.
    for dx, dy in [(0,0), (1,0), (0,1), (1,1)]:
        sx, sy = x[near_order]+dx, y[near_order]+dy
        valid = (sx>=0)&(sy>=0)&(sx<size[0])&(sy<size[1])
        sx, sy, indices = sx[valid], sy[valid], near_order[valid]
        _, first = np.unique(sy*size[0]+sx, return_index=True)
        pixels[sy[first], sx[first]] = rgb[indices[first]]
    return Image.fromarray(pixels)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("reports/range2-study-20261018"))
    args = parser.parse_args()
    root = args.root.resolve()
    summaries = read(root/"decoded/summary.json")
    indices = {p.parent.name: read(p) for p in (root/"decoded").glob("*/index.json")}
    reports = {p.parent.name: read(p) for p in (root/"reconstruction").glob("*/reconstruction.json")}
    previews = {p["scan_id"]: p for p in read(root/"comparison/summary.json")["pairs"]}
    totals = Counter()
    for row in summaries:
        totals.update(row["status"])
    o3d = require_open3d()
    assets = root/"assets"; assets.mkdir(exist_ok=True)
    small_font, title_font = font(15), font(23)
    cards = []
    for key in sorted(reports):
        cloud = o3d.io.read_point_cloud(str(root/"reconstruction"/key/"tsdf_pointcloud_mm.ply"))
        card = Image.new("RGB", (460, 420), (24, 33, 47)); d = ImageDraw.Draw(card)
        d.text((13, 9), key.removeprefix("scan_"), font=title_font, fill="#edf3fa")
        card.paste(render(cloud), (10, 43))
        q = reports[key]["quality"]
        d.text((13, 388), f"{q['point_count']:,} 点 · 体素 {reports[key]['voxel_mm']:.2f} mm", font=small_font, fill="#b1c5db")
        card.save(assets/(key+".png")); cards.append(card)
    overview = Image.new("RGB", (460*4, 420*int(np.ceil(len(cards)/4))), (12, 19, 30))
    for i, card in enumerate(cards): overview.paste(card, ((i%4)*460, (i//4)*420))
    overview.save(root/"reconstruction-overview.png")
    # Color check uses the same camera basis and complete cloud bounds.
    figure_id = "scan_20261018122607"
    index = indices[figure_id]; source = Path(index["source_directory"])
    own_path = root/"reconstruction"/figure_id/"tsdf_pointcloud_mm.ply"
    fusion_path = source/"pointclouds/Fused 1018_1 (0.40mm).ply"
    own = o3d.io.read_point_cloud(str(own_path)); xyz = np.asarray(own.points)
    rgb = np.asarray(own.colors)*255
    color_audit = {"physical_reference": "用户确认：蝴蝶结蓝色", "mapping": "A,B,G,R bytes -> R,G,B,A array",
        "jpeg": "原始字节保留。Pillow 标准 RGB 解码在这批数据中需交换 R/B 才与实物及保存 PLY 一致。",
        "correction_note": "早期只验证了与原始 JPEG 的数值一致性，未证明颜色的物理含义；旧 color-*-probe/audit.json 是修正前诊断。",
        "checks": []}
    panels = Image.new("RGB", (1500, 480), (24, 33, 47)); d = ImageDraw.Draw(panels)
    bounds = (xyz.min(0), xyz.max(0))
    for i, (label, p) in enumerate([("自研 TSDF · 通道修正后", own_path), ("官方保存融合 PLY", fusion_path), ("官方保存预览 PLY", source/"raw_preview.ply")]):
        cloud = o3d.io.read_point_cloud(str(p))
        panels.paste(render(cloud, (490, 395), yaw=1.2, pitch=.1, bounds=bounds), (i*500+5, 45))
        d.text((i*500+12, 10), label, font=title_font, fill="#edf3fa")
        if i:
            distances, nearest = cKDTree(np.asarray(cloud.points)).query(xyz)
            mask = (distances<.5)&((rgb.max(1)-rgb.min(1))>40)
            native_rgb = np.asarray(cloud.colors)[nearest[mask]]*255
            color_audit["checks"].append({"reference": label, "chromatic_points_within_0_5mm": int(mask.sum()),
                "rgb_median_mae": float(np.median(np.abs(rgb[mask]-native_rgb).mean(1))),
                "rb_swapped_median_mae": float(np.median(np.abs(rgb[mask][:,[2,1,0]]-native_rgb).mean(1)))})
    d.text((15, 450), "同一坐标系、相同观察方向；仅显示增亮 1.8 倍及简易光照，不改变导出点云。", font=small_font, fill="#b1c5db")
    panels.save(root/"color-comparison.png")
    (root/"color-validation.json").write_text(json.dumps(color_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    roi_section = ""
    roi_path = root/"experiments/cup-roi/summary.json"
    if roi_path.exists():
        roi_rows = read(roi_path)
        roi_image = Image.new("RGB", (1500, 500*len(roi_rows)), (24, 33, 47)); rd = ImageDraw.Draw(roi_image)
        for j, row in enumerate(roi_rows):
            key = row["scan_id"]; lower, upper = np.array(row["bounds_min_mm"]), np.array(row["bounds_max_mm"])
            original = o3d.io.read_point_cloud(str(root/"reconstruction"/key/"tsdf_pointcloud_mm.ply"))
            xyz = np.asarray(original.points); chosen = np.flatnonzero(np.all((xyz>=lower)&(xyz<=upper),axis=1))
            zoom = original.select_by_index(chosen)
            candidate = o3d.io.read_point_cloud(str(root/"experiments/cup-roi/candidate"/key/"tsdf_pointcloud_mm.ply"))
            rd.text((12,j*500+8), key.removeprefix("scan_")+f" · 体素 {row['baseline']['voxel_mm']:.3f} → {row['candidate']['voxel_mm']:.3f} mm", font=title_font, fill="#edf3fa")
            for i,(title,cloud,bounds) in enumerate([("原全场景",original,None),("原结果 · 仅显示物体盒内",zoom,(lower,upper)),("裁剪深度后重新融合",candidate,(lower,upper))]):
                rd.text((i*500+12,j*500+47),title,font=small_font,fill="#adbed1")
                roi_image.paste(render(cloud,(490,395),yaw=1.2,pitch=.15,bounds=bounds),(i*500+5,j*500+78))
            rd.text((12,j*500+477),"中、右使用相同观察方向与空间范围；裁剪不修改位姿。密度变化包含实际体素变细的影响。",font=small_font,fill="#adbed1")
        roi_image.save(root/"experiments/cup-roi/comparison.png")
        roi_section = '''<h2>物体区域选择实验</h2><p>针对两份失败的绿色杯子扫描，保持原位姿，用颜色观测提出空间盒、保留盒内全部颜色的深度，再重新融合。13:12:22 的实际体素 2.063→0.607 mm，主连通面 38.8%→88.1%；13:13:59 为 2.186→0.598 mm、55.6%→95.0%。背景减少，表示变细，尚不等于跟踪已修复或物理精度提高。</p><figure><img src="experiments/cup-roi/comparison.png" alt="原场景、原结果局部和裁剪后重新融合"><figcaption><a href="experiments/cup-roi/README.md">选区规则、统计与局限</a> · <a href="experiments/cup-roi/scan_20261018131222-review.html">13:12:22 三维对照</a> · <a href="experiments/cup-roi/scan_20261018131359-review.html">13:13:59 三维对照</a></figcaption></figure>'''
        if (root/"experiments/cup-registration/summary.json").exists():
            roi_section += '<p><a class="button" href="experiments/cup-registration/review.html">杯子多工程配准与组合候选</a>　几何门槛及变换见 <a href="experiments/cup-registration/summary.json">配准记录</a>。</p>'
    visibility_path = root/"experiments/cup-visibility/summary.json"
    if visibility_path.exists():
        evidence = read(visibility_path)
        picture = Image.new("RGB", (1500, 430), (24, 33, 47)); ed = ImageDraw.Draw(picture)
        for i,row in enumerate(evidence["results"]):
            key = row["source"]
            cloud = o3d.io.read_point_cloud(str(visibility_path.parent/(key+"-evidence-mm.ply")))
            ed.text((i*375+10,10),"参考自检" if key=="reference_tsdf_control" else key.removeprefix("scan_"),font=small_font,fill="#edf3fa")
            picture.paste(render(cloud,(365,340),yaw=1.2,pitch=.15,gain=1.),(i*375+5,40))
            conflicting=row["threshold_checks"][0]["points_with_three_or_more_free_space_conflicts"]/row["sampled_surface_points"]
            ed.text((i*375+10,390),f"含重复冲突的点 {conflicting:.1%}",font=small_font,fill="#adbed1")
        picture.save(visibility_path.parent/"evidence.png")
        roi_section += '''<h2>低重叠与观测冲突的区别</h2><p>将对齐候选投回 13:10:19 保存的 27 个深度视图，分别记录支持、遮挡和可能的空域冲突。每组抽样 20,000 点，2 mm 容差下，参考自检没有重复冲突，13:11 候选有 3.2%，两份失败扫描为 22.6% 和 18.5%。这些是同源数据的内部证据，不能裁定哪份扫描绝对正确。</p><figure><img src="experiments/cup-visibility/evidence.png" alt="四组模型的深度支持与冲突着色"><figcaption>绿：至少两视图支持、无重复冲突；紫：支持与冲突并存；红：重复冲突且不足两次支持；灰：未定。遮挡不算冲突。<a href="experiments/cup-visibility/review.html">三维证据</a> · <a href="experiments/cup-visibility/summary.json">阈值与计数</a>。</figcaption></figure>'''
    complementary_path = root/"experiments/cup-complementarity/summary.json"
    if complementary_path.exists():
        comp_folder = complementary_path.parent
        paths = [root/"reconstruction/scan_20261018131019/tsdf_pointcloud_mm.ply",
            root/"experiments/cup-registration/scan_20261018131127-aligned-candidate-mm.ply", comp_folder/"two-surface-candidate-mm.ply"]
        trio = [o3d.io.read_point_cloud(str(p)) for p in paths]
        bounds = (np.asarray(trio[-1].points).min(0),np.asarray(trio[-1].points).max(0))
        picture = Image.new("RGB", (1500,460),(24,33,47)); cd = ImageDraw.Draw(picture)
        for i,(title,cloud) in enumerate(zip(["13:10 原表面","13:11 对齐候选","两表面组合 · 待人工审阅"],trio)):
            cd.text((i*500+12,10),title,font=title_font,fill="#edf3fa")
            picture.paste(render(cloud,(490,390),yaw=1.2,pitch=.15,bounds=bounds),(i*500+5,45))
        picture.save(comp_folder/"comparison.png")
        roi_section += '''<h2>翻面扫描的互补候选</h2><p>13:10 与 13:11 的低表面重叠，可能部分来自不同可见区域。反向深度检查同样保留了自检、阈值和冲突计数。因此另存一个两表面组合候选供人工检查；它没有通过原先的完整重叠门槛，也没有纳入主结果。组合是已重建表面点的体素整合，不是多工程原深度重新 TSDF。</p><figure><img src="experiments/cup-complementarity/comparison.png" alt="两次杯子扫描与组合探索候选"><figcaption><a href="experiments/cup-complementarity/review.html">互补候选三维审阅</a> · <a href="experiments/cup-complementarity/summary.json">双向深度证据与局限</a>。</figcaption></figure>'''
    tensor_path = root/"experiments/tensor-tsdf/summary.json"
    if tensor_path.exists():
        tensor = read(tensor_path)
        fine = tensor["variants"][-1]
        roi_section += f'''<h2>固定 0.4 mm 的稀疏融合后端</h2><p>已用 CPU Tensor VoxelBlockGrid 重新融合人偶同一 563 帧，保持位姿、边缘规则和截断距离。固定 0.4 mm、提取权重阈值 3 时得到 {fine['surface_points']:,} 个表面点；原 Uniform 基线为 139,848 点、实际体素约 0.938 mm。不同方向的支持统计有改善也有退步，尚不宣称整体更准确；默认基线保留。</p><figure><img src="experiments/tensor-tsdf/comparison.png" alt="Uniform、两种权重的固定体素融合与官方保存融合"><figcaption><a href="experiments/tensor-tsdf/comparison.html">三种方案对官方融合的三色选点</a> · <a href="experiments/tensor-tsdf/review.html">彩色三维结果</a> · <a href="experiments/tensor-tsdf/README.md">参数、统计和局限</a>。</figcaption></figure>'''
    groups_path = root/"experiments/cup-id-groups/summary.json"
    if groups_path.exists():
        groups = read(groups_path)
        selected = read(root/"experiments/cup-roi/scan_20261018131359-selection.json")
        bounds = (np.array(selected["bounds_min_mm"]),np.array(selected["bounds_max_mm"]))
        paths = [("两组共同融合",root/"experiments/cup-roi/candidate/scan_20261018131359/tsdf_pointcloud_mm.ply")]
        paths += [(f"组 {row['id_high_word']} · {row['frames']} 帧",groups_path.parent/f"id_high_{row['id_high_word']}"/"scan_20261018131359/tsdf_pointcloud_mm.ply") for row in groups["groups"]]
        picture = Image.new("RGB",(1500,440),(24,33,47));gd = ImageDraw.Draw(picture)
        for i,(title,path) in enumerate(paths):
            cloud = o3d.io.read_point_cloud(str(path));gd.text((i*500+12,10),title,font=title_font,fill="#edf3fa")
            picture.paste(render(cloud,(490,350),yaw=1.2,pitch=.15,bounds=bounds),(i*500+5,45))
        gd.text((12,405),"参与帧分组实验：原位姿、选区、体素和截断规则相同；组的厂商语义未确认。",font=small_font,fill="#adbed1")
        picture.save(groups_path.parent/"comparison.png")
        roi_section += '''<h2>参与帧分组实验</h2><p>13:13:59 可按完整帧 ID 高位分为 220 帧与 138 帧。分别融合时不修改位姿，使用相同空间盒和体素。主连通面比例与跨扫描深度冲突给出的排序并不一致，说明不能只按片段长短或最大连通面自动删帧。两组均保留。</p><figure><img src="experiments/cup-id-groups/comparison.png" alt="同一扫描两组帧的分开融合"><figcaption><a href="experiments/cup-id-groups/review.html">分组三维对照</a> · <a href="experiments/cup-id-groups/summary.json">帧选择和指标</a>。</figcaption></figure>'''
    piecewise_path = root/"experiments/cup-piecewise-pose/summary.json"
    if piecewise_path.exists():
        piecewise = read(piecewise_path)
        paths = [("另一扫描作为参考",root/"reconstruction/scan_20261018131019/tsdf_pointcloud_mm.ply"),
            ("整扫描统一变换 · 对照",piecewise_path.parent/"whole_scan_control/scan_20261018131359/tsdf_pointcloud_mm.ply"),
            ("两组分别变换 · 候选",piecewise_path.parent/"piecewise_candidate/scan_20261018131359/tsdf_pointcloud_mm.ply")]
        pcs = [o3d.io.read_point_cloud(str(p)) for _,p in paths]
        bounds = (np.min([pc.get_min_bound() for pc in pcs],axis=0),np.max([pc.get_max_bound() for pc in pcs],axis=0))
        picture = Image.new("RGB",(1500,440),(24,33,47));pd = ImageDraw.Draw(picture)
        for i,((title,_),pc) in enumerate(zip(paths,pcs)):
            pd.text((i*500+12,10),title,font=title_font,fill="#edf3fa")
            picture.paste(render(pc,(490,350),yaw=1.2,pitch=.15,bounds=bounds),(i*500+5,45))
        pd.text((12,405),"相同 358 帧、相同原坐标 ROI、固定 0.6 mm 与权重阈值 3。候选为参考辅助对齐；未纳入主结果。",font=small_font,fill="#adbed1")
        picture.save(piecewise_path.parent/"comparison.png")
        roi_section += '''<h2>分段对齐后重新融合</h2><p>两组表面分别向参考扫描配准，估计的刚体校正彼此相差约 178.5°，提示需要检查翻面或分段坐标关系；这不是已证实的物理转角。用相同 358 帧、相同原选区和固定 0.6 mm 重新融合，至少两视图支持从 57.8% 升至 66.8%，重复深度冲突从 20.1% 降至 9.7%。主连通面却从 97.1% 降至 92.1%，问题未全部解决，因此仍只保留候选。</p><figure><img src="experiments/cup-piecewise-pose/comparison.png" alt="统一变换与分段变换重新融合的对照"><figcaption><a href="experiments/cup-piecewise-pose/review.html">分段融合三维对照</a> · <a href="experiments/cup-piecewise-pose/summary.json">同输入核对、矩阵、指标和局限</a>。参考扫描参与拟合和评价，非独立精度验证。</figcaption></figure>'''
    crosscheck_path = root/"experiments/cup-piecewise-crosscheck/summary.json"
    if crosscheck_path.exists():
        crosscheck = read(crosscheck_path)
        validation = crosscheck["results"][1]
        a2,b2 = validation["thresholds"][0]["arms"].values()
        a4,b4 = validation["thresholds"][1]["arms"].values()
        n = validation["points"]
        roi_section += f'''<h2>同一原像素交叉检查：改善仍有条件</h2><p>固定 {n:,} 个原始深度点，并用未参与分组变换拟合的 13:11:27 检查。2 mm 下支持从 {a2['supported_in_at_least_two_views']/n:.1%} 增至 {b2['supported_in_at_least_two_views']/n:.1%}，冲突也从 {a2['conflicts_in_at_least_three_views']/n:.1%} 增至 {b2['conflicts_in_at_least_three_views']/n:.1%}；4 mm 下冲突则从 {a4['conflicts_in_at_least_three_views']/n:.1%} 降至 {b4['conflicts_in_at_least_three_views']/n:.1%}。不能只挑有利阈值宣布成功。原参考中，很多“冲突消失”的点变成被遮挡、证据未定，并没有新增支持。仍保留候选。</p><figure><img src="experiments/cup-piecewise-crosscheck/evidence-comparison.png" alt="相同原始深度点在两份扫描上的支持与冲突"><figcaption><a href="experiments/cup-piecewise-crosscheck/README.md">完整方法、阈值与遮挡解释</a> · <a href="experiments/cup-piecewise-crosscheck/review.html">三维证据着色</a> · <a href="experiments/cup-depth-repeatability/README.md">原深度内部对照</a>。额外扫描的既有配准也有误差，不是独立物理真值。</figcaption></figure>'''
    if (root/"frame-metadata/summary.json").exists():
        roi_section += '''<h2>帧元数据调查</h2><p>9,434 条帧信息均为 75 字节。序号候选存在重置、跳号和倒退；状态候选也不等价于优化位姿是否存在。尚不能据此恢复真实采集时间或自动删帧。8,790 对保存/优化位姿逐元素相同，562 对不同；优化表存在不证明每份扫描都改过位姿。</p><p><a href="frame-metadata/README.md">字段事实与边界</a> · <a href="frame-metadata/frames.csv">逐帧字段</a>。</p>'''
    direct = root/"experiments/cup-direct-split"
    if (direct/"full-reconstruction/summary.json").exists():
        roi_section += '''<h2>不用外部参考：直接对齐片段</h2><p>同一工程拆成两个片段，以 186 帧训练、172 帧留出。仅用训练几何直接配准，原像素留出检查的 2 mm 支持由 42.0% 升至 49.7%，重复冲突由 28.1% 降至约 0.4%。另一候选支持更多但冲突也更多，仍保留多解。全 358 帧演示减少了重复杯柄轮廓，但孔洞和碎片仍在。</p><figure><img src="experiments/cup-direct-split/full-reconstruction/comparison.png" alt="原保存关系、两个直接片段配准及颜色精修的全帧融合"><figcaption><a href="experiments/cup-direct-split/README.md">训练/留出设计、颜色尝试与限制</a> · <a href="experiments/cup-direct-split/full-reconstruction/review.html">全帧候选三维对照</a> · <a href="experiments/cup-direct-split/evaluation/review.html">留出原像素证据</a>。</figcaption></figure>'''
    if (direct/"landmark-workbench.html").exists():
        roi_section += '''<h2>对应点配准工作台</h2><p>固定片段、移动片段、对齐预览分三栏。Alt 单击选至少三对同一物理位置，立即计算刚体对齐，导出原点编号、对应关系与矩阵。后端核对原文件与点编号，再用完整精度坐标重新求解；原模型不覆盖。当前完成数值和模拟交互检查，实际 GPU 画面仍待验证。</p><p><a class="button" href="experiments/cup-direct-split/landmark-workbench.html">打开对应点工作台</a> · <a href="../../docs/landmark-workbench.md">使用方法与接回融合程序</a>。</p>'''
    if (direct/"view-coverage/summary.json").exists():
        roi_section += '''<h2>从表面点回查原帧，再提出补扫方向</h2><p>区分支持次数与视角分布：一个杯内壁附近的代表点有 27 帧支持，但与首支持视角最大夹角仅 9.77°。已恢复具体帧号、深度像素和对齐颜色。覆盖诊断用于解释已有表面，不推断完全未扫到的形状。</p><figure><img src="experiments/cup-direct-split/view-coverage/comparison.png" alt="表面观测覆盖、重复冲突和方向分布"><figcaption><a href="experiments/cup-direct-split/view-coverage/README.md">覆盖方法与三维审阅</a> · <a href="experiments/cup-direct-split/point-trace-weak-region/README.md">点到原帧和像素的证据</a> · <a href="../../docs/offline-coverage-guidance.md">离线链路说明</a>。</figcaption></figure>'''
    if (direct/"scan-view-proposals/summary.json").exists():
        plan = read(direct/"scan-view-proposals/summary.json")
        roi_section += f'''<h2>离线补扫方向原型</h2><p>对 {len(plan['recommendations'])} 个已观察弱区域检查新方向、法向入射和当前网格射线可见性，保留 {plan['proposals']} 个需用户判断的建议。冲突区域先检查配准；遮挡不满足条件时不强行给出建议。建议在物体参考系中，不是房间轨迹或设备执行指令。</p><figure><img src="experiments/cup-direct-split/scan-view-proposals/directions.png" alt="弱区域的离线观察方向建议"><figcaption><a href="experiments/cup-direct-split/scan-view-proposals/README.md">建议、矩阵、可见性和限制</a>。箭头长度仅为显示，实际建议距离见表。</figcaption></figure>'''
    if (root/'experiments/depth-sequence-consistency/README.md').exists():
        roi_section += '''<h2>失败扫描：定位分歧，也保留失败尝试</h2><p>13:12:22 在相邻记录中找到 7 处明显深度分歧。理想转轴约束增加了冲突；拆为 8 段后，自动几何连接仅 3/7 通过门槛，没有强行进行全局优化。颜色精修也没有救回连接，其中一处保留原始关系更合理。</p><p><a href="experiments/depth-sequence-consistency/README.md">逐记录深度检查</a> · <a href="experiments/fixed-axis-depth-prior/README.md">固定轴对照</a> · <a href="experiments/cup-segment-pose-graph/README.md">分段连接</a> · <a href="experiments/cup-segment-color-edges/README.md">颜色候选</a> · <a href="experiments/cup-segment-pose-graph/manual-workbenches/README.md">对应点工作台</a>。</p>'''
    if (root/'experiments/cup-multi-scan-tsdf/README.md').exists():
        roi_section += '''<h2>两份原始深度工程联合融合</h2><p>208＋255＝463 帧保存深度直接进入同一个 0.6 mm 稀疏 TSDF，生成约 19 万点的联合候选。各来源在单独与联合实验的像素、RGB 和位姿逐数组哈希相同。联合表面抽样中，约 52.3% 双方支持、32.0% 仅第一份支持、15.5% 仅第二份支持；12.8% 仍有重复深度冲突。配准尚未通过原先完整重叠门槛，结果继续保留候选状态。</p><figure><img src="experiments/cup-multi-scan-tsdf/comparison.png" alt="两份扫描各自与联合原始深度融合"><figcaption><a href="experiments/cup-multi-scan-tsdf/README.md">输入证明、来源着色、互补与问题</a> · <a href="experiments/cup-multi-scan-tsdf/review.html">三维对照</a> · <a href="experiments/cup-multi-scan-tsdf/depth-evidence/review.html">逐工程证据</a> · <a href="experiments/cup-multi-scan-tsdf/trace-source_only/README.md">杯底补充区域回查</a>。</figcaption></figure>'''
    if (root/'workflow-prototype-run/index.html').exists():
        roi_section += '''<h2>可重复执行的工具工作流</h2><p>六类确定性工具已注册，真实数据五步链路全部完成：来源证据、互补点回查、冲突点回查、像素邻域、局部表面距离。每步保留独立产物、输入与依赖哈希、状态和日志，失败时停止后续步骤。目前没有连接语言模型，统一编辑器仍待实现。</p><p><a class="button" href="workflow-prototype-run/index.html">查看实际五步运行</a> · <a href="../../docs/offline-workflow-runner.md">配方、工具和使用方法</a>。本次用 1,000 点验证工具串联，完整研究的 40,000 点统计分别保留。</p>'''
    # Build the standalone colored review, including official outputs separately.
    command = [sys.executable, "scripts/build_reconstruction_review.py", "--unit", "mm", "--max-points", "20000", "--up-axis", "x", "--invert-up", "--out", str(root/"review.html"),
        "--provenance", "逐帧保存深度＋标定＋工程优化位姿重新 TSDF；彩色数组已按实物蓝色蝴蝶结核对。",
        "--notes", "各工程坐标独立，逐项查看。13:05:40 基线仅融合 193 条有优化位姿的帧；另 82 帧保留。原始 JPEG 未改写，其常规解码的 R/B 与保存 PLY 相反。"]
    for key in sorted(reports): command += ["--cloud", key.removeprefix("scan_")+" | TSDF="+str(root/"reconstruction"/key/"tsdf_pointcloud_mm.ply")]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    command = [sys.executable, "scripts/build_reconstruction_review.py", "--unit", "mm", "--max-points", "25000", "--up-axis", "x", "--invert-up", "--allow-overlay", "--out", str(root/"official-fusion-comparison/color-review.html"),
        "--notes", "同一工程坐标系。此页显示实际顶点色，三色差异分类另见 comparison.html。原 JPEG 字节保留，解包色彩以实物蓝色蝴蝶结和保存 PLY 为依据。"]
    for label, path in [("自研 TSDF", own_path), ("官方保存融合", fusion_path), ("官方保存预览", source/"raw_preview.ply")]: command += ["--cloud", label+"="+str(path)]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    # Self-contained navigation plus ordinary relative links to large artifacts.
    rows, markdown = [], []
    for key, idx in sorted(indices.items()):
        n = idx["status"]; rep = reports.get(key); tag = key.removeprefix("scan_")
        if rep:
            q = rep["quality"]; quality = f"{q['point_count']:,} 点 / {q['largest_component_triangle_fraction']:.1%} 主连通面"
            geom = f"<a href='reconstruction/{key}/tsdf_pointcloud_mm.ply'>PLY</a> · <a href='reconstruction/{key}/tsdf_mesh_mm.ply'>网格</a> · <a href='reconstruction/{key}/reconstruction.json'>参数</a>"
            thumb = f"<img src='assets/{key}.png' loading='lazy' alt='{tag} 自研重建'>"
            st = previews[key]["stats"]["1"]
            support = f"{st['own']['commonFraction']:.1%} / {st['official']['commonFraction']:.1%}"
            voxel = f"{rep['voxel_mm']:.3f}"
        else:
            quality, geom, thumb, support, voxel = "空工程", "—", "", "—", "—"
        diagnostic = f"<a href='turntable-poses/{key}/report.json'>位姿</a>"
        if (root/"marker-analysis"/key/"report.json").exists(): diagnostic += f" · <a href='marker-analysis/{key}/report.json'>标记</a>"
        rows.append(f"<tr><td>{thumb}<b>{tag}</b></td><td>{n['depth_decoded']} / {n['optimized_poses_parsed']}</td><td>{n['colored_depth_frames']} / {n['marker_observations']}</td><td>{voxel}</td><td>{quality}<br>{geom}</td><td>{support}</td><td>{diagnostic}</td></tr>")
        markdown.append(f"| {tag} | {n['depth_decoded']} / {n['optimized_poses_parsed']} | {n['colored_depth_frames']} / {n['marker_observations']} | {voxel} | {quality} | {support} |")
    fusion = read(root/"official-fusion-comparison/summary.json")["pairs"][0]["stats"]["1"]
    parts = ["# 2026-10-18 扫描工程研究结果\n", "[报告首页](index.html) · [彩色三维审阅](review.html) · [26 份预览对比](comparison/comparison.html) · [官方融合对比](official-fusion-comparison/comparison.html) · [完整研究记录](../../docs/range2-study-20261018.md)\n",
        f"29 份工程，其中 26 份包含深度。读取 {totals['depth_decoded']:,} 帧，恢复 {totals['poses_parsed']:,} 条保存位姿和 {totals['optimized_poses_parsed']:,} 条优化位姿；保留 {totals['jpeg_frames']:,} 张原始 JPEG、{totals['marker_observations']:,} 次标记观测。解码错误 0。\n",
        "颜色已按用户确认的蓝色蝴蝶结校正。原始 JPEG 字节未修改；初期与 JPEG 一致的数组顺序不是最终 RGB 解释。见 [颜色核对](color-validation.json)。\n",
        f"12:26:07 有真正保存的官方融合点云，533,469 点。0.5 mm 固定体素分析、1 mm 容差下，双向支持率为 {fusion['own']['commonFraction']:.2%} / {fusion['official']['commonFraction']:.2%}。这反映几何一致性，不是物理精度结论。其余工程按原始预览比较。\n",
        "[标记补帧实验](experiments/marker-recovery/experiment.json)使留出标记残差降低，但没有改善补入深度与基线表面的对齐，未纳入主结果。\n",
        "下面的“深度/优化”是帧数；“彩色/标记”是彩色帧数与标记观测次数；支持率依次为自研→预览、预览→自研，容差 1 mm。主连通面比例仅描述网格碎片程度。\n",
        "| 工程 | 深度 / 优化 | 彩色 / 标记 | 实际体素 mm | 几何 | 预览双向支持 |", "| --- | ---: | ---: | ---: | --- | --- |", *markdown,
        "\n实际体素由场景包围盒与最多 256³ 网格共同决定，不能把请求的 0.6 mm 当成每份结果实际分辨率。源工程与 JPEG 的最终完整性校验见 source-integrity.json。\n",
        "WebGL 页面通过数据与交互逻辑检查；浏览器应用访问授权超时，内置浏览器策略也拒绝本地 file:// 页面，未完成实际 GPU 画面验证。静态渲染只用于辅助观察，不代替三维表面质量评估。\n"]
    if roi_path.exists():
        parts.append("\n[杯子选区实验](experiments/cup-roi/README.md)：两份失败扫描裁剪背景后重新融合，实际体素恢复到约 0.6 mm、主体连通面比例提高。候选未改位姿，仍须检查孔洞、重影和误裁。\n")
    if crosscheck_path.exists():
        parts.append("\n[同像素交叉检查](experiments/cup-piecewise-crosscheck/README.md)：额外扫描揭示阈值敏感与支持/冲突并存，分组候选继续保留，尚未纳入主结果。另见 [帧元数据调查](frame-metadata/README.md)。\n")
    if (root/'experiments/cup-multi-scan-tsdf/README.md').exists():
        parts.append('\n[463 帧多工程原始深度联合融合](experiments/cup-multi-scan-tsdf/README.md)：相同参数与逐来源输入核对，支持互补，也保留局部冲突。[失败扫描分段诊断](experiments/cup-segment-pose-graph/README.md)记录自动连接不足时的停止与人工审阅入口。\n')
    (root/"README.md").write_text("\n".join(parts), encoding="utf-8")
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>离线扫描工程研究 · 2026-10-18</title><style>
    body{margin:0;background:#0c1420;color:#e2ecf8;font:15px/1.7 system-ui,'Microsoft YaHei',sans-serif}main{max-width:1500px;margin:auto;padding:32px}h1{font-size:30px;margin:0}h2{margin-top:34px;font-size:22px}a{color:#9bcaff}nav{display:flex;gap:14px;flex-wrap:wrap;margin:25px 0}.button{padding:12px 18px;background:#213b58;border:1px solid #476785;border-radius:8px;text-decoration:none}.note{padding:15px 20px;background:#202d3b;border-left:3px solid #80b7e9;border-radius:6px}.cards{display:flex;gap:12px;flex-wrap:wrap}.card{background:#17283b;border:1px solid #2b425d;border-radius:8px;padding:14px 24px}.card b{display:block;font-size:29px;color:#a4d5ff}.muted{color:#adbed1}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:12px;border-bottom:1px solid #2e4055;text-align:left;vertical-align:middle}th{background:#17283b}td:first-child{width:190px}td img{display:block;width:175px;margin-bottom:6px;border-radius:5px}figure{margin:20px 0}figure img{max-width:100%;border-radius:8px}figcaption{color:#adbed1;font-size:13px}.scroll{overflow:auto}code{font-size:13px}li{margin:9px 0}</style><main>
    <p class="muted">Revo Scan 离线数据 · 保存深度、位姿、颜色与标记的实测</p><h1>从工程数据到独立融合</h1>
    <p>研究用户 2026-10-18 保存的工程。用户说明主要使用 RANGE 2 与转台；当前手边为 Inspire。文件中存在两组设备指纹，尚不据此断言每份工程的硬件型号。</p>
    <div class="cards">__CARDS__</div><nav><a class="button" href="review.html">26 份彩色三维结果</a><a class="button" href="official-fusion-comparison/comparison.html">官方融合 vs 自研 · 三色选点</a><a class="button" href="comparison/comparison.html">26 份原预览对比</a><a class="button" href="../../docs/range2-study-20261018.md">完整记录与运行方法</a></nav>
    <div class="note">12:26:07 人偶工程保存了一份 533,469 点的官方融合云，可作同源结果比较；其他工程按扫描预览比较。绿色表示容差内双方支持，蓝色仅自研支持，橙色仅官方支持。支持差异不能自动判定谁更准确。</div>
    <h2>已核实的关键点</h2><ul><li>新工程是属性表格式，深度头长 20 字节、位姿长 132 字节；旧版 16 字节头和 Y/Z 翻转不能直接沿用。本批光学到位姿轴为 [1,1,1]。</li><li>用户确认蝴蝶结为蓝色。据此核实对齐颜色字节应解释为 A,B,G,R。原 JPEG 按常规解码会红蓝相反，原件保留，解包数组和 TSDF 已修正。</li><li>13:05:40 的 275 帧中只有 193 条优化位姿。全部 275 帧均已解包；82 条缺少优化位姿的记录保留，主结果暂不融合它们。</li><li>标记修正实验用相同 271 帧作对照。留出标记中位残差 0.275→0.103 mm，但补入深度的表面对齐中位距离 4.778→4.795 mm，未采用为主结果。<a href="experiments/marker-recovery/review.html">查看实验</a>。</li><li>多份结果仍有背景、重影、碎片与孔洞。当前 TSDF 信任保存位姿；下一步重点是物体区域选择、异常帧分组、配准交互和可撤销工作流。</li></ul>
    <h2>颜色核对</h2><figure><img src="color-comparison.png" alt="通道修正后的自研结果与官方保存输出同视角对照"><figcaption>静态点渲染，显示增亮 1.8 倍。完整顶点色请用 <a href="official-fusion-comparison/color-review.html">彩色三维对照</a>；<a href="color-validation.json">数值核对</a>。</figcaption></figure>
    <h2>逐工程结果</h2><p class="muted">深度/优化为帧数；彩色/标记为彩色帧数与标记观测次数。双向支持为自研→原预览、原预览→自研，容差 1 mm。实际体素依包围盒自适应；主连通面比例描述碎片程度。</p>
    <div class="scroll"><table><thead><tr><th>工程</th><th>深度 / 优化</th><th>彩色 / 标记</th><th>体素 mm</th><th>结果与文件</th><th>预览双向支持</th><th>诊断</th></tr></thead><tbody>__ROWS__</tbody></table></div>
    <h2>验证与使用边界</h2><p>原件仅只读访问，<a href="source-integrity.json">SHA256 校验</a>另存；解码仅恢复实际保存的记录，无法证明采集时所有物理帧均被保留。时间戳和未解释字段保留为未知。标记框架与位姿都来自同一官方工程，残差不是独立精度测量。</p><p>独立 HTML 的数据与交互逻辑已检查。浏览器应用访问授权曾超时，内置浏览器也因 URL 策略拒绝本地 file:// 页面，实际 GPU 画面尚未验证。可先查看静态图、PLY 与参数 JSON。<a href="reconstruction-overview.png">26 份静态总览</a> · <a href="project-contact-sheet.png">原工程缩略图总览</a> · <a href="README.md">表格版摘要</a></p></main></html>'''
    cards = [("29", "保存工程"), (str(len(reports)), "独立 TSDF"), (f"{totals['depth_decoded']:,}", "已解包帧"), (f"{totals['jpeg_frames']:,}", "原始 JPEG"), (f"{totals['marker_observations']:,}", "标记观测")]
    page = page.replace("__CARDS__", "".join(f"<div class='card'><b>{n}</b>{html.escape(label)}</div>" for n,label in cards)).replace("__ROWS__", "".join(rows))
    page = page.replace("<h2>逐工程结果</h2>", roi_section+"<h2>逐工程结果</h2>")
    (root/"index.html").write_text(page, encoding="utf-8")
    print(json.dumps({"report": str(root/"index.html"), "projects": len(indices), "models": len(reports), "totals": dict(totals)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

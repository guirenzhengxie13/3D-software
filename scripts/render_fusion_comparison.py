"""Render three-color overview and local diagnostic crops of final surfaces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


GREEN = np.array([103, 211, 145], np.uint8)
BLUE = np.array([84, 168, 255], np.uint8)
ORANGE = np.array([255, 173, 92], np.uint8)


def font(size):
    for name in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def render(root, scan, variant, threshold):
    base = root / "comparison"
    saved = np.load(base / f"analysis_mesh_{scan}_{variant}.npz", allow_pickle=False)
    data = {key: saved[key] for key in saved.files}
    matrix = np.eye(4)
    if scan == "scan_04":
        matrix = np.asarray(json.loads((root / "registration/scan_04_registration.json").read_text(encoding="utf-8"))["transform_source_to_reference"])
    own = data["own_xyz"] @ matrix[:3, :3].T + matrix[:3, 3]
    official = data["official_xyz"] @ matrix[:3, :3].T + matrix[:3, 3]
    own_common, official_common = data["own_distances"] <= threshold, data["official_distances"] <= threshold
    labels = ["全貌 · XY", "全貌 · XZ", "头部诊断盒 · Y ≥ 0", "底座诊断盒 · Y < -95"] if scan == "scan_04" else ["全貌 · XY", "全貌 · XZ"]
    height = 140 + 380 * len(labels)
    image = Image.new("RGB", (1800, height), (13, 20, 31))
    draw = ImageDraw.Draw(image)
    title = {"scan_04": "失败扫描", "scan_03": "成功扫描", "scan_01": "标准样例"}[scan]
    title += " · 参考辅助候选" if variant == "reference_assisted" else " · 相同工程基线"
    draw.text((25, 12), title + f" | 最终网格表面对照 | 容差 {threshold:g} mm", font=font(25), fill=(237, 244, 252))
    x = 25
    for color, label in ((GREEN, "绿色：双方表面支持"), (BLUE, "蓝色：仅自研支持"), (ORANGE, "橙色：仅官方支持")):
        draw.rectangle((x, 60, x + 17, 77), fill=tuple(color))
        draw.text((x + 27, 54), label, font=font(18), fill=(202, 215, 230))
        x += 400
    draw.text((25, 92), "颜色为当前容差下的空间差异；蓝色不等于正确补全。叠加图优先显示差异，遮挡关系请在三维页面查看。", font=font(16), fill=(154, 174, 196))
    if variant == "reference_assisted":
        draw.text((1120, 14), "额外使用成功扫描，不作同输入优劣排名", font=font(17), fill=(235, 205, 143))
    for row, label in enumerate(labels):
        axes = [0, 2] if row == 1 else [0, 1]
        if row == 2:
            own_mask, official_mask = own[:, 1] >= 0, official[:, 1] >= 0
        elif row == 3:
            own_mask, official_mask = own[:, 1] < -95, official[:, 1] < -95
        else:
            own_mask, official_mask = np.ones(len(own), bool), np.ones(len(official), bool)
        oq, vq = own[own_mask], official[official_mask]
        oc, vc = own_common[own_mask], official_common[official_mask]
        merged = np.concatenate([oq, vq])
        minimum, maximum = merged[:, axes].min(0), merged[:, axes].max(0)
        center = (minimum + maximum) / 2
        span = np.maximum(maximum - minimum, 1e-6)
        scale = min(535 / span[0], 267 / span[1])

        def raster(points, color_values):
            buffer = np.empty((285, 568, 3), np.uint8)
            buffer[:] = (22, 31, 45)
            uv = np.rint((points[:, axes] - center) * scale).astype(int)
            uv[:, 0] += 284
            uv[:, 1] = 143 - uv[:, 1]
            valid = (uv[:, 0] >= 0) & (uv[:, 0] < 568) & (uv[:, 1] >= 0) & (uv[:, 1] < 285)
            uv, color_values = uv[valid], color_values[valid]
            buffer[uv[:, 1], uv[:, 0]] = color_values
            return Image.fromarray(buffer)

        y = 135 + row * 380
        draw.text((22, y), label, font=font(18), fill=(211, 224, 239))
        own_colors = np.where(oc[:, None], GREEN, BLUE)
        official_colors = np.where(vc[:, None], GREEN, ORANGE)
        # Common support is drawn first in this diagnostic projection only.
        overlay_points = np.concatenate([oq[oc], vq[vc], oq[~oc], vq[~vc]])
        overlay_colors = np.concatenate([own_colors[oc], official_colors[vc], own_colors[~oc], official_colors[~vc]])
        panels = [(vq, official_colors, "官方最终网格", vc), (oq, own_colors, "自研候选网格", oc),
                  (overlay_points, overlay_colors, "三色叠加：绿色共同 / 蓝色自研 / 橙色官方", None)]
        for column, (points, colors, text, common) in enumerate(panels):
            x0 = column * 600 + 16
            draw.text((x0 + 8, y + 31), text, font=font(16), fill=(180, 199, 220))
            image.paste(raster(points, colors), (x0, y + 62))
            draw.rectangle((x0, y + 62, x0 + 568, y + 347), outline=(60, 78, 100))
            if common is not None:
                draw.text((x0 + 8, y + 351), f"表面样本支持率 {common.mean() * 100:.2f}%  |  {len(common):,} 样本", font=font(15), fill=(154, 174, 196))
    output = base / f"three_color_{scan}_{variant}_{threshold:g}mm.png"
    image.save(output)
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("reports/four-scans"))
    parser.add_argument("--threshold", type=float, default=1.)
    args = parser.parse_args()
    for scan, variant in (("scan_04", "baseline"), ("scan_04", "reference_assisted"), ("scan_03", "baseline")):
        render(args.root, scan, variant, args.threshold)


if __name__ == "__main__":
    main()

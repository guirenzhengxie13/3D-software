"""Explain axial conflicts using measured local 3x3 point-to-plane distances."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import open3d as o3d
from PIL import Image, ImageDraw

from build_attribute_study_report import font, render
from reconstruct_scans import clean_depth_edges, write_json
from reconstruction_probe.local_surface_evidence import project_local_planes
from reconstruction_probe.multi_scan import bound_evidence_path
from reconstruction_probe.offline import file_sha256


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--fusion', type=Path, required=True); parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--evidence',type=Path,help='Separate evidence directory; defaults to FUSION/depth-evidence')
    args = parser.parse_args(); fusion = args.fusion.resolve(); out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('Use a new/empty output directory')
    out.mkdir(parents=True, exist_ok=True); metadata = read(fusion / 'summary.json')
    evidence_path=bound_evidence_path(fusion,args.evidence if args.evidence is not None else fusion/'depth-evidence')
    with np.load(evidence_path, allow_pickle=False) as saved:
        xyz = saved['xyz_shared_mm'].copy(); original_ids = saved['source_point_indices'].copy(); expected = saved['conflict_counts'].copy()
    n = len(xyz); center = np.zeros((2, 2, n), np.uint16); valid_plane = center.copy(); large_normal = center.copy(); near_normal = center.copy(); invalid = center.copy()
    plane_bins = np.zeros((2, 5), np.int64); frames = []; sources = metadata['results'][-1]['source_contributions']
    for source_index, source in enumerate(sources):
        decoded = Path(source['decoded_directory']); index = read(decoded / 'index.json'); transform = np.array(source['source_to_shared_mm'])
        for ordinal, frame in enumerate(index['frames']):
            folder = decoded / f"frame_{frame['id']:010d}"
            with np.load(folder / 'frame.npz', allow_pickle=False) as saved:
                depth = saved['depth_mm']
            depth, _ = clean_depth_edges(depth, 3.); pose = transform @ np.load(folder / 'pose_optimized.npy', allow_pickle=False)
            result = project_local_planes(xyz, pose, depth, index['intrinsics']['Pl'], source['optical_axes'])
            ids = result.point_indices; fit = result.spans_two_dimensions & (result.plane_rms_mm <= .2); normal_abs = np.abs(result.signed_point_to_plane_mm)
            for j, tolerance in enumerate([2., 4.]):
                free = result.axial_delta_mm > tolerance
                center[source_index, j, ids[free]] += 1; valid_plane[source_index, j, ids[free & fit]] += 1
                large_normal[source_index, j, ids[free & fit & (result.signed_point_to_plane_mm > tolerance)]] += 1
                near_normal[source_index, j, ids[free & fit & (normal_abs <= 1.)]] += 1; invalid[source_index, j, ids[free & ~fit]] += 1
            original_free = result.axial_delta_mm > 2.; accepted = original_free & fit
            small = normal_abs[accepted]; bins = np.array([(small <= .5).sum(), ((small > .5) & (small <= 1.)).sum(), ((small > 1.) & (small <= 2.)).sum(), (small > 2.).sum(), (original_free & ~fit).sum()], np.int64)
            plane_bins[source_index] += bins
            frames.append(dict(scan_id=source['scan_id'], frame_id=frame['id'], center_free_space_observations_2mm=int(original_free.sum()),
                accepted_local_planes=int(accepted.sum()), normal_residual_bin_counts=bins.tolist(),
                abs_view_normal_dot_quantiles=np.percentile(result.abs_view_normal_dot[accepted], [10, 50, 90]).tolist() if accepted.any() else None))
            if ordinal % 80 == 0 or ordinal + 1 == len(index['frames']):
                print(f"local planes {source['scan_id']} {ordinal + 1}/{len(index['frames'])}", flush=True)
    if not np.array_equal(center, expected) or not np.array_equal(valid_plane + invalid, center):
        raise ValueError('Original axial conflict accounting changed')
    old = (center[:, 0] >= 3).any(0); large = (large_normal[:, 0] >= 3).any(0)
    np.savez_compressed(out / 'local-plane-evidence.npz', xyz_shared_mm=xyz, source_point_indices=original_ids,
        axial_conflict_counts=center, valid_local_plane_counts=valid_plane, large_normal_distance_counts=large_normal,
        within_1mm_plane_counts=near_normal, rejected_local_plane_counts=invalid)
    results = []
    for i, source in enumerate(sources):
        results.append(dict(scan_id=source['scan_id'], original_axial_repeated_conflict_points_2mm=int((center[i, 0] >= 3).sum()),
            repeated_additional_normal_discrepancy_points_2mm=int((large_normal[i, 0] >= 3).sum()),
            original_axial_repeated_conflict_points_4mm=int((center[i, 1] >= 3).sum()),
            repeated_additional_normal_discrepancy_points_4mm=int((large_normal[i, 1] >= 3).sum()),
            original_2mm_free_space_observation_plane_bins=plane_bins[i].tolist()))
    summary = dict(status='measured_local_plane_diagnostic_not_independent_accuracy', sample_count=n,
        original_repeated_axial_conflict_points=int(old.sum()), repeated_additional_normal_discrepancy_points=int(large.sum()),
        normal_abs_residual_bin_labels=['<=0.5mm', '(0.5,1]mm', '(1,2]mm', '>2mm', 'local_plane_rejected'],
        fit_rule=dict(pixel_radius=1, minimum_valid_neighbors=6, minimum_middle_to_largest_covariance_ratio=.001, maximum_patch_plane_rms_mm=.2),
        results=results, frames=frames, input_sha256={str(p):file_sha256(p) for p in [fusion / 'summary.json', evidence_path]},
        limitations=['A local plane is fitted to the same saved depth data and is not independent ground truth.',
          'Low local fitting residual does not establish object identity or correct alignment. Tangential displacement can remain unconstrained.',
          'Plane eligibility is a diagnostic rule, not calibrated confidence; failed fits remain explicitly unassessed.',
          'The original axial depth support, free-space and occlusion evidence is retained. No frames or models are altered.',
          'Counts at 2 mm axial/normal thresholds are descriptive and do not establish a 2 mm physical accuracy specification.'])
    write_json(out / 'summary.json', summary)
    original = o3d.io.read_point_cloud(str(fusion / 'joint_raw_depth/tsdf_pointcloud_mm.ply')); rgb = np.asarray(original.colors)[original_ids]
    colors = np.tile([.40, .49, .59], (n, 1)); colors[old & ~large] = [239/255, 164/255, 82/255]; colors[large] = [192/255, 106/255, 220/255]
    clouds = []
    for label, values, name in [('实际 RGB', rgb, 'physical-rgb-mm.ply'), ('轴向差与表面法向差', colors, 'normal-distance-classes-mm.ply')]:
        cloud = o3d.geometry.PointCloud(); cloud.points = o3d.utility.Vector3dVector(xyz); cloud.colors = o3d.utility.Vector3dVector(values)
        path = out / name; o3d.io.write_point_cloud(str(path), cloud); clouds.append((label, cloud, path))
    command = [sys.executable, 'scripts/build_reconstruction_review.py', '--unit', 'mm', '--up-axis', 'x', '--invert-up', '--max-points', str(n), '--out', str(out / 'review.html'), '--notes', '原轴向重复冲突点：紫色还在同一来源至少3个合格局部平面中显示超过2mm正法向距离；橙色未达到该附加条件，可能法向差小或平面不合格，不能宣称正确。原冲突保留。']
    for label, _, path in clouds:
        command += ['--cloud', label + '=' + str(path)]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    picture = Image.new('RGB', (1000, 530), (24, 33, 47)); draw = ImageDraw.Draw(picture); bounds = (xyz.min(0), xyz.max(0))
    for i, (label, cloud, _) in enumerate(clouds):
        draw.text((i*500+12, 10), label, font=font(20), fill='#edf3fa'); picture.paste(render(cloud, (490, 390), yaw=1.2, pitch=.15, bounds=bounds, gain=1.8 if i == 0 else 1.), (i*500+5, 45))
    draw.text((12, 462), f'原轴向重复冲突 {int(old.sum()):,} 点；另有重复 >2 mm 法向偏差 {int(large.sum()):,} 点。', font=font(18), fill='#edf3fa')
    draw.text((12, 497), '橙色不等于正确：也可能无法可靠拟合局部平面；同源平面不是物理真值。', font=font(16), fill='#adbed1'); picture.save(out / 'comparison.png')
    lines = ['# 沿视线的深度差，不等于垂直表面的距离', '',
        '对每个被投影点周围的 3×3 有效深度反投影成局部点云，拟合平面，再计算候选点到平面的有符号距离。平面法向朝向相机。要求至少 6 点、在两个方向展开、平面 RMS 至多 0.2 mm。未满足条件的平面明确留作未评估。', '',
        f'同一批 {n:,} 个联合表面样本中，原有 {int(old.sum()):,} 个重复轴向自由空间冲突点；其中 {int(large.sum()):,} 个还在同一来源至少三个合格局部平面上表现为超过 2 mm 的正法向距离。', '',
        '![局部平面距离](comparison.png)', '',
        '| 来源 | 原 2 mm 轴向重复冲突 | 还具有重复 >2 mm 法向距离 |', '| --- | ---: | ---: |']
    for row in results:
        lines.append(f"| {row['scan_id'].removeprefix('scan_')} | {row['original_axial_repeated_conflict_points_2mm']:,} | {row['repeated_additional_normal_discrepancy_points_2mm']:,} |")
    lines += ['', '## 原轴向冲突观测的局部距离分布', '',
        '| 来源 | ≤0.5 mm | 0.5–1 mm | 1–2 mm | >2 mm | 平面不合格 |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for row in results:
        lines.append('| ' + row['scan_id'].removeprefix('scan_') + ' | ' + ' | '.join(f'{value:,}' for value in row['original_2mm_free_space_observation_plane_bins']) + ' |')
    lines += ['', '这里比较的是不同几何距离，不是把阈值放宽后宣布误差消失。斜面会放大沿视线差；另一方面，局部点到平面距离也不能限制切向滑动，圆柱或平面上配错位置仍可能取得小距离。', '',
        '原单像素冲突、像素邻域结果、无合格平面的情况全部保留，没有修改模型或剔除帧。局部平面和候选同源，不能把统计解释成真实精度。', '',
        '[三维审阅](review.html) · [每工程与逐帧分布](summary.json) · [像素邻域检查](../pixel-sensitivity/README.md)']
    (out / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(dict(original=int(old.sum()), additional_normal_discrepancy=int(large.sum()), results=results)), flush=True)


if __name__ == '__main__':
    main()

"""Check whether joint-surface depth conflicts depend on one raster pixel."""

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
from reconstruction_probe.depth_footprint import project_depth_footprints
from reconstruction_probe.multi_scan import bound_evidence_path
from reconstruction_probe.offline import file_sha256


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--fusion', type=Path, required=True)
    parser.add_argument('--evidence',type=Path,help='Separate evidence directory; defaults to FUSION/depth-evidence')
    parser.add_argument('--out', type=Path, required=True); args = parser.parse_args(); fusion = args.fusion.resolve(); out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('Use a new/empty output directory')
    out.mkdir(parents=True, exist_ok=True); metadata = read(fusion / 'summary.json')
    evidence_path=bound_evidence_path(fusion,args.evidence if args.evidence is not None else fusion/'depth-evidence')
    with np.load(evidence_path, allow_pickle=False) as saved:
        xyz = saved['xyz_shared_mm'].copy(); original_ids = saved['source_point_indices'].copy(); expected = saved['conflict_counts'].copy()
    n = len(xyz); center = np.zeros((2, 2, n), np.uint16); unanimous = center.copy(); mixed = center.copy(); sparse = center.copy(); neighbor_near = center.copy()
    per_view = []; sources = metadata['results'][-1]['source_contributions']
    for source_index, source in enumerate(sources):
        decoded = Path(source['decoded_directory']); index = read(decoded / 'index.json'); transform = np.array(source['source_to_shared_mm'])
        for ordinal, frame in enumerate(index['frames']):
            folder = decoded / f"frame_{frame['id']:010d}"
            with np.load(folder / 'frame.npz', allow_pickle=False) as saved:
                depth = saved['depth_mm']
            depth, _ = clean_depth_edges(depth, 3.); pose = transform @ np.load(folder / 'pose_optimized.npy', allow_pickle=False)
            projected = project_depth_footprints(xyz, pose, depth, index['intrinsics']['Pl'], source['optical_axes'])
            ids = projected.point_indices; rows = []
            for j, tolerance in enumerate([2., 4.]):
                is_free = projected.center_delta_mm > tolerance; enough = projected.valid_neighbors >= 5
                stable = is_free & enough & (projected.minimum_delta_mm > tolerance)
                sensitive = is_free & enough & (projected.minimum_delta_mm <= tolerance)
                few = is_free & ~enough; near = sensitive & (projected.minimum_absolute_delta_mm <= tolerance)
                for array, mask in [(center, is_free), (unanimous, stable), (mixed, sensitive), (sparse, few), (neighbor_near, near)]:
                    array[source_index, j, ids[mask]] += 1
                rows.append(dict(tolerance_mm=tolerance, center_conflicts=int(is_free.sum()), unanimous_valid_neighborhood=int(stable.sum()),
                    neighborhood_disagrees=int(sensitive.sum()), too_few_valid_neighbors=int(few.sum()), nearby_depth_within_tolerance=int(near.sum())))
            per_view.append(dict(scan_id=source['scan_id'], frame_id=frame['id'], thresholds=rows))
            if ordinal % 80 == 0 or ordinal + 1 == len(index['frames']):
                print(f"pixel sensitivity {source['scan_id']} {ordinal + 1}/{len(index['frames'])}", flush=True)
    if not np.array_equal(center, expected) or not np.array_equal(center, unanimous + mixed + sparse):
        raise ValueError('Original conflict accounting changed')
    np.savez_compressed(out / 'pixel-sensitivity.npz', xyz_shared_mm=xyz, source_point_indices=original_ids, center_conflict_counts=center,
        unanimous_neighborhood_conflict_counts=unanimous, mixed_neighborhood_counts=mixed, sparse_neighborhood_counts=sparse,
        near_depth_neighbor_counts=neighbor_near)
    results = []
    for source_index, source in enumerate(sources):
        thresholds = []
        for j, tolerance in enumerate([2., 4.]):
            original = center[source_index, j] >= 3; stable = unanimous[source_index, j] >= 3
            thresholds.append(dict(tolerance_mm=tolerance, repeated_center_conflict_points=int(original.sum()),
                repeated_unanimous_neighbor_conflict_points=int(stable.sum()),
                center_repeated_but_not_neighbor_unanimous=int((original & ~stable).sum()),
                center_conflict_observations=int(center[source_index, j].sum()), unanimous_observations=int(unanimous[source_index, j].sum()),
                mixed_neighborhood_observations=int(mixed[source_index, j].sum()), sparse_neighborhood_observations=int(sparse[source_index, j].sum())))
        results.append(dict(scan_id=source['scan_id'], thresholds=thresholds))
    old_any = (center[:, 0] >= 3).any(0); new_any = (unanimous[:, 0] >= 3).any(0)
    summary = dict(status='pixel_footprint_sensitivity_not_a_confidence_filter', sample_count=n, radius_pixels=1, minimum_valid_neighbors=5,
        repeated_center_conflict_samples=int(old_any.sum()), repeated_unanimous_neighbor_conflict_samples=int(new_any.sum()),
        results=results, frames=per_view, input_sha256={str(p):file_sha256(p) for p in [fusion / 'summary.json', evidence_path]},
        limitations=['Neighboring pixels correspond to distinct rays. Agreement with one of them is not proof that the original surface point is correct.',
          'A 3x3 neighborhood has an angle- and range-dependent physical footprint; no calibrated sensor uncertainty is inferred.',
          'The original single-pixel conflict counts are preserved. This diagnostic neither deletes measurements nor changes the reconstruction.',
          'Counts remaining after the unanimous-neighbor condition can still arise from pose, depth or model errors and need further review.'])
    write_json(out / 'summary.json', summary)
    actual = o3d.io.read_point_cloud(str(fusion / 'joint_raw_depth/tsdf_pointcloud_mm.ply')); colors = np.asarray(actual.colors)[original_ids]
    painted = np.tile(np.array([.40, .49, .59]), (n, 1)); painted[old_any & ~new_any] = [239/255, 164/255, 82/255]; painted[new_any] = [192/255, 106/255, 220/255]
    clouds = []
    for label, rgb, name in [('实际 RGB', colors, 'physical-rgb-mm.ply'), ('原冲突与邻域检查', painted, 'neighborhood-sensitivity-mm.ply')]:
        cloud = o3d.geometry.PointCloud(); cloud.points = o3d.utility.Vector3dVector(xyz); cloud.colors = o3d.utility.Vector3dVector(rgb)
        path = out / name; o3d.io.write_point_cloud(str(path), cloud); clouds.append((label, cloud, path))
    command = [sys.executable, 'scripts/build_reconstruction_review.py', '--unit', 'mm', '--up-axis', 'x', '--invert-up', '--max-points', str(n), '--out', str(out / 'review.html'), '--notes', '紫=同一来源至少3视图在3×3有效邻域全部仍落后于预测点；橙=原单像素重复冲突未满足这一邻域条件；灰=其余。邻域射线不同，不是正确/错误或置信度分类。']
    for label, _, path in clouds:
        command += ['--cloud', label + '=' + str(path)]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    picture = Image.new('RGB', (1000, 520), (24, 33, 47)); draw = ImageDraw.Draw(picture); bounds = (xyz.min(0), xyz.max(0))
    for i, (label, cloud, _) in enumerate(clouds):
        draw.text((i*500+12, 10), label, font=font(20), fill='#edf3fa'); picture.paste(render(cloud, (490, 390), yaw=1.2, pitch=.15, bounds=bounds, gain=1.8 if i == 0 else 1.), (i*500+5, 45))
    draw.text((12, 460), f'原重复冲突 {int(old_any.sum()):,} 点；有效邻域仍一致冲突 {int(new_any.sum()):,} 点。', font=font(18), fill='#edf3fa')
    draw.text((12, 492), '邻域条件是敏感性检查，不代表橙色点已证明正确；原数据和模型未改动。', font=font(16), fill='#adbed1'); picture.save(out / 'comparison.png')
    lines = ['# 深度冲突对像素邻域的敏感性', '',
        '同一个三维点投影到一格深度像素后，小的像素偏移在斜面、杯口或薄壁附近可能改变所见表面。这里保留原单像素检查，再查看周围 3×3 中至少 5 个有效像素是否全部仍显示自由空间冲突。', '',
        f'{n:,} 个原联合表面样本中，原重复冲突 {int(old_any.sum()):,} 个；加入上述邻域条件后仍有至少三视图一致冲突的 {int(new_any.sum()):,} 个。', '',
        '![原色与邻域敏感区域](comparison.png)', '',
        '| 来源 | 容差 mm | 原重复冲突点 | 至少三次有效邻域全部冲突 |', '| --- | ---: | ---: | ---: |']
    for row in results:
        for threshold in row['thresholds']:
            lines.append(f"| {row['scan_id'].removeprefix('scan_')} | {threshold['tolerance_mm']} | {threshold['repeated_center_conflict_points']:,} | {threshold['repeated_unanimous_neighbor_conflict_points']:,} |")
    lines += ['', '邻域里的像素对应不同射线，因此这不是放宽容差后证明点正确，也不是新的置信度。原单像素冲突数、邻域分歧、有效像素不足分别保存，没有删除任何帧或改动融合结果。', '',
        '[三维敏感性审阅](review.html) · [逐工程、阈值和每帧计数](summary.json)']
    (out / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(dict(original=int(old_any.sum()), unanimous_neighbors=int(new_any.sum()), per_source=results)), flush=True)


if __name__ == '__main__':
    main()

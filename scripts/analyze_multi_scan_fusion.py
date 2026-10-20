"""Preserve per-project depth support and conflicts on multi-scan candidates."""

import os
os.environ.setdefault('OMP_NUM_THREADS', '4')

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
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.visibility import project_depth_observations


LABELS = ['both_projects_support', 'target_only_support', 'source_only_support', 'insufficient_support']
COLORS = np.array([[85, 200, 126], [85, 156, 235], [239, 164, 82], [134, 145, 162], [192, 106, 220]], float) / 255


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def distribution(values):
    return dict(count=len(values), median_mm=float(np.median(values)), p90_mm=float(np.percentile(values, 90)),
        within_1mm=int((values <= 1).sum()), within_2mm=int((values <= 2).sum()), farther_than_2mm=int((values > 2).sum()))


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--fusion', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True); parser.add_argument('--max-points', type=int, default=40000)
    args = parser.parse_args(); fusion = args.fusion.resolve(); out = args.out.resolve()
    if not 100 <= args.max_points <= 100000 or (out.exists() and any(out.iterdir())):
        parser.error('Use 100..100000 samples and a new/empty output directory')
    report = read(fusion / 'summary.json'); sources = report['results'][-1]['source_contributions']
    out.mkdir(parents=True, exist_ok=True); results = []; cloud_rows = []; frame_ids = []; source_ids = []; cameras = []
    all_clouds = {r['label']:o3d.io.read_point_cloud(str(fusion / r['label'] / 'tsdf_pointcloud_mm.ply')) for r in report['results']}
    source_views = []
    for source_index, source in enumerate(sources):
        decoded = Path(source['decoded_directory']); index = read(decoded / 'index.json'); transform = np.array(source['source_to_shared_mm'])
        for ordinal, frame in enumerate(index['frames']):
            pose = transform @ np.load(decoded / f"frame_{frame['id']:010d}" / 'pose_optimized.npy', allow_pickle=False)
            source_views.append((source_index, decoded, index, frame, pose, source['optical_axes']))
            frame_ids.append(frame['id']); source_ids.append(source_index); cameras.append(pose[:3, 3])
    for label, cloud in all_clouds.items():
        points = np.asarray(cloud.points); chosen = np.linspace(0, len(points)-1, min(args.max_points, len(points)), dtype=np.int64)
        xyz = points[chosen]; n = len(xyz); counts = [np.zeros((2, 2, n), np.uint16) for _ in range(3)]
        support, conflict, occluded = counts; observed = np.zeros((2, n), np.uint16); flags = np.zeros((len(source_views), n), bool)
        for view_index, (source_index, decoded, index, frame, pose, axes) in enumerate(source_views):
            with np.load(decoded / f"frame_{frame['id']:010d}" / 'frame.npz', allow_pickle=False) as saved:
                depth = saved['depth_mm']
            depth, _ = clean_depth_edges(depth, 3.)
            evidence = project_depth_observations(xyz, pose, depth, index['intrinsics']['Pl'], axes)
            ids, delta = evidence.point_indices, evidence.signed_delta_mm; observed[source_index, ids] += 1
            for tolerance_index, tolerance in enumerate([2., 4.]):
                support[source_index, tolerance_index, ids[np.abs(delta) <= tolerance]] += 1
                conflict[source_index, tolerance_index, ids[delta > tolerance]] += 1
                occluded[source_index, tolerance_index, ids[delta < -tolerance]] += 1
            flags[view_index, ids[np.abs(delta) <= 2.]] = True
            if view_index % 100 == 0 or view_index + 1 == len(source_views):
                print(f'{label}: depth evidence {view_index + 1}/{len(source_views)}', flush=True)
        supported = support[:, 0] >= 2; categories = np.full(n, 3, np.uint8)
        categories[supported[0] & supported[1]] = 0; categories[supported[0] & ~supported[1]] = 1; categories[supported[1] & ~supported[0]] = 2
        conflicts = (conflict[:, 0] >= 3).any(axis=0); display = categories.copy(); display[conflicts] = 4
        np.savez_compressed(out / (label + '-evidence.npz'), source_point_indices=chosen, xyz_shared_mm=xyz,
            source_scan_ids=np.array([s['scan_id'] for s in sources]), frame_scan_indices=np.array(source_ids, np.uint8),
            frame_ids=np.array(frame_ids, np.int64), camera_centers_mm=np.array(cameras), support_counts=support,
            conflict_counts=conflict, occluded_counts=occluded, observed_counts=observed, categories=categories,
            repeated_conflict_mask=conflicts, support_view_bits=np.packbits(flags.T, axis=1, bitorder='little'))
        painted = o3d.geometry.PointCloud(); painted.points = o3d.utility.Vector3dVector(xyz); painted.colors = o3d.utility.Vector3dVector(COLORS[display])
        path = out / (label + '-source-evidence-mm.ply'); o3d.io.write_point_cloud(str(path), painted)
        cloud_rows.append((label, path, painted))
        results.append(dict(label=label, sample_count=n, category_counts={name:int((categories == i).sum()) for i, name in enumerate(LABELS)},
            repeated_conflict_samples=int(conflicts.sum()), both_supported_and_conflicting=int(((categories == 0) & conflicts).sum()),
            source_statistics=[dict(scan_id=sources[i]['scan_id'], supported_at_least_two_views_2mm=int(supported[i].sum()),
                conflict_in_at_least_three_views_2mm=int((conflict[i, 0] >= 3).sum()),
                supported_at_least_two_views_4mm=int((support[i, 1] >= 2).sum()),
                conflict_in_at_least_three_views_4mm=int((conflict[i, 1] >= 3).sum())) for i in range(2)]))
    distances = []; joint = all_clouds['joint_raw_depth']
    for label in ['target_only', 'source_only_registered']:
        single = all_clouds[label]
        distances.append(dict(single_label=label, single_to_joint=distribution(np.asarray(single.compute_point_cloud_distance(joint))),
            joint_to_single=distribution(np.asarray(joint.compute_point_cloud_distance(single)))))
    summary = dict(status='internal_per_project_depth_evidence_not_independent_accuracy', surface_results=results,
        surface_retention_distances=distances, source_scan_ids=[s['scan_id'] for s in sources],
        thresholds=dict(support_tolerance_mm=[2., 4.], minimum_supporting_views=2, minimum_conflicting_views=3),
        input_sha256={str(p):file_sha256(p) for p in [fusion / 'summary.json', *[fusion / label / 'tsdf_pointcloud_mm.ply' for label in all_clouds]]},
        limitations=['All evaluated depths contributed to these reconstructions or the frozen registration; this is not independent validation.',
          'Each model has a different sampled surface. Fractions between models are descriptive, not paired point accuracy.',
          'A point may be supported by both projects and still conflict with other views; these states are kept separately.',
          'Not supported is not a geometric error; viewpoints may be occluded or lack saved depth.',
          'Single-to-joint distances measure representation changes, not the truth of the removed/added geometry.'])
    write_json(out / 'summary.json', summary)
    command = [sys.executable, 'scripts/build_reconstruction_review.py', '--unit', 'mm', '--up-axis', 'x', '--invert-up', '--max-points', str(args.max_points), '--out', str(out / 'review.html'), '--notes', '绿=两工程各至少2次深度支持；蓝=仅第一份支持；橙=仅第二份；灰=支持不足；紫=任一工程至少3次自由空间冲突。紫色优先显示，底层同时保留支持状态。内部诊断，不是独立精度。']
    for label, path, _ in cloud_rows:
        command += ['--cloud', label + '=' + str(path)]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    bounds = (np.min([pc.get_min_bound() for _, _, pc in cloud_rows], axis=0), np.max([pc.get_max_bound() for _, _, pc in cloud_rows], axis=0))
    picture = Image.new('RGB', (1500, 560), (24, 33, 47)); draw = ImageDraw.Draw(picture)
    for i, ((label, _, pc), row) in enumerate(zip(cloud_rows, results)):
        draw.text((i*500+12, 10), label, font=font(19), fill='#edf3fa'); picture.paste(render(pc, (490, 390), yaw=1.2, pitch=.15, bounds=bounds, gain=1.), (i*500+5, 45))
        draw.text((i*500+12, 450), f"双方支持 {row['category_counts'][LABELS[0]]/row['sample_count']:.1%}", font=font(18), fill='#edf3fa')
        draw.text((i*500+12, 480), f"重复冲突 {row['repeated_conflict_samples']/row['sample_count']:.1%}", font=font(18), fill='#adbed1')
    draw.text((12, 525), '绿双方 · 蓝第一份 · 橙第二份 · 灰不足 · 紫冲突；不同模型抽样，不能当逐点精度排名。', font=font(16), fill='#adbed1'); picture.save(out / 'comparison.png')
    print(json.dumps(dict(surface_results=results, surface_retention_distances=distances)), flush=True)


if __name__ == '__main__':
    main()

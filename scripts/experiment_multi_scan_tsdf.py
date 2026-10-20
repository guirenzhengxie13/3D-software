"""Fuse a frozen two-project registration from original saved depth frames.

Three arms use identical camera calibrations and depth preprocessing: target
alone, registered source alone and both projects together. No vendor mesh or
per-project fused cloud is integrated into the volume.
"""

import os
os.environ.setdefault('OMP_NUM_THREADS', '4')

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import open3d as o3d
from PIL import Image, ImageDraw

from build_attribute_study_report import font, render
from reconstruct_scans import clean_depth_edges, optical_to_pose_axes, write_geometry, write_json
from reconstruction_probe.multi_scan import FrameKey, registered_camera_to_object_m, rigid, scaled_intrinsics
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.tensor_tsdf import TensorTSDFVolume


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def integrate_arm(label, sources, destination):
    destination.mkdir(parents=True, exist_ok=False)
    started = time.time()
    volume = TensorTSDFVolume(.0006, .0024, weight_threshold=3.)
    records = []; contributions = []; seen = set()
    for source in sources:
        decoded = source['decoded']; index = source['index']; scan_id = index['scan_id']
        depth_hash = hashlib.sha256(); pose_hash = hashlib.sha256(); color_hash = hashlib.sha256()
        raw_points = 0; edge_points = 0
        for ordinal, frame in enumerate(index['frames']):
            key = FrameKey(scan_id, frame['id'])
            if key in seen:
                raise ValueError('Repeated compound frame identity')
            seen.add(key)
            folder = decoded / f'frame_{key.frame_id:010d}'
            pose = rigid(np.load(folder / 'pose_optimized.npy', allow_pickle=False))
            camera = registered_camera_to_object_m(source['transform'], pose, optical_to_pose_axes(index))
            with np.load(folder / 'frame.npz', allow_pickle=False) as saved:
                depth = saved['depth_mm']; rgba = saved['rgba']
                if int(saved['color_layout_version']) != 2:
                    raise ValueError('Expected physically verified color convention version 2')
                valid = depth > 0
                if rgba.shape != (int(valid.sum()), 4):
                    raise ValueError('Depth/RGBA correspondence mismatch')
                color = np.full((*depth.shape, 3), 165, np.uint8); color[valid] = rgba[:, :3]
                raw_points += int(valid.sum())
                selected, removed = clean_depth_edges(depth, 3.); edge_points += removed
                height, width = depth.shape
                K = scaled_intrinsics(index['intrinsics']['Pl'], width, height)
                if K[0, 1] != 0 or K[1, 0] != 0:
                    raise ValueError('This Open3D adapter requires zero-skew calibration')
                intrinsic = o3d.camera.PinholeCameraIntrinsic(width, height, K[0, 0], K[1, 1], K[0, 2], K[1, 2])
                rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
                    o3d.geometry.Image(color), o3d.geometry.Image(selected.astype(np.float32)),
                    depth_scale=1000., depth_trunc=2., convert_rgb_to_intensity=False)
                volume.integrate(rgbd, intrinsic, np.linalg.inv(camera))
                # IDs remain part of each digest; equal raster bytes in another
                # project do not establish the same physical measurement.
                encoded_id = np.array([key.frame_id], '<u8').tobytes()
                depth_hash.update(encoded_id + selected.astype('<f4').tobytes())
                color_hash.update(encoded_id + color.tobytes())
                pose_hash.update(encoded_id + camera.astype('<f8').tobytes())
                records.append(dict(scan_id=scan_id, frame_id=key.frame_id, record_ordinal=ordinal,
                    valid_pixels_before_edges=int(valid.sum()), edge_pixels_omitted=removed,
                    integrated_valid_pixels=int((selected > 0).sum()), pose_source='table_pose_optimized',
                    capture_timestamp=None))
            if ordinal % 64 == 0 or ordinal + 1 == len(index['frames']):
                print(f'{label}: {scan_id} {ordinal + 1}/{len(index["frames"])}', flush=True)
        contributions.append(dict(scan_id=scan_id, decoded_directory=str(decoded),
            index_sha256=file_sha256(decoded / 'index.json'), frame_count=len(index['frames']),
            source_to_shared_mm=source['transform'].tolist(), intrinsics=index['intrinsics']['Pl'],
            optical_axes=optical_to_pose_axes(index).tolist(), raw_valid_pixels=raw_points,
            edge_pixels_omitted=edge_points, ordered_selected_depth_sha256=depth_hash.hexdigest(),
            ordered_physical_rgb_sha256=color_hash.hexdigest(), ordered_camera_pose_m_sha256=pose_hash.hexdigest()))
    points = volume.extract_point_cloud(); mesh = volume.extract_triangle_mesh()
    mesh.remove_duplicated_vertices(); mesh.remove_duplicated_triangles(); mesh.remove_degenerate_triangles(); mesh.remove_unreferenced_vertices(); mesh.compute_vertex_normals()
    if points.is_empty() or len(mesh.triangles) == 0:
        raise ValueError('No supported surface')
    coordinate_frame = 'frozen_reference_' + sources[0]['shared_id']
    write_geometry(destination / 'tsdf_pointcloud_mm.ply', points, coordinate_frame)
    write_geometry(destination / 'tsdf_mesh_mm.ply', mesh, coordinate_frame)
    obj = o3d.geometry.TriangleMesh(mesh); obj.scale(1000, center=(0, 0, 0))
    o3d.io.write_triangle_mesh(str(destination / 'tsdf_mesh_mm.obj'), obj, write_vertex_colors=False, write_triangle_uvs=False)
    _, counts, _ = mesh.cluster_connected_triangles(); counts = np.asarray(counts)
    quality = dict(point_count=len(points.points), mesh_vertices=len(mesh.vertices), mesh_triangles=len(mesh.triangles),
        components=len(counts), largest_component_triangle_fraction=float(counts.max() / counts.sum()),
        watertight=mesh.is_watertight(), bounds_min_mm=(points.get_min_bound() * 1000).tolist(), bounds_max_mm=(points.get_max_bound() * 1000).tolist())
    with (destination / 'frame-contributions.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
    report = dict(label=label, algorithm='Open3D CPU VoxelBlockGrid TSDF from compound saved-depth frames',
        status='exploratory_frozen_registration_not_promoted', unit='mm', coordinate_frame=coordinate_frame,
        voxel_mm=.6, truncation_mm=2.4, edge_threshold_mm=3., extraction_weight_threshold=3., depth_truncation_mm=2000.,
        integrated_frames=len(records), source_contributions=contributions, tensor_diagnostics=volume.diagnostics(),
        quality=quality, elapsed_seconds=time.time() - started,
        input_sha256={str(s['decoded'] / 'index.json'):file_sha256(s['decoded'] / 'index.json') for s in sources},
        output_sha256={name:file_sha256(destination / name) for name in ['tsdf_pointcloud_mm.ply', 'tsdf_mesh_mm.ply', 'tsdf_mesh_mm.obj', 'frame-contributions.csv']})
    write_json(destination / 'fusion-report.json', report)
    print(json.dumps(dict(label=label, frames=len(records), quality=quality, seconds=report['elapsed_seconds'])), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True); parser.add_argument('--registration', type=Path, required=True)
    parser.add_argument('--source-id', default='scan_20261018131127'); parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); study = args.study.resolve(); out = args.out.resolve(); registration = args.registration.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('Use a new/empty output directory')
    registered = read(registration); source_row = next(row for row in registered['registrations'] if row['scan_id'] == args.source_id)
    target_id = source_row['reference_scan_id']; source_id = source_row['scan_id']
    if source_id == target_id or source_row['unit'] != 'mm':
        parser.error('Expected distinct scan projects and a registration in mm')
    sources = []
    for scan_id, transform in [(target_id, np.eye(4)), (source_id, rigid(source_row['transform_source_scan_to_reference_scan']))]:
        decoded = study / 'decoded' / scan_id; index = read(decoded / 'index.json')
        original = Path(index['source_directory']).resolve()
        if original == out or original in out.parents:
            parser.error('Outputs must stay outside original scan projects')
        if index.get('color_layout_version') != 2:
            parser.error('Re-run physical color normalization first')
        sources.append(dict(decoded=decoded, index=index, transform=transform, shared_id=target_id))
    out.mkdir(parents=True, exist_ok=True)
    results = [integrate_arm(label, chosen, out / label) for label, chosen in
        [('target_only', sources[:1]), ('source_only_registered', sources[1:]), ('joint_raw_depth', sources)]]
    joint_by_scan = {s['scan_id']:s for s in results[-1]['source_contributions']}
    same = all(row['source_contributions'][0] == joint_by_scan[row['source_contributions'][0]['scan_id']] for row in results[:2])
    if not same:
        raise ValueError('Single and joint arms did not integrate the exact same source contributions')
    inputs = [registration, *[s['decoded'] / 'index.json' for s in sources], Path(source_row['source_path']), Path(source_row['reference_path'])]
    summary = dict(status='exploratory_multi_project_raw_depth_fusion_not_promoted',
        reference_scan_id=target_id, source_scan_id=source_id, same_per_source_pixels_color_and_poses=same,
        registration_was_frozen_before_this_experiment=True, original_registration_passed=source_row['accepted_for_experimental_combination'],
        original_registration_checks=source_row['checks'], results=results,
        input_sha256={str(p):file_sha256(p) for p in inputs},
        limitations=['The frozen registration was fitted using prior full-data surfaces; this is not held-out validation.',
          'The projects look like the same green cup but physical object identity is not independently confirmed.',
          'The original full-overlap registration gate failed. These outputs remain reviewable candidates, not a promoted reconstruction.',
          'More reconstructed points, greater support and higher connectivity do not certify physical accuracy.',
          'Saved optimized poses remain fixed within each project; no trajectory correction or hole hallucination is performed.',
          'Each saved frame is identified by (scan_id, frame_id). Record order is not a physical timestamp.',
          'Sparse TSDF uses a fixed shared 0.6 mm world lattice and 2.4 mm truncation; outputs are in mm.'])
    write_json(out / 'summary.json', summary)
    clouds = [(r['label'], o3d.io.read_point_cloud(str(out / r['label'] / 'tsdf_pointcloud_mm.ply'))) for r in results]
    command = [sys.executable, 'scripts/build_reconstruction_review.py', '--unit', 'mm', '--up-axis', 'x', '--invert-up', '--allow-overlay', '--max-points', '40000', '--out', str(out / 'review.html'), '--notes', '两份工程真实原始深度联合 TSDF；各自单独与联合使用同一输入像素、颜色和冻结位姿。工程间变换尚未通过原先完整重叠门槛，结果只作探索，不是精度证明。']
    for label, _ in clouds:
        command += ['--cloud', label + '=' + str(out / label / 'tsdf_pointcloud_mm.ply')]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    bounds = (np.min([pc.get_min_bound() for _, pc in clouds], axis=0), np.max([pc.get_max_bound() for _, pc in clouds], axis=0))
    picture = Image.new('RGB', (1500, 950), (24, 33, 47)); draw = ImageDraw.Draw(picture)
    for i, ((label, pc), row) in enumerate(zip(clouds, results)):
        draw.text((i*500+12, 12), label, font=font(20), fill='#edf3fa')
        for j, (yaw, pitch) in enumerate([(1.2, .15), (3.8, .6)]):
            picture.paste(render(pc, (490, 360), yaw=yaw, pitch=pitch, bounds=bounds, gain=1.8), (i*500+5, 48+j*380))
        draw.text((i*500+12, 830), f"{row['integrated_frames']} 帧 · {row['quality']['point_count']:,} 点", font=font(18), fill='#edf3fa')
        draw.text((i*500+12, 865), f"主连通面 {row['quality']['largest_component_triangle_fraction']:.1%}", font=font(17), fill='#adbed1')
    draw.text((12, 913), '相同固定体素与边缘处理；联合结果仍是待审阅候选。上下两排为不同观察方向。', font=font(17), fill='#adbed1')
    picture.save(out / 'comparison.png')
    print(json.dumps(dict(status=summary['status'], same_per_source_inputs=same, frames=results[-1]['integrated_frames'])), flush=True)


if __name__ == '__main__':
    main()

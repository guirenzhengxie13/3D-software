"""Trace one joint-fusion surface point to compound source-frame pixels."""

import argparse
import json
from pathlib import Path

import numpy as np
import open3d as o3d
from PIL import Image, ImageDraw

from build_attribute_study_report import font
from reconstruct_scans import clean_depth_edges, write_json
from reconstruction_probe.depth_footprint import project_depth_footprints
from reconstruction_probe.multi_scan import bound_evidence_path
from reconstruction_probe.offline import file_sha256


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--fusion', type=Path, required=True)
    parser.add_argument('--evidence',type=Path,help='Separate evidence directory; defaults to FUSION/depth-evidence')
    parser.add_argument('--out', type=Path, required=True)
    choice = parser.add_mutually_exclusive_group(required=True); choice.add_argument('--sample-index', type=int)
    choice.add_argument('--category', choices=['both_support', 'target_only', 'source_only', 'repeated_conflict', 'unanimous_neighbor_conflict'])
    args = parser.parse_args(); fusion = args.fusion.resolve(); out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('Use a new/empty output directory')
    evidence_root=args.evidence.resolve() if args.evidence is not None else fusion/'depth-evidence'
    evidence_path = bound_evidence_path(fusion,evidence_root)
    with np.load(evidence_path, allow_pickle=False) as saved:
        xyz_all = saved['xyz_shared_mm'].copy(); original_ids = saved['source_point_indices'].copy()
        categories = saved['categories'].copy(); repeated = saved['repeated_conflict_mask'].copy()
    sample = args.sample_index; selection = 'explicit_sample_index'; additional_inputs=[]
    if args.category is not None:
        category_id = dict(both_support=0, target_only=1, source_only=2)
        if args.category=='unanimous_neighbor_conflict':
            path=fusion/'pixel-sensitivity/pixel-sensitivity.npz'
            with np.load(path,allow_pickle=False) as data:
                if not np.array_equal(data['xyz_shared_mm'],xyz_all):raise ValueError('Pixel sensitivity uses a different surface sample')
                mask=(data['unanimous_neighborhood_conflict_counts'][:,0]>=3).any(0)
            additional_inputs.append(path)
        else:
            mask = repeated if args.category == 'repeated_conflict' else (categories == category_id[args.category]) & ~repeated
        ids = np.flatnonzero(mask)
        if not len(ids):
            raise ValueError('Requested category has no samples')
        cloud = o3d.geometry.PointCloud(); cloud.points = o3d.utility.Vector3dVector(xyz_all[ids])
        groups = np.array(cloud.cluster_dbscan(eps=3., min_points=8, print_progress=False))
        available = groups[groups >= 0]
        if len(available):
            largest = int(np.argmax(np.bincount(available))); ids = ids[groups == largest]
            selection = f'nearest-to-centroid sample of largest 3 mm DBSCAN cluster in {args.category}'
        else:
            selection = f'nearest-to-centroid sample of all {args.category} samples; no qualifying cluster'
        sample = int(ids[np.argmin(np.linalg.norm(xyz_all[ids] - xyz_all[ids].mean(0), axis=1))])
    if sample is None or not 0 <= sample < len(xyz_all):
        raise ValueError('Sample index outside saved evidence')
    out.mkdir(parents=True, exist_ok=True); xyz = xyz_all[sample]
    summary_path = fusion / 'summary.json'; summary = read(summary_path)
    sources = summary['results'][-1]['source_contributions']; observations = []; source_info = []
    for source_index, source in enumerate(sources):
        decoded = Path(source['decoded_directory']); index = read(decoded / 'index.json'); transform = np.array(source['source_to_shared_mm'])
        source_info.append((decoded, index))
        for frame in index['frames']:
            rid = frame['id']; folder = decoded / f'frame_{rid:010d}'
            with np.load(folder / 'frame.npz', allow_pickle=False) as saved:
                depth = saved['depth_mm']
            depth, _ = clean_depth_edges(depth, 3.)
            camera = transform @ np.load(folder / 'pose_optimized.npy', allow_pickle=False)
            projected = project_depth_footprints(xyz[None, :], camera, depth, index['intrinsics']['Pl'], source['optical_axes'])
            if not len(projected.point_indices):
                continue
            pixel = int(projected.pixel_indices[0]); v, u = divmod(pixel, depth.shape[1]); delta = float(projected.center_delta_mm[0])
            observations.append(dict(scan_id=source['scan_id'], source_index=source_index, frame_id=rid, pixel_index=pixel, u=u, v=v,
                signed_depth_delta_mm=delta, saved_measured_depth_mm=float(depth[v, u]), predicted_depth_mm=float(depth[v, u] - delta),
                valid_neighbors_3x3=int(projected.valid_neighbors[0]),minimum_neighbor_delta_mm=float(projected.minimum_delta_mm[0]),
                maximum_neighbor_delta_mm=float(projected.maximum_delta_mm[0]),closest_neighbor_abs_delta_mm=float(projected.minimum_absolute_delta_mm[0]),
                unanimous_neighbor_free_space_2mm=bool(projected.valid_neighbors[0]>=5 and projected.minimum_delta_mm[0]>2),
                relation='support' if abs(delta) <= 2. else 'free_space_conflict' if delta > 2. else 'occluded'))
    selected = []
    for source_index in range(2):
        rows = [r for r in observations if r['source_index'] == source_index]
        for relation in ['support', 'free_space_conflict', 'occluded']:
            values = sorted([r for r in rows if r['relation'] == relation], key=lambda r:abs(r['signed_depth_delta_mm']))
            if not values:
                continue
            # Supporting example uses closest depth; non-support uses the
            # median observed discrepancy instead of an extreme outlier.
            chosen = values[0] if relation == 'support' else values[len(values)//2]
            selected.append(dict(chosen))
    if not selected:
        raise ValueError('No saved depth observation for this point')
    pictures = []; input_paths = [summary_path, evidence_path,*additional_inputs]
    for row in selected:
        source_index = row['source_index']; decoded, index = source_info[source_index]; folder = decoded / f"frame_{row['frame_id']:010d}"
        path = folder / 'frame.npz'; input_paths += [path, folder / 'pose_optimized.npy']
        with np.load(path, allow_pickle=False) as saved:
            depth = saved['depth_mm']; rgba = saved['rgba']
            if int(saved['color_layout_version']) != 2:
                raise ValueError('Verified physical RGB convention required')
        color = np.zeros((*depth.shape, 3), np.uint8); color[depth > 0] = rgba[:, :3]
        image = Image.fromarray(color); marked = image.copy(); draw = ImageDraw.Draw(marked); u, v = row['u'], row['v']
        draw.ellipse((u-8, v-8, u+8, v+8), outline='#ff6380', width=2)
        draw.line((u-13, v, u+13, v), fill='white'); draw.line((u, v-13, u, v+13), fill='white')
        prefix = row['scan_id'] + '-frame-' + str(row['frame_id']); image_name = prefix + '-aligned-color.png'; crop_name = prefix + '-crop.png'
        marked.save(out / image_name); crop = image.crop((u-40, v-40, u+41, v+41)).resize((162, 162), Image.Resampling.NEAREST)
        ImageDraw.Draw(crop).ellipse((75, 75, 87, 87), outline='#ff6380', width=2); crop.save(out / crop_name)
        card = Image.new('RGB', (420, 615), (24, 33, 47)); draw = ImageDraw.Draw(card)
        draw.text((12, 8), row['scan_id'].removeprefix('scan_') + f" / ID {row['frame_id']}", font=font(17), fill='#edf3fa')
        draw.text((12, 38), f"{row['relation']} · ΔZ {row['signed_depth_delta_mm']:+.3f} mm", font=font(16), fill='#adbed1')
        card.paste(marked.resize((400, 300), Image.Resampling.NEAREST), (10, 75)); card.paste(crop, (12, 400))
        draw.text((188, 405), f'像素 ({u}, {v})', font=font(16), fill='#edf3fa')
        draw.text((188, 438), f"测量 {row['saved_measured_depth_mm']:.2f}", font=font(15), fill='#adbed1')
        draw.text((188, 468), f"预测 {row['predicted_depth_mm']:.2f} mm", font=font(15), fill='#adbed1')
        pictures.append(card); row.update(color_image=image_name, crop_image=crop_name)
    sheet = Image.new('RGB', (420 * len(pictures), 655), (24, 33, 47))
    for i, card in enumerate(pictures):
        sheet.paste(card, (i*420, 0))
    ImageDraw.Draw(sheet).text((12, 622), '同一三维点在不同工程的投影；颜色对齐到深度，缺深度为黑。ΔZ=测量深度−预测深度。', font=font(16), fill='#adbed1'); sheet.save(out / 'evidence.png')
    counts = [{relation:sum(r['source_index'] == i and r['relation'] == relation for r in observations)
        for relation in ['support', 'free_space_conflict', 'occluded']} for i in range(2)]
    report = dict(sample_index=sample, original_joint_point_id=int(original_ids[sample]), xyz_shared_mm=xyz.tolist(),
        selection=selection, category=int(categories[sample]), repeated_conflict=bool(repeated[sample]), source_scan_ids=[s['scan_id'] for s in sources],
        source_observation_counts=counts, displayed_frames=selected, observations=observations,
        input_sha256={str(p):file_sha256(p) for p in input_paths},
        limitations=['This example is selected after viewing the fusion and diagnostic categories; it is not independent validation.',
          'A signed depth discrepancy can arise from pose error, depth error, pixel discretization, thin surfaces or occlusion boundaries; it does not by itself identify the faulty source.',
          'Color images show saved depth-aligned RGBA, not the original full JPEG camera raster.'])
    write_json(out / 'summary.json', report)
    (out / 'README.md').write_text(f"# 联合表面点回查\n\n抽样编号 {sample}，原联合 PLY 顶点 {int(original_ids[sample])}。选择方式：{selection}。每条证据使用工程 ID＋完整帧 ID，避免重复帧号混淆。\n\n![各工程支持、冲突与遮挡](evidence.png)\n\nΔZ＝测量深度−预测深度。绝对值至多 2 mm 为支持；大于 2 mm 表示预测点落在测量表面前的自由空间；小于 −2 mm 表示预测点在测量表面之后、可能被遮挡。\n\n[全部工程/帧/像素与深度数值](summary.json)。这些关系是同源数据的内部检查，不能仅凭一张图认定某工程错误。\n", encoding='utf-8')
    print(json.dumps(dict(sample_index=sample, point_id=int(original_ids[sample]), counts=counts, displayed=len(selected))), flush=True)


if __name__ == '__main__':
    main()

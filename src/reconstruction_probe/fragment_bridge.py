"""Bind verified surface alignment to explicit, immutable saved-frame inputs.

A PLY never establishes frame ownership. The binding is an explicit research
selection in one saved scan coordinate system, not a geometry accuracy claim.
"""

import json
from pathlib import Path
import re

import numpy as np

from .fragment_plan import compile_fragment_plan
from .landmark_sessions import verify_landmark_session
from .multi_scan import FrameKey, rigid, scaled_intrinsics
from .offline import file_sha256
from .ply_layout import map_ply_vertices


def read_json(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object: ' + str(path))
    return value


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('An explicit ' + label + ' is required')
    return value


def checked_digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Expected a lowercase SHA256 content pin')
    return value


def build_fragment_plan(decoded, binding_path, alignment, candidate_label, mapper):
    """Validate actual files and return a canonical two-fragment plan + audit.

    Source and target must both be expressed in the original saved scan mm
    frame. The selected matrix corrects the source into the fixed target. Each
    selected original depth and optimized pose is hashed, not just the index.
    """
    decoded = mapper.resolve(decoded)
    binding_path = mapper.resolve(binding_path)
    alignment = mapper.resolve(alignment)
    binding = read_json(binding_path)
    allowed = {'format_version', 'unit', 'scan_id', 'decoded_index_sha256',
               'alignment_summary_sha256', 'decision', 'source', 'target',
               'selection_roi_original_scan_mm', 'input_sha256'}
    if set(binding) - allowed or type(binding.get('format_version')) is not int or binding['format_version'] != 1 or binding.get('unit') != 'mm':
        raise ValueError('Expected frame binding format_version 1 and unit mm')
    decision = nonempty(binding.get('decision'), 'selection decision')
    pins = {}

    def pin(path, expected=None):
        path = mapper.resolve(path)
        if not path.is_file():
            raise ValueError('Pinned input is missing: ' + str(path))
        digest = file_sha256(path)
        if expected is not None and digest != checked_digest(expected):
            raise ValueError('Pinned input changed: ' + str(path))
        if str(path) in pins and pins[str(path)] != digest:
            raise ValueError('Input changed during validation: ' + str(path))
        pins[str(path)] = digest
        return digest

    pin(binding_path)
    index_path = decoded/'index.json'
    index_sha = pin(index_path, checked_digest(binding.get('decoded_index_sha256')))
    index = read_json(index_path)
    scan_id = nonempty(index.get('scan_id'), 'scan ID')
    if binding.get('scan_id') != scan_id:
        raise ValueError('Binding belongs to another scan')
    available = [FrameKey(scan_id, row['id']).frame_id for row in index['frames']]
    if len(set(available)) != len(available):
        raise ValueError('Index contains duplicate original frame IDs')
    summary_path = alignment/'summary.json'
    alignment_sha = pin(summary_path, checked_digest(binding.get('alignment_summary_sha256')))
    report = read_json(summary_path)
    if report.get('status') != 'reviewable_candidates_not_automatically_promoted':
        raise ValueError('Expected verified alignment output, not a registration guess')
    session_path = alignment/'session-original.json'
    session_sha = pin(session_path)
    session = mapper.record(read_json(session_path))
    reported_pins = report.get('input_sha256')
    if not isinstance(reported_pins, dict) or session_sha not in reported_pins.values():
        raise ValueError('Alignment does not pin its original exported session')
    for name, digest in reported_pins.items():
        pin(name, checked_digest(digest))
    evidence = binding.get('input_sha256', {})
    if not isinstance(evidence, dict):
        raise ValueError('Binding evidence pins must be a mapping')
    for name, digest in evidence.items():
        pin(name, checked_digest(digest))
    models = {}; ownership = {}; selected = set(); points = {}
    for side in ['target', 'source']:
        row = binding.get(side)
        if not isinstance(row, dict) or set(row) != {'path', 'sha256', 'frame_ids', 'coordinate_frame', 'basis'}:
            raise ValueError('Each model binding needs path, sha256, frame_ids, coordinate_frame and basis')
        if row['coordinate_frame'] != 'saved_scan_mm':
            raise ValueError('Model coordinates must be in the original saved scan mm frame')
        nonempty(row['basis'], 'coordinate/frame ownership basis')
        model = mapper.resolve(row['path'])
        sha = pin(model, checked_digest(row['sha256']))
        if mapper.resolve(session[side]['path']) != model or session[side].get('sha256') != sha:
            raise ValueError('Bound model does not match the verified session: ' + side)
        if reported_pins.get(session[side]['path']) != sha:
            # Compare canonical paths while retaining the original report bytes.
            matches = [value for name, value in reported_pins.items() if mapper.resolve(name) == model]
            if matches != [sha]:
                raise ValueError('Alignment does not pin this bound model: ' + side)
        ids = row['frame_ids']
        if not isinstance(ids, list) or not ids:
            raise ValueError('Each model needs explicit nonempty original frame IDs')
        for rid in ids:
            FrameKey(scan_id, rid)
            if rid not in available or rid in selected:
                raise ValueError('Missing or multiply-owned source frame')
            selected.add(rid)
        ownership[side] = sorted(ids)
        records, _ = map_ply_vertices(model)
        points[side] = np.column_stack([records[name] for name in ['x', 'y', 'z']]).astype(float)
        if not len(points[side]) or not np.isfinite(points[side]).all():
            raise ValueError('Bound source model has no finite complete surface')
        del records
        models[side] = dict(path=str(model), sha256=sha, basis=row['basis'])
    if models['source']['path'] == models['target']['path']:
        raise ValueError('Source and target must be distinct bound models')
    validated = verify_landmark_session(session, points['source'], points['target'], models['source']['sha256'], models['target']['sha256'])
    if report.get('landmark_validation', {}).get('kind') != validated['kind']:
        raise ValueError('Alignment validation kind disagrees with its session')
    if validated['kind'] == 'existing_candidate':
        reference = session.get('candidate_reference', {})
        ref_path = mapper.resolve(reference['path'])
        pin(ref_path, checked_digest(reference['sha256']))
        recorded = [row for row in read_json(ref_path)['candidates'] if row['label'] == session.get('candidate_label')]
        if len(recorded) != 1 or not np.allclose(rigid(recorded[0]['transform']), validated['matrix'], rtol=0, atol=1e-10):
            raise ValueError('Existing candidate disagrees with original session')
        base_label = 'selected_' + nonempty(session.get('candidate_label'), 'candidate label')
    else:
        base_label = 'manual_landmarks'
    candidates = report.get('candidates')
    if not isinstance(candidates, list):
        raise ValueError('Alignment has no candidate list')
    chosen = [row for row in candidates if row.get('label') == candidate_label]
    if len(chosen) != 1 or candidate_label not in {base_label, base_label+'_icp'}:
        raise ValueError('Choose exactly one verified alignment candidate')
    transform = rigid(chosen[0]['transform'])
    if candidate_label == base_label and not np.allclose(transform, validated['matrix'], rtol=0, atol=1e-10):
        raise ValueError('Chosen transform disagrees with verified original-point fit')
    roi = binding.get('selection_roi_original_scan_mm')
    if roi is not None:
        bounds = np.asarray(roi, float)
        if bounds.shape != (2, 3) or not np.isfinite(bounds).all() or np.any(bounds[1] <= bounds[0]):
            raise ValueError('Expected ordered original-scan ROI bounds')
    valid_observations = 0
    for rid in sorted(selected):
        folder = decoded/f'frame_{rid:010d}'
        depth_path = folder/'frame.npz'; pose_path = folder/'pose_optimized.npy'
        depth_sha = pin(depth_path); pose_sha = pin(pose_path)
        with np.load(depth_path, allow_pickle=False) as frame:
            depth = frame['depth_mm']
            if depth.ndim != 2 or min(depth.shape) <= 0 or depth.dtype.kind not in 'fu' or not np.isfinite(depth).all() or np.any(depth < 0) or not np.any(depth > 0):
                raise ValueError('Selected frame has invalid saved metric depth')
            scaled_intrinsics(index['intrinsics']['Pl'], depth.shape[1], depth.shape[0])
            count = int((depth > 0).sum()); valid_observations += count
            if 'rgba' in frame and (frame['rgba'].shape != (count, 4) or frame['rgba'].dtype != np.uint8):
                raise ValueError('Saved color rows do not match valid depth pixels')
        rigid(np.load(pose_path, allow_pickle=False))
        pin(depth_path, depth_sha); pin(pose_path, pose_sha)
    plan = dict(format_version=1, unit='mm', scan_id=scan_id, decoded_index_sha256=index_sha,
        decision=decision, fragments=[
            dict(fragment_id=0, parent_fragment_id=None, frame_ids=ownership['target'], transform_to_parent_mm=np.eye(4).tolist()),
            dict(fragment_id=1, parent_fragment_id=0, frame_ids=ownership['source'], transform_to_parent_mm=transform.tolist())],
        input_sha256=pins,
        bridge_provenance=dict(alignment_summary_sha256=alignment_sha, candidate_label=candidate_label,
            source=models['source'], target=models['target'], coordinate_frame='saved_scan_mm',
            frame_policy='explicit_original_frame_ids_optimized_poses',
            selection_policy='ROI is evaluated before pose correction; each selected frame is integrated once'))
    if roi is not None:
        plan['selection_roi_original_scan_mm'] = roi
    compiled = compile_fragment_plan(plan, scan_id, index_sha, available)
    return plan, dict(status='validated_frame_binding_plan_not_geometry_accuracy', scan_id=scan_id,
        selected_frames=len(compiled['selected_frame_ids']), source_frames=len(ownership['source']),
        target_frames=len(ownership['target']), unselected_frames=len(available)-len(selected),
        valid_saved_depth_observations_before_roi=valid_observations, pinned_files=len(pins),
        candidate_label=candidate_label, landmark_kind=validated['kind'],
        limitations=['Frame ownership and saved-coordinate basis are explicit assertions, not inferred from PLY geometry.',
            'Selected models may have been fitted on training subsets; all selected frames now enter a demonstration, not heldout evaluation.',
            'Single saved scan only. General multi-project binding requires an additional source-to-object coordinate contract.',
            'A validated plan is not a completed fusion or a proof of improved physical accuracy.'])

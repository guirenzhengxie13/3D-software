"""Deterministic offline tools and recorded execution, without a model service.

Tools run as argument vectors from a fixed registry. Every operation writes
to its own new directory; dependency outputs are hashed and checked before
reuse. Cancellation currently takes effect between operations.
"""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
import time

from .offline import file_sha256


TOOLS = {
    'multi_scan.fuse': ('experiment_multi_scan_tsdf.py', {
        'study': ('--study', 'directory', True), 'registration': ('--registration', 'file', True),
        'source_id': ('--source-id', 'token', False)}),
    'multi_scan.evidence': ('analyze_multi_scan_fusion.py', {
        'fusion': ('--fusion', 'directory', True), 'max_points': ('--max-points', 'samples', False)}),
    'multi_scan.trace': ('trace_multi_scan_surface_point.py', {
        'fusion': ('--fusion', 'directory', True), 'evidence': ('--evidence', 'directory', False),
        'category': ('--category', 'category', False), 'sample_index': ('--sample-index', 'index', False)}),
    'multi_scan.pixel_sensitivity': ('analyze_multi_scan_pixel_sensitivity.py', {
        'fusion': ('--fusion', 'directory', True), 'evidence': ('--evidence', 'directory', False)}),
    'multi_scan.local_planes': ('analyze_multi_scan_local_planes.py', {
        'fusion': ('--fusion', 'directory', True), 'evidence': ('--evidence', 'directory', False)}),
    'landmarks.align': ('apply_landmark_alignment.py', {
        'session': ('--session', 'file', True), 'refine_icp': ('--refine-icp', 'boolean', False)}),
    'cloud.preview': ('build_pointcloud_lod.py', {
        'source': ('--source','file',True),'unit':('--unit','mm_unit',True),'budget':('--budget','samples',False)}),
    'cloud.index': ('build_ply_spatial_index.py', {
        'source': ('--source','file',True),'unit':('--unit','mm_unit',True),'tile_mm':('--tile-mm','positive_mm',False)}),
    'cloud.region': ('export_pointcloud_region.py', {
        'index':('--index','directory',True),'source':('--source','file',False),'vertex_ids':('--vertex-id','vertex_ids',True),
        'radius_mm':('--radius-mm','positive_mm',False),'maximum_points':('--maximum-points','samples',False)}),
}
TRACE_CATEGORIES = ['both_support', 'target_only', 'source_only', 'repeated_conflict']


def tool_catalog():
    return [dict(name=name, implementation=script, output='new operation directory',
        parameters={key:dict(type=kind, required=required, **({'enum':TRACE_CATEGORIES} if kind=='category' else {}),
            **({'minimum':100,'maximum':100000} if kind=='samples' else {}),**({'minimum':0,'maximum':2**31-1} if kind=='index' else {}))
            for key, (_, kind, required) in params.items()}) for name, (script, params) in TOOLS.items()]


def reference(value):
    return isinstance(value, dict)


def checked_relative_path(value):
    if not isinstance(value, str) or not value or Path(value).is_absolute() or PureWindowsPath(value).drive:
        raise ValueError('Dependency path must be a relative path')
    if '..' in Path(value).parts or '..' in PureWindowsPath(value).parts:
        raise ValueError('Dependency path cannot traverse parents')
    return value


def verify_pins(plan, workspace):
    pins = plan.get('input_sha256', {})
    if not isinstance(pins, dict):
        raise ValueError('input_sha256 must be a mapping')
    for path, digest in pins.items():
        if not isinstance(path, str) or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Expected file paths and lowercase SHA256 input pins')
        resolved = (workspace / path).resolve()
        if not resolved.is_file() or file_sha256(resolved) != digest:
            raise ValueError('Pinned input changed or missing: ' + str(resolved))


def validate_plan(plan, workspace):
    if not isinstance(plan, dict) or set(plan) - {'format_version', 'name', 'input_sha256', 'nodes'} or type(plan.get('format_version')) is not int or plan.get('format_version') != 1:
        raise ValueError('Expected offline workflow format_version 1')
    nodes = plan.get('nodes')
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 64:
        raise ValueError('Workflow requires 1..64 ordered operations')
    previous = set()
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {'id', 'tool', 'parameters'}:
            raise ValueError('Each operation needs id, tool and parameters only')
        node_id = node['id']
        if not isinstance(node_id, str) or not re.fullmatch('[a-z][a-z0-9_-]{0,48}', node_id) or node_id in previous:
            raise ValueError('Operation IDs must be unique simple names')
        if not isinstance(node['tool'],str) or node['tool'] not in TOOLS:
            raise ValueError('Unknown deterministic tool: ' + str(node['tool']))
        if not (workspace/'scripts'/TOOLS[node['tool']][0]).is_file():
            raise ValueError('Registered implementation is unavailable')
        specs = TOOLS[node['tool']][1]; params = node['parameters']
        if not isinstance(params, dict) or set(params) - set(specs):
            raise ValueError('Unknown tool parameters')
        for key, (_, kind, required) in specs.items():
            if key not in params:
                if required:
                    raise ValueError('Missing tool parameter: ' + key)
                continue
            value = params[key]
            if kind in ('file', 'directory'):
                if reference(value):
                    if set(value) != {'node', 'path'} or value['node'] not in previous:
                        raise ValueError('Dependencies must refer to an earlier operation')
                    checked_relative_path(value['path'])
                else:
                    if not isinstance(value, str) or not value:
                        raise ValueError('Expected a path or earlier operation reference')
                    path = (workspace / value).resolve()
                    if not (path.is_file() if kind == 'file' else path.is_dir()):
                        raise ValueError('Missing ' + kind + ': ' + str(path))
            elif kind == 'boolean':
                if type(value) is not bool:
                    raise ValueError('Boolean required: ' + key)
            elif kind in ('index', 'samples'):
                if type(value) is not int or not (0 <= value <= 2**31-1 if kind == 'index' else 100 <= value <= 100000):
                    raise ValueError('Integer parameter outside supported range: ' + key)
            elif kind == 'category':
                if value not in TRACE_CATEGORIES:
                    raise ValueError('Unknown trace category')
            elif kind == 'token':
                if not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9_]{1,100}', value):
                    raise ValueError('Invalid source identifier')
            elif kind=='mm_unit':
                if value!='mm':raise ValueError('Current cloud tools require explicitly established unit mm')
            elif kind=='positive_mm':
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<=1000000:raise ValueError('Positive finite millimetres required')
            elif kind=='vertex_ids':
                if not isinstance(value,list) or not 1<=len(value)<=64 or any(type(v) is not int or not 0<=v<=2**32-1 for v in value) or len(set(value))!=len(value):
                    raise ValueError('Expected 1..64 distinct original uint32 vertex IDs')
        if node['tool'] == 'multi_scan.trace' and (('category' in params) == ('sample_index' in params)):
            raise ValueError('Trace requires exactly one category or sample_index')
        previous.add(node_id)
    verify_pins(plan, workspace)


def inventory(directory):
    return {str(path.relative_to(directory)).replace('\\', '/'):file_sha256(path)
        for path in sorted(directory.rglob('*')) if path.is_file()}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_state(path, state):
    temporary = path.with_suffix('.tmp'); temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8'); temporary.replace(path)


def resolve_parameters(node, workspace, out, completed):
    result = {}; snapshots = {}
    for key, value in node['parameters'].items():
        kind = TOOLS[node['tool']][1][key][1]
        if kind not in ('file', 'directory'):
            result[key] = value; continue
        if reference(value):
            dependency = completed[value['node']]; folder = out / 'nodes' / value['node']
            if inventory(folder) != dependency['output_sha256']:
                raise ValueError('Dependency outputs changed: ' + value['node'])
            path = (folder / value['path']).resolve()
            if path != folder.resolve() and folder.resolve() not in path.parents:
                raise ValueError('Dependency path escapes its operation directory')
        else:
            path = (workspace / value).resolve()
        if not (path.is_file() if kind == 'file' else path.is_dir()):
            raise ValueError('Expected ' + kind + ': ' + str(path))
        result[key] = str(path)
        metadata = [path] if kind == 'file' else [p for p in [path/'index.json', path/'summary.json'] if p.is_file()]
        if kind == 'directory' and (path/'decoded').is_dir():
            metadata += sorted((path/'decoded').glob('*/index.json'))
        snapshots.update({str(p):file_sha256(p) for p in metadata})
    return result, snapshots


def run_workflow(plan, workspace, out, cancel_file=None, on_event=None):
    workspace = Path(workspace).resolve(); out = Path(out).resolve(); allowed = (workspace/'reports').resolve()
    validate_plan(plan, workspace)
    if workspace not in allowed.parents or allowed not in out.parents or out.exists():
        raise ValueError('Use a new run directory strictly within workspace/reports')
    out.mkdir(parents=True); (out/'nodes').mkdir(); (out/'logs').mkdir()
    write_state(out/'plan.json', plan)
    state = dict(format_version=1, name=plan.get('name', ''), status='running', started_at_utc=utc_now(),
        execution_clock='UTC workflow execution time, not scanner capture time', cancellation='between operations',
        model_service_connected=False, plan_sha256=file_sha256(out/'plan.json'), nodes=[])
    completed = {}; state_path = out/'state.json'; write_state(state_path, state)
    for node in plan['nodes']:
        if cancel_file is not None and Path(cancel_file).is_file():
            state['status'] = 'cancelled_between_operations'; break
        row = dict(id=node['id'], tool=node['tool'], status='running', started_at_utc=utc_now()); state['nodes'].append(row)
        write_state(state_path, state); started = time.monotonic()
        try:
            verify_pins(plan, workspace)
            values, snapshots = resolve_parameters(node, workspace, out, completed)
            script = workspace/'scripts'/TOOLS[node['tool']][0]
            if not script.is_file():
                raise ValueError('Registered implementation is unavailable: ' + str(script))
            destination = out/'nodes'/node['id']; command = [sys.executable, str(script), '--out=' + str(destination)]
            for key, value in values.items():
                flag, kind, _ = TOOLS[node['tool']][1][key]
                if kind == 'boolean':
                    if value:
                        command.append(flag)
                elif kind=='vertex_ids':
                    command.extend(flag+'='+str(vertex_id) for vertex_id in value)
                else:
                    command.append(flag + '=' + str(value))
            row.update(resolved_parameters=values, input_sha256=snapshots, implementation_sha256=file_sha256(script),
                command_argv=command, log='logs/' + node['id'] + '.log')
            write_state(state_path, state)
            if on_event:
                on_event(dict(event='operation_started', id=node['id'], tool=node['tool']))
            with (out/row['log']).open('w', encoding='utf-8') as log:
                environment=os.environ.copy();environment['PYTHONIOENCODING']='utf-8'
                process = subprocess.run(command, cwd=workspace, stdout=log, stderr=subprocess.STDOUT, shell=False,env=environment)
            row['exit_code'] = process.returncode
            if process.returncode:
                raise RuntimeError(f'Registered tool exited with code {process.returncode}; see {row["log"]}')
            if not destination.is_dir():
                raise RuntimeError('Tool reported success without its output directory')
            outputs=inventory(destination)
            if not outputs:raise RuntimeError('Tool reported success without output files')
            row.update(status='completed', output_sha256=outputs); completed[node['id']] = row
        except Exception as exc:
            row.update(status='failed', error=str(exc)); state['status'] = 'failed'
        row.update(finished_at_utc=utc_now(), elapsed_seconds=time.monotonic()-started); write_state(state_path, state)
        if on_event:
            on_event(dict(event='operation_finished', id=node['id'], status=row['status'], error=row.get('error')))
        if row['status'] == 'failed':
            break
    if state['status'] == 'running':
        state['status'] = 'completed'
    done = {row['id'] for row in state['nodes']}
    state['not_run_operations'] = [n['id'] for n in plan['nodes'] if n['id'] not in done]
    state['finished_at_utc'] = utc_now(); write_state(state_path, state)
    return state

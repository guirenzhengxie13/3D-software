"""Explicit frame ownership and rigid corrections for offline fragments."""

import numpy as np

from .multi_scan import FrameKey, rigid


def compile_fragment_plan(plan, scan_id, index_sha256, available_frame_ids):
    if not isinstance(plan,dict) or type(plan.get('format_version')) is not int or plan.get('format_version')!=1:
        raise ValueError('Expected fragment plan format_version 1')
    if plan.get('scan_id')!=scan_id or plan.get('decoded_index_sha256')!=index_sha256:
        raise ValueError('Fragment plan belongs to another scan/index revision')
    if plan.get('unit')!='mm':raise ValueError('Fragment transforms must declare unit mm')
    if not isinstance(plan.get('decision'),str) or not plan['decision'].strip():
        raise ValueError('An explicit selection decision/provenance is required')
    rows=plan.get('fragments')
    if not isinstance(rows,list) or not rows:raise ValueError('At least one fragment is required')
    available=set(available_frame_ids);fragments={};ownership={}
    for row in rows:
        fragment=row.get('fragment_id')
        if type(fragment) is not int or fragment<0 or fragment in fragments:raise ValueError('Fragment IDs must be unique nonnegative integers')
        parent=row.get('parent_fragment_id')
        if parent is not None and (type(parent) is not int or parent<0):raise ValueError('Invalid parent fragment ID')
        ids=row.get('frame_ids')
        if not isinstance(ids,list) or not ids:raise ValueError('Each fragment needs explicit source-local frame IDs')
        for rid in ids:
            key=FrameKey(scan_id,rid)
            if rid not in available or key in ownership:raise ValueError('Missing or multiply-owned source frame')
            ownership[key]=fragment
        fragments[fragment]=dict(parent=parent,transform=rigid(row['transform_to_parent_mm']),frame_ids=ids)
    corrections={};active=set()
    def visit(fragment):
        if fragment in corrections:return corrections[fragment]
        if fragment in active:raise ValueError('Fragment transform graph contains a cycle')
        if fragment not in fragments:raise ValueError('Referenced parent fragment is absent')
        active.add(fragment);row=fragments[fragment]
        matrix=row['transform'] if row['parent'] is None else visit(row['parent'])@row['transform']
        active.remove(fragment);corrections[fragment]=matrix
        return matrix
    for fragment in fragments:visit(fragment)
    return dict(corrections=corrections,ownership=ownership,selected_frame_ids=sorted(key.frame_id for key in ownership))

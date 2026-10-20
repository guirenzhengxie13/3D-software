"""Inspect fixed-width PLY vertices and map them read-only without full loading."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np


SCALARS = {'char':'i1','int8':'i1','uchar':'u1','uint8':'u1','short':'i2','int16':'i2',
    'ushort':'u2','uint16':'u2','int':'i4','int32':'i4','uint':'u4','uint32':'u4',
    'float':'f4','float32':'f4','double':'f8','float64':'f8'}


@dataclass(frozen=True)
class PlyLayout:
    format: str
    vertex_count: int
    face_count: int
    header_bytes: int
    vertex_dtype: np.dtype | None
    vertices_are_first: bool
    comments: tuple[str, ...]


def inspect_ply(path):
    path=Path(path);fields=[];comments=[];format_name=None;vertex_count=None;face_count=0;current=None;prior_nonempty=False;vertices_first=True;fixed=True
    with path.open('rb') as stream:
        if stream.readline().strip()!=b'ply':raise ValueError('Not a PLY file')
        while True:
            line=stream.readline()
            if not line or stream.tell()>1024*1024:raise ValueError('Missing or oversized PLY header')
            words=line.decode('ascii').strip().split()
            if not words:continue
            if words[0]=='end_header':break
            if words[0]=='format':
                if len(words)!=3 or words[2]!='1.0' or format_name is not None:raise ValueError('Unsupported PLY format declaration')
                format_name=words[1]
            elif words[0]=='comment':comments.append(line.decode('ascii').strip()[8:])
            elif words[0]=='element':
                if len(words)!=3:raise ValueError('Malformed PLY element')
                current=words[1];count=int(words[2])
                if count<0:raise ValueError('Negative PLY element count')
                if current=='vertex':
                    if vertex_count is not None:raise ValueError('Duplicate vertex element')
                    vertex_count=count;vertices_first=not prior_nonempty
                elif current=='face':face_count=count
                if vertex_count is None and count:prior_nonempty=True
            elif words[0]=='property' and current=='vertex':
                if len(words)==3 and words[1] in SCALARS:
                    if any(name==words[2] for name,_ in fields):raise ValueError('Duplicate vertex property')
                    fields.append((words[2],SCALARS[words[1]]))
                elif len(words)==5 and words[1]=='list':fixed=False
                else:raise ValueError('Unsupported vertex property')
        offset=stream.tell()
    if format_name not in ['ascii','binary_little_endian','binary_big_endian'] or vertex_count is None:
        raise ValueError('Unsupported or missing PLY format/vertices')
    byte_order='>' if format_name=='binary_big_endian' else '<'
    dtype=np.dtype([(name,byte_order+kind) for name,kind in fields]) if fixed else None
    if fixed and not {'x','y','z'}<=set(dtype.names or []):raise ValueError('PLY vertices need XYZ fields')
    if format_name!='ascii' and dtype is not None and vertices_first and path.stat().st_size<offset+vertex_count*dtype.itemsize:
        raise ValueError('Truncated PLY vertex payload')
    return PlyLayout(format_name,vertex_count,face_count,offset,dtype,vertices_first,tuple(comments))


def map_ply_vertices(path):
    layout=inspect_ply(path)
    if layout.format=='ascii' or layout.vertex_dtype is None or not layout.vertices_are_first:
        raise ValueError('Read-only mapping requires first-element fixed-width binary vertices')
    if layout.vertex_count==0:return np.empty(0,dtype=layout.vertex_dtype),layout
    return np.memmap(path,mode='r',dtype=layout.vertex_dtype,offset=layout.header_bytes,shape=(layout.vertex_count,)),layout


def xyz_block(records,start=0,stop=None):
    selected=records[start:stop]
    return np.column_stack([selected[name] for name in ['x','y','z']]).astype(np.float64,copy=False)

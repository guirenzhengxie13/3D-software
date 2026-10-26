"""Validated settings for the explicit two-fragment fusion workflow."""

import math

DEFAULT_FUSION_SETTINGS=dict(voxel_mm=.6,truncation_mm=2.4,edge_threshold_mm=3.,weight_threshold=3.)
FUSION_RANGES=dict(voxel_mm=(.3,3.),truncation_mm=(.6,12.),edge_threshold_mm=(.5,10.),weight_threshold=(1.,20.))


def fusion_settings(value=None):
    if value is None:return DEFAULT_FUSION_SETTINGS.copy()
    if not isinstance(value,dict) or set(value)!=set(DEFAULT_FUSION_SETTINGS):raise ValueError('融合参数需要体素、截断、深度跳变和提取权重四项')
    result={}
    for key,(lower,upper) in FUSION_RANGES.items():
        v=value[key]
        if type(v) not in (float,int) or not math.isfinite(v) or not lower<=v<=upper:raise ValueError('融合参数超出支持范围：'+key)
        result[key]=float(v)
    if not 2*result['voxel_mm']<=result['truncation_mm']<=8*result['voxel_mm']:raise ValueError('截断距离需在体素大小的2至8倍之间')
    return result


def effective_truncation_mm(requested_mm,voxel_mm,backend):
    """Tensor honors the requested distance; retain legacy uniform-grid floor."""
    for value in [requested_mm,voxel_mm]:
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('TSDF尺寸必须是有限正数')
    if backend=='tensor':
        if requested_mm<=voxel_mm:raise ValueError('Tensor截断距离必须大于体素')
        return float(requested_mm)
    if backend=='uniform':return max(float(requested_mm),4*float(voxel_mm))
    raise ValueError('未知TSDF后端')


def executed_fusion_settings(report):
    """Read actual reconstruction fields, rather than echoing the plan."""
    if report.get('tsdf_backend')!='tensor':raise ValueError('片段融合要求Tensor后端')
    diag=report['tensor_diagnostics'];voxel=diag['voxel_m']*1000;truncation=voxel*diag['truncation_voxel_multiplier']
    if not math.isclose(voxel,report['voxel_mm'],rel_tol=1e-12,abs_tol=1e-12) or not math.isclose(truncation,report['sdf_truncation_mm'],rel_tol=1e-12,abs_tol=1e-12):raise ValueError('卷实际尺寸与重建报告不一致')
    actual=dict(voxel_mm=report['voxel_mm'],truncation_mm=report['sdf_truncation_mm'],edge_threshold_mm=report['depth_edge_threshold_mm'],weight_threshold=report['tensor_diagnostics']['extraction_weight_threshold'])
    return fusion_settings(actual)

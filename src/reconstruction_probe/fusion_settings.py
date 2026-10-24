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

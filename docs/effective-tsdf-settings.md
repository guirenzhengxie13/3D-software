# 核验参数与实际TSDF参数

2026-10-26。上一阶段允许Tensor截断距离在2–8倍体素范围内，但旧 `reconstruct_scans.py` 对所有后端执行 `max(请求截断, 4×有效体素)`。这使低于4倍的请求在后台被放大，计划和任务摘要仍可能显示请求值。

已修正：Tensor使用受支持的请求值，uniform保留原有4倍下限。既有默认0.6/2.4mm、0.8/3.2mm都为4倍，其历史结果和研究结论不受此问题影响。不修改旧计划、模型或历史摘要。

重建报告新增 `requested_truncation_mm`，原 `sdf_truncation_mm`继续记录实际配置。卷诊断增加 `voxel_m`、`truncation_voxel_multiplier`。片段执行从实际重建报告读取体素、截断、清边和提取权重，并与卷诊断及已核验计划交叉检查；两组结果均一致才完成。新摘要的 `fusion_parameters` 是核验值，`effective_fusion_parameters` 是已检查的执行值。数值配置一致不代表物理精度。

在真实同一114帧局部组件上请求0.8mm体素、1.6mm截断、3mm清边、权重3，任务 `9d10fd888e3b4e7d` 的两卷均实际倍率2、实际截断1.6mm，输出37,620/37,124点。原ROI像素SHA仍为 `5c899c637d54df68f358d9bcdb597689ce32b97a08f0d2031de2cd8a8e621736`。结果不自动采用，仍只114/336帧。

已知平面实际重建也验证2倍截断与正确米/毫米单位。初始平面恰落体素零值面时没有点云，改用非格点平面完成截断测试；这个测试几何选择不改变实际数据或接受规则。另有只读体素查询的原生坐标、负块边界和实际提取验证，总221项Python回归通过。

复用已完成任务归属、用明确参数新建核验与运行：

```powershell
.\.venv\Scripts\python.exe scripts/run_frozen_parameter_control.py --port 8877 --from-job 8197aff465a34cf7 --voxel-mm .8 --truncation-mm 1.6 --out reports/new-two-voxel-check
```

不传参数仍使用旧默认，旧默认回放的决定文本保留，已有日志可继续用 `--resume`。新任务仍需新核验，不复用已提交令牌。

[精简验证](../research/verification/2026-10-26-effective-settings/README.md)。后续继续追查体素累计和提取，当前修复本身不证明某个极端点真实或错误，也不是整份失败扫描的修复。

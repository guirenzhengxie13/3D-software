param([string]$Output = 'reports/four-scans/review.html')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$reviewArguments = @('--unit','mm','--up-axis','y')
$datasets = @(
    @('完整胸像：886帧独立TSDF','reports/four-scans/reconstruction/scan_03/tsdf_pointcloud_mm.ply'),
    @('局部胸像：54帧独立TSDF','reports/four-scans/reconstruction/scan_02/tsdf_pointcloud_mm.ply'),
    @('失败扫描：742帧未经修正基线','reports/four-scans/reconstruction/scan_04/tsdf_pointcloud_mm.ply'),
    @('失败扫描：参考辅助修正候选','reports/four-scans/reconstruction/scan_04_reference_assisted/scan_04/tsdf_pointcloud_mm.ply'),
    @('标准样例：来源与物体身份待确认','reports/four-scans/reconstruction/scan_01/tsdf_pointcloud_mm.ply'),
    @('完整＋局部：跨扫描组合候选','reports/four-scans/registration/decoded_compare/combined_voxel_surface_samples.ply')
)
foreach ($dataset in $datasets) {
    $path = Join-Path $projectRoot $dataset[1]
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing result: $path" }
    $reviewArguments += @('--cloud',($dataset[0] + '=' + $path))
}
$reviewArguments += @(
    '--out',(Join-Path $projectRoot $Output),
    '--notes','每项最多显示4万个抽样点。标准样例是否为官方示例、是否与其余数据同一物体尚未确认，当前几何匹配未通过，单独保留。参考辅助候选使用完整扫描约束失败扫描的逐帧位姿并过滤远离参考的观测，不能当作独立修复精度证据；基线另存。本批没有RGB纹理，显示颜色不代表实物颜色。各单次扫描参考系不同，请逐项审阅。',
    '--provenance','单次基线：原始深度＋保存位姿独立TSDF；组合候选：独立TSDF结果配准与体素整合，跨扫描变换基于官方输出估计。参考辅助候选：以完整扫描为参考修正失败扫描位姿后重新TSDF。原件未修改。'
)
& $python (Join-Path $PSScriptRoot 'build_reconstruction_review.py') @reviewArguments
if ($LASTEXITCODE -ne 0) { throw "Review generation failed with exit code $LASTEXITCODE" }

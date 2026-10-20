# 点云规模与局部精确交互

[研究首页与图表](../reports/pointcloud-scale-20261019/index.html) · [逐工程数量和字节数](../reports/pointcloud-scale-20261019/summary.json) · [完整实测记录](../reports/pointcloud-scale-20261019/README.md)

目前输入已经达到亿次重复观测，融合后的单模型主要在十万至百万点之间。原深度、完整表面、概览显示和局部精确操作应作为不同的数据层。

| 层级 | 当前规模 | 合适的处理方式 |
| --- | --- | --- |
| 新批单帧有效深度 | 中位25,143，最大162,754点 | 按帧解码、反投影和积分 |
| 杯子单次扫描 | 326万–997万次重复观测 | 保留原深度与位姿，流式处理 |
| 新批全部输入 | 9,434帧，266,838,143次观测 | 按工程/对象分组，避免同时展开 |
| 新旧全部输入 | 11,932帧，370,243,304次观测 | 这是语料总量，不代表同一个物体 |
| 新批主融合表面 | 单份约1.9万–16.1万点，合计204.7万 | 完整模型计算可在本机处理 |
| 更高分辨率与旧预览 | 自研候选79.3万，旧预览151.9万点 | 完整模型保留，概览另存空间缓存 |
| 显示与选点概览 | 本轮约3.9万点/模型 | 保留原始顶点编号 |
| 局部精确操作 | 按空间范围取回原顶点 | 原坐标求解，超预算明确拒绝 |

“观测次数”包含同一表面被多帧反复测量。不能把3.70亿观测当成3.70亿个互不重复表面点。压缩后的深度包约几百MiB，也不意味着全部解压可同时放进内存：新批密集深度float32展开约16.87GiB，已超过当前约15.23GiB物理内存；尚未包含算法临时数据。

## 已实现的数据路径

```text
原深度/位姿 ──逐帧融合──→ 完整表面PLY（保留）
                              ├─ 空间预览缓存：实际原顶点＋原编号＋源哈希
                              └─ 磁盘空间索引：每个有效原顶点保留一次
                                                   ↓
                                 按预览原编号选择局部范围
                                                   ↓
                                 局部完整点缓存 → 精确对应点操作
                                                   ↓
                                 后端核对完整原模型并重新求解
```

这些后端工具现已接入[Web工作台](web-studio.md)：模型概览可点击原点编号，已建索引的模型可读取局部完整点并切回概览；对应点页可直接提交后端核对。实际GPU渲染仍待验证，CPU查询耗时不能直接换算成界面帧率。

## 空间预览

在每个占用体素内选一个最接近体素中心的**实际源顶点**，记录原文件SHA256和原始顶点编号。它与把体素内点平均成新坐标不同：后续仍能回到完整原模型中的具体点。

同等约3.9万显示点下，79万点人偶的全点最大表示距离由按行抽样的10.47mm降至空间预览的1.77mm，152万点旧预览由6.40mm降至2.10mm。这些是预览对原模型的覆盖距离，不是扫描精度，也不能证明原模型正确。

构建采用分块读取和候选容量保护。体素大小搜索只保留实际测过且不超过预算的方案，不宣称得到全局最优体素。原模型与原始扫描数据均不覆盖。

项目根目录PowerShell，输出使用新目录：

```powershell
$model = 'reports\range2-study-20261018\experiments\cup-multi-scan-tsdf\joint_raw_depth\tsdf_pointcloud_mm.ply'

& '.\.venv\Scripts\python.exe' scripts\build_pointcloud_lod.py `
  --source $model --unit mm --budget 40000 --out 'reports\cup-spatial-preview-new'
```

缓存包括 `summary.json`、`preview-data.npz` 和便于查看的 `preview-mm.ply`。NPZ内保存 `original_vertex_ids`、`xyz_mm`、`rgb`。预览PLY也保留 `source_vertex_id` 属性；它的行号不能冒充完整原模型编号。

## 局部完整点索引与读取

索引为各空间块保存原顶点编号，不移除有效点。打开索引时核对源文件和索引内容哈希，运行中检查源文件状态。查询先筛空间块，再对原顶点做精确球形筛选。

实测：152万点模型额外索引约5.8MiB，局部查询中位约1.38ms；千万点合成样本额外索引约38.4MiB，局部查询中位约4.22ms。各12次查询与完整源点穷举所得编号完全一致。一次性开启和哈希核对另计，测试范围为3、5、10mm半径。

```powershell
& '.\.venv\Scripts\python.exe' scripts\build_ply_spatial_index.py `
  --source $model --unit mm --tile-mm 5 --out 'reports\cup-local-index-new'

# 12345是完整原模型顶点编号的示例，不代表某个已标注物理部位。
& '.\.venv\Scripts\python.exe' scripts\export_pointcloud_region.py `
  --index 'reports\cup-local-index-new' --vertex-id 12345 --radius-mm 5 `
  --out 'reports\cup-exact-region-new'
```

可重复传 `--vertex-id`，取多个区域的并集。候选或精确输出超过预算时明确失败，需要缩小范围或采用概览，不会偷偷抽样后仍称完整选择。局部结果使用与空间预览相同的原模型引用和原编号契约。

## 接入对应点工作台

`build_landmark_workbench.py` 新增 `--target-lod`、`--source-lod`，分别指定两侧的空间或局部缓存。无需把完整点云加载成Open3D对象后再抽样。现成人偶示例见[缓存工作台](../reports/pointcloud-scale-20261019/cached-workbench/workbench.html)，两侧完整模型分别为533,469和793,214点。

换预览时，可传 `--include-session 旧选点JSON`，把旧会话需要的原顶点加入新预览，保持原编号。数据版本不匹配或显示预算不足会拒绝，而不是把旧编号替换成新抽样行号。新增 `--notes` 可以说明本次比较的对象和坐标前提。

生成HTML的模拟交互、原编号导出与后端求解已有合成端到端控制，包含中文源路径。验证命令：

```powershell
& '.\.venv\Scripts\python.exe' scripts\check_cached_landmark_roundtrip.py
```

该检查没有伪造真实人工选点，也没有验证实际GPU画面。缓存保留原点不等于用户选的是同一物理位置，几何对应关系仍需人工审阅。

## 工作流与后续

`cloud.preview`、`cloud.index`、`cloud.region` 已加入确定性工具注册，共九类工具。实际完成[三步空间工作流](../reports/pointcloud-scale-20261019/workflow-spatial-run/index.html)，记录输入、依赖哈希、日志及状态。原有五步重建证据链继续保留。

Web界面已连接概览选点、局部区域读取和返回概览，对应点页可直接提交原坐标核对。后续补全通用片段的原深度重融合和工程历史。原始层按帧流式，完整表面用于计算，概览与局部层用于交互；不要用显示抽样替代正式融合数据。当前还没有语言模型服务。

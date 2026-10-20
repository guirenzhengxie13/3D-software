# 四份离线扫描工程：解析、重建与组合实验

实测日期：2026-10-16。输入为本项目 `item/` 下四个 ZIP 及其解压目录。全部处理离线完成，不调用 SDK；原件保持不变。

## 可以直接查看的结果

- [三维交互预览](../reports/four-scans/review.html)：四份独立重建和跨扫描组合候选，逐项旋转、平移和缩放；每项最多显示 40,000 个抽样点。
- [四份重建的多视角总览](../reports/four-scans/reconstruction_overview.png)。
- [完整胸像的独立重建 OBJ](../reports/four-scans/reconstruction/scan_03/tsdf_mesh_mm.obj) 与 [PLY](../reports/four-scans/reconstruction/scan_03/tsdf_mesh_mm.ply)。
- [完整＋局部扫描的组合候选网格](../reports/four-scans/registration/decoded_compare/combined_ball_pivoting_supported_mesh.ply)。
- [失败扫描的参考辅助修正候选](../reports/four-scans/reconstruction/scan_04_reference_assisted/scan_04/tsdf_mesh_mm.ply)，须与未经修正的基线和下文依赖说明一起看。
- 每份工程的完整深度数组、位姿矩阵和 CSV 在 `reports/four-scans/decoded/scan_01..04/`，统计见各目录 `index.json`。

网页是单个离线 HTML 文件，无 CDN 和服务端依赖；显示点经过抽样，不替代完整网格。已检查嵌入数据、JavaScript 语法及交互逻辑，当前没有可用的自动化浏览器，尚未完成真实浏览器 WebGL 画面验证。静态多视角图已逐项检查。

## 实际读取了什么

四份均为 JSON `.revox` 工程描述、RPAlgo 头的 SQLite `frames.dataset`、对应标定和预览/融合结果。没有靠模型文件名猜测解析成功。

| 编号 | 原目录名称 | 深度帧 | 保存位姿记录 | 另存全局位姿 | 有效深度样本 |
| --- | --- | ---: | ---: | ---: | ---: |
| scan_01 | 20261015_标准模型 | 816 | 817 | 0 | 17,606,410 |
| scan_02 | 四分之一turmp | 54 | 54 | 0 | 2,610,964 |
| scan_03 | 成功的川普 | 886 | 886 | 886 | 44,922,265 |
| scan_04 | 失败的trump | 742 | 743 | 0 | 38,265,522 |
| 合计 | | **2,498** | **2,500** | **886** | **103,405,161** |

2,498 条位姿对应有深度的帧；scan_01 和 scan_04 各多一条仅位姿记录，单独保存在 `pose_only/`，CSV 中标记为 `stored_pose_only`，不拿它们生成不存在的深度。

四个数据库完整性检查通过。深度为 400×300、sparse v0 布局，恢复后保留原 float32 毫米值和零值无测量区域。所有帧解析成功，没有静默跳过未知编码。

**这批工程没有 RGB 纹理。** `FrameColor` 表全部为空，实际深度载荷也不含 RGBA，工程 `scan_texture=0`。灰色表面或按扫描来源的配色属于显示和诊断，不是实物颜色。

工程描述中的 `vf_count` 分别为 1,629 / 103 / 1,765 / 1,488，与数据库中保存的深度帧数不一致。其精确语义尚未确认，因此不能宣称取得了全部传感器物理采集帧。SQL 的 `pose/optimized/droped/seqId` 等列全部为空，也不能从空列推断保存位姿不存在、帧被丢弃或已优化。四个工程 `scan.guid` 相同，不能拿这个值充当唯一项目 ID 或共同坐标系证据。

## 位姿、投影与坐标约定

新样例的 `FrameInfo.bin` 均为 **164 字节**，不是此前书本案例的可变长数组格式。第一矩阵仍在偏移 16；16 字节头和尾部 20 字节原样保留，不猜测其位标志含义。少量失败扫描记录的头标志不同，但矩阵仍可解析；可解析并不代表跟踪可靠。

`global_register_pose.pose` 仅见于 scan_03。结构为 uint32 数量及若干条 `uint32 id_high + uint32 id_low + float64[16]`。两个 ID 字分别为小端整数，组合为 `(high << 32) | low`，不可直接按小端 uint64 解读。886 个 ID 与本工程逐帧数据完全匹配。

对给定样例比较多种内参、坐标轴符号和矩阵方向后，验证出：

```text
K = 按深度尺寸缩放本工程 Pl.bin 的内参
camera_optical = [(u-cx)*z/fx, (v-cy)*z/fy, z]
scan_point = saved_pose × [camera_x, -camera_y, -camera_z, 1]
```

这里同时翻转 Y、Z，相当于绕 X 的 180° 正规旋转；与旧书本案例中尚有明显偏差的单轴翻转结论分开处理。不能不经核对推广到其他设备、格式或项目。

scan_03 分别测试了逐帧记录与全局位姿：抽样投影点到官方最终融合云的中位距离，逐帧位姿约 0.289 mm，全局位姿约 0.221 mm；90 分位由 1.615 mm 降至 0.329 mm。因而本轮 scan_03 采用另存全局位姿，其余工程使用逐帧保存矩阵。文件名及表现支持“全局配准结果”的解释，但未据此声称知道厂商具体优化算法。

## 从原始深度独立重建

实际流程为：完整深度帧读取 → 剔除深度突变边界的可疑像素 → 按标定和保存位姿投影 → Uniform TSDF 多帧融合 → 零交叉表面提取 → 保留完整结果与连通片候选。

官方 PLY 只在重建完成后用于一致性比较，没有用于生成单次 TSDF。当前安装的 Open3D Scalable TSDF 在真实帧和人工平面对照均返回空表面，因此改用已经通过对照的 Uniform TSDF，不把空输出计为成功。

| 工程 | 实际融合帧 | 实际 TSDF 体素 | 表面点 | 网格三角形 | 最大连通片三角占比 |
| --- | ---: | ---: | ---: | ---: | ---: |
| scan_01 | 816 | 0.685 mm | 61,417 | 122,561 | 99.67% |
| scan_02 | 54 | 0.746 mm | 76,339 | 146,888 | 48.86% |
| scan_03 | 886 | 0.799 mm | 171,360 | 341,863 | 99.94% |
| scan_04 | 742 | 0.838 mm | 170,856 | 338,645 | 99.15% |

体积最多 256³，因此实际体素根据范围调整，并非所有工程均达到请求的 0.6 mm。全部结果仍有边界，未宣称水密或真实补洞。

每份还生成 `voxel_all_observations_mm.ply` 和 `voxel_support.npz`，保留所有帧投影后的体素采样及观测支持，便于后续检查 TSDF 未保留的观测、噪声和低支持区域。它们不是另一份已证实更准确的模型。`tsdf_dominant_component_candidate_mm.ply` 是供选择的主连通片；尤其 scan_02 只保留约一半三角，不能默认用它替代完整局部数据。

scan_01 对官方全场景的反向覆盖起初较低，进一步检查发现官方结果还包含一块分离的近似背景平面。按连通组件拆分后，主体到独立 TSDF 的中位距离约 0.271 mm、99.98% 在 1 mm 内；分离背景平面约 11,599 个降采样点，拟合平面 RMS 约 0.196 mm，未被 TSDF 保留。这解释了整场景误差尾部，不应误写为主体丢失约 23%。

所有上述距离都是与已有工程几何的自洽性比较，**没有尺寸真值，不能称为实物测量精度**。

## 跨扫描对齐和组合

用户说明 scan_01 可能是官方标准样例，并认为可能与其余扫描为同一物体。它包含 816 帧深度与保存位姿，四包设备标识和整套标定一致，但工程未记录足够的样例来源信息，无法证明是用户采集或官方示例。预览呈现外形和尺度差异，现有刚体匹配未通过，因此暂作身份待确认的对照样例单独保留，而非凭文件名直接判定不同物体。已补充允许统一缩放的几何诊断，结果另见 `registration/standard_identity_check/`。

补充诊断先取两份独立 TSDF 的主体连通片，排除 scan_01 的背景；使用 168 个 PCA/尺度初值加 ICP。最佳统一缩放约 **1.68186 倍**，双向中位距离仍为 2.879 / 5.581 mm，2 mm 内的双向覆盖约为 40.34% / 27.48%。缩放改善了刚体基线，但没有使当前几何达到高重合；这组有限初值试验也不是全局最优或身份不同的证明。没有据此修改标定、改变实物尺度或强行合并。若以后确认是可信标准数据，再决定它是否适合作为评测基准。

对另外三份比较了 PCA 多初值、FPFH/RANSAC、FGR 和多尺度 ICP，并记录双向覆盖、距离分位和法线一致性：

- **scan_02 → scan_03 通过**。官方输入的单向中位距离约 0.317 mm；独立 TSDF 在相同变换下约 0.385 mm。反向覆盖低符合局部扫描的性质，不能把局部数据称为完整覆盖。
- **scan_04 整份未通过**。独立 TSDF 对参考的中位距离约 0.935 mm，1 mm 覆盖约 52.23%、2.5 mm 覆盖约 79.71%，仍有系统偏差。保留变换与偏差区域，不把整份错误几何混入通过的候选。

对 scan_02 + scan_03 独立 TSDF 结果做了体素平均、法线处理和有边长限制的球枢轴三角化，产生 170,788 个表面采样、137,024 个网格顶点及 272,905 个三角形。仍有 1,341 条边界边、38 个连通片；没有推断一个完整实体。

跨扫描变换的初值来自官方点云配准，再在独立 TSDF 上检验；组合阶段没有把两个工程全部原始深度帧联合重新积分。另有一套基于官方输入云的 Poisson 实验，路径和来源均独立记录，不能混作完全从原始深度生成的结果。局部扫描主要增加重叠观测，目前没有证据证明它补出了原完整模型缺失的真实表面。

## 复现与文件保护

### 失败扫描的额外修正试验

在保留原始 scan_04 重建的同时，以 scan_03 独立 TSDF 表面为参考，对 scan_04 每帧做有界的稳健点到面 ICP。整体配准候选仅作为初值，不能因局部优化就改写它原先未通过的结论。

先测试 48 帧，再对全部 742 帧运行；742 帧均通过本次设定的修正量和重叠检查。帧级最近邻中位距离的中位数从 **0.869 mm 降至 0.351 mm**，旋转修正中位约 1.660°，观测点位移中位约 2.842 mm。这个距离正是被优化的目标，不是独立实物精度。

用修正位姿重新积分 742 帧，得到 160,493 个表面点、160,572 个顶点和 316,992 个三角形，仍非水密。剔除距参考支持超过 2.5 mm 的 5,586 个深度像素，约占输入有效观测的 0.015%；这些像素可能是错误，也可能是参考中未见的新区域，不能自动认定为缺陷。原基线、完整原始观测、修正矩阵和逐帧统计全部保留。

[修正前后正交视图](../reports/four-scans/reconstruction/scan_04_reference_assisted/before_after.png) 已检查，重复轮廓减少。整云到参考的 90 分位距离由 3.044 mm 降到 0.538 mm，但参考到候选的反向 1 mm 覆盖只有约 86.15%，其 90 分位距离仍约 8.18 mm。因此改善重叠不能解释为缺失表面已经恢复。

本轮可以称为**利用另一份成功扫描辅助修正失败扫描的候选工作流**。它依赖所选参考，特征弱或对称区域仍需人工审阅；没有宣称独立修好了全部失跟，也没有把它自动并入先前通过的组合结果。完整记录在 `reconstruction/scan_04_reference_assisted/experiment.json`。

### 运行命令

在本项目 PowerShell 中，使用 Python 3.12 虚拟环境：

```powershell
$env:PYTHONIOENCODING = 'utf-8'

# 完整数据库解析，输出必须是新的独立目录。
.\.venv\Scripts\python.exe scripts/decode_scan_projects.py --input item --out reports/four-scans/decoded_new

# 由解包后的全部帧独立重建；不调用官方融合。
.\.venv\Scripts\python.exe scripts/reconstruct_scans.py --decoded reports/four-scans/decoded_new --out reports/four-scans/reconstruction_new

# 官方结果作为输入的跨包配准实验（与原始深度重建分开）。
.\.venv\Scripts\python.exe scripts/register_scans.py --item item --output reports/four-scans/registration_new

# 将独立 TSDF 结果接入已求出的跨扫描变换，单独比较和三角化。
.\.venv\Scripts\python.exe scripts/register_scans.py --output reports/four-scans/registration_new --raw-tsdf-root reports/four-scans/reconstruction_new

# 所有原件哈希、ZIP CRC 与解压一致性检查。
.\.venv\Scripts\python.exe scripts/verify_scan_inputs.py

# 额外参考辅助修正；单独输出，不替换未经修正的模型。
.\.venv\Scripts\python.exe scripts/refine_failed_scan.py --full-if-promising

# 包括位姿、深度解码和原件保护的测试。
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`input-integrity.json` 记录：4 个 ZIP 的 CRC 全部通过；63 个解压文件与 ZIP 对应内容逐字节哈希匹配；处理前后 63 个原工程文件哈希全部不变。数据库头只在临时副本中恢复，再以只读方式查询。原始 `item/`、生成结果及私有数据不纳入版本控制。项目改名后的 `.venv` 可编辑安装路径已修复。

最终 26 项测试通过，包括已知平面的实际 TSDF 深度对照、两种位姿结构、非刚体拒绝、稀疏深度/颜色布局、体素权重跨批次守恒、无效深度边界处理和源文件保护。

本轮落地的是可复现的读取、重建、配准与审阅原型；交互式区域编辑、撤销历史和 Agent 工具层仍需要在这些真实处理能力上继续实现。

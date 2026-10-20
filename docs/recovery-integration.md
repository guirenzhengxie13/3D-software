# 既有离线恢复成果与后处理接入

核查日期：2026-10-15。通过已连接的 GitHub 账号读取了用户提供的[私有仓库](https://github.com/guirenzhengxie13/Fuck_Revopoint)，固定版本 `a3fae1ab31e01fd38b10e4ac2a892b38726c378d`。初次完成源码与元数据审查后，现已取回逐帧二进制记录，在本机恢复出全部 12 帧位姿并进行几何一致性检查；没有重跑完整数据库解包，也没有修改该仓库。详见 [位姿恢复实测](pose-recovery.md)。

## 已定位的成果

入口为 [recover_revo_range.py](https://github.com/guirenzhengxie13/Fuck_Revopoint/blob/a3fae1ab31e01fd38b10e4ac2a892b38726c378d/recover_revo_range.py#L333)，标定参数导出工具为 [dump_camera_params.py](https://github.com/guirenzhengxie13/Fuck_Revopoint/blob/a3fae1ab31e01fd38b10e4ac2a892b38726c378d/dump_camera_params.py)。

这份实现读取 `frames.dataset` 数据库，支持其已识别的 sparse RANGE v0 布局，不是此前公开调研中逐个 `.dph` 的旧解析器。离线恢复不依赖官方 SDK；源码主要依赖 NumPy、OpenCV 和 Python 标准库，其中 `hashlib.file_digest` 要求 Python 3.11 或更新版本。

## 案例所证明的能力

仓库中的书本案例，其原工程元数据标记设备为 RANGE 2。下表区分原工具记录和本次实际恢复结果：

| 项目 | 案例记录 |
| --- | --- |
| 帧记录 | 12 帧；不能据此证明覆盖设备全部物理采集帧 |
| RGB | 12 帧导出成功 |
| 深度 | 12 帧恢复成功，400×300、float32、毫米 |
| 相机系点云 | 12 个 PLY，共 358,714 点 |
| 保存位姿 | 原工具漏读；本次从 bin 恢复出 12 个第一矩阵及 12 个第二矩阵 |
| 扫描参考系点云 | 本次生成 12 个候选点云；仍存在明显几何偏差，尚未融合 |
| 官方融合结果 | 77,227 点，原件复制供参考 |
| 官方原始预览 | 12,018 点，原件复制供参考 |

[案例恢复摘要](https://github.com/guirenzhengxie13/Fuck_Revopoint/blob/a3fae1ab31e01fd38b10e4ac2a892b38726c378d/%E6%A1%88%E4%BE%8B_%E4%B9%A6%E6%9C%AC%E6%89%AB%E6%8F%8F_c7deada8/analysis/recovered/run_summary.json) 和同目录空的 `poses.csv` 反映原工具只接受 292 字节记录的限制。实际记录为 532–964 字节，矩阵仍在偏移 16；动态解析后全部读出。104 个标记点观测中，100 个经第一矩阵正向变换后距工程标记框架不足 1 mm，中位偏差 0.221 mm，支持其变换方向；不能把该一致性指标当作独立重建精度。

该案例的 `seqId`、`droped`、`optimized` 等字段同样未解析，不能把全部导出帧等同于官方实际参与融合的帧集。官方融合云和预览云是复制结果，不是恢复脚本重新配准融合生成；当前也没有独立尺寸真值或严格几何精度验证。

## 本软件的接入契约

从恢复输出目录读取实际可用资源，以报告和逐帧 JSON 判断状态：

| 资源 | 使用约定 |
| --- | --- |
| `frame.json` | 帧 ID、恢复状态、点数、单位、内参、坐标说明及位姿应用情况 |
| `depth_mm.npy` | 优先作为无损深度输入，float32 毫米；0 为无测量；结合有效掩码 |
| `depth_raw16.png` | 量化深度备选，比例由记录决定，不能直接把整数当作毫米 |
| `rgb.jpg` / `color_aligned.png` | 可用时作为颜色资源；JPEG 导出经过重编码，不代表原始字节保存 |
| `cloud_camera.ply` | 局部光学坐标点云，默认毫米；进入本项目基础点云契约时按元数据转换为米 |
| 位姿 NPY / `cloud_world.ply` | 仅在成功解析且约定经过核对时使用；缺失时保留未知 |
| `report.json` / `run_summary.json` | 包级清点、恢复数量、限制和错误，不以目录名推断恢复成功 |
| `vendor_fuse.ply` 等 | 标记为官方已有结果，作为基线或单独输入，不冒充自研重建成果 |

恢复源码的相机坐标为 X 向右、Y 向下、Z 向前。候选点云转换使用 `M_at16 × [x, y, -z, 1]`，不可重复应用变换。该选择优于本次测试的反向与正 Z 方案，但对官方预览云仍有 36.91 mm 中位距离，应继续核对深度校正与投影。光学 Z 反射改变手性，转换后的 3×3 矩阵不可直接作为右手旋转。不同工程仍需要独立的跨包对齐。

首版可从这些相机系点云建立帧索引、预览和人工选择，再用后处理配准估计位置。厂商位姿可在可用时作为初值；保存位姿与自研估计分别记录。这样位姿缺失不会阻塞全部后处理工作。

## 接入时应处理的两个问题

1. [PLY 写出函数](https://github.com/guirenzhengxie13/Fuck_Revopoint/blob/a3fae1ab31e01fd38b10e4ac2a892b38726c378d/recover_revo_range.py#L176) 对 world 点云也写入 `camera_optical` 坐标注释。适配时不能仅信该注释，应对照输出类别和帧 JSON，随后在受控集成版本中修正。
2. 脚本会复制数据库后只读查询，并校验源数据库哈希；但[主程序汇总写入](https://github.com/guirenzhengxie13/Fuck_Revopoint/blob/a3fae1ab31e01fd38b10e4ac2a892b38726c378d/recover_revo_range.py#L472) 没有完整复用输出路径保护：单库导出拒绝原目录后，仍可能向该路径写入汇总。标定工具的 JSON 输出也没有源目录保护。集成时应在启动任何导出前统一校验独立输出目录；本次没有修改或执行这些工具。

当前应复用的边界是：**已有离线恢复输出 → 本项目导入适配 → 统一后处理命令 → 人工交互或 Agent 工作流**。新的重建成果需通过真实运行和比较产生，不把现有复制基线计作已实现的后处理效果。

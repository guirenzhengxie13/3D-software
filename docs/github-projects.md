# Revopoint 相关 GitHub 项目调研

核对日期：2026-10-15（Asia/Shanghai）。首个目标设备为 RANGE 2，当前开发电脑为 Windows x64。以下依据 GitHub README、实际源码和默认分支提交记录；本轮没有运行这些第三方程序，也没有验证真实设备。

本次未找到带有明确 RANGE 2 真机采集成功记录、可直接完整替代 Revo Scan 的第三方项目。已经找到值得复用思路的实时驱动、离线逐帧解析和交互重建尝试。仓库里出现设备枚举值，只能证明存在接口定义；其他型号的采集成功也不能自动推及 RANGE 2。

## 优先关注

| 项目 | 已核实的内容 | 对本课题的用途与边界 |
| --- | --- | --- |
| [rccn-dev/revopoint_camera](https://github.com/rccn-dev/revopoint_camera) | ROS 2 节点调用 SDK 枚举、连接、开流，发布深度、RGB 和 PointCloud2。所附 SDK 为 3.2.229.20251110，头文件显式列出 `CAMERA_RANGE_2` | 最值得进一步核对的 RANGE 2 采集参考。未找到 RANGE 2 实测记录；构建指向 Linux x64/aarch64，需要为 Windows 独立采集层调整。公开 vendor 目录不等于设备已获授权 |
| [tycoon0804/revopoint_ros](https://github.com/tycoon0804/revopoint_ros) | Windows ROS 1/Catkin 接入，README 明确实测 MINI 2；源码通过厂商 SDK 发布深度、RGB、内参和点云 | 用户已有 MINI 2，可作为另一台设备的验证线索。仍依赖 3DCamera DLL；RANGE 2 未证实，POP 3 被列为 TODO，不应扩大兼容范围 |
| [HazenBabcock/revopoint-python](https://github.com/HazenBabcock/revopoint-python) | Python 通过 Wi-Fi HTTP 获取深度和 RGB，控制曝光、增益；README 明确实测初代 MINI、固件 v7.6.9.0816、Python 3.10/3.12 | 可研究精简采集接口和非官方网络接入。作者报告约 4 Hz，深度仍是原始值、未转换毫米；未证实 RANGE 2、MINI 2 或当前固件兼容 |
| [jamesratzlaff/revopoint-viewer](https://github.com/jamesratzlaff/revopoint-viewer) | Python 读取 RevoScan 工程 `property.rvproj`、`Q.bin`、`.dph` 和 `.inf`，生成带帧位姿变换的 XYZ，并用 Open3D 显示 | 很适合作为离线逐帧接入参考；可帮助开发关键帧浏览、重配准。没有硬件实时采集或 RGB 读取，也没有 Revo Scan 6 / RANGE 2 明确兼容声明 |
| [1bigpig/REVOMOD](https://github.com/1bigpig/REVOMOD) | FreeBASIC 编写的 Revo Scan 5 关键帧工具，支持显示/隐藏帧和复制扫描子项目，按追踪丢失位置拆分，再交回官方软件融合合并 | 与“交互式辅助重建”的问题很接近，可借鉴帧筛选与失跟恢复流程。它没有自有完整重建引擎；作者也标明部分帧标志行为尚未完全验证 |
| [pranch555/CloudClean](https://github.com/pranch555/CloudClean) | Python/Open3D 后端与浏览器工作台，含清理、配准、网格、编辑、测量和项目流程；有 MetroY/MetroY Ultra Linux USB 采集尝试，以及接收官方软件导出文件的桥接 | 可参考软件模块和交互流程。原生采集针对 MetroY 系列，并非 RANGE 2 驱动；协议文档是作者的观测与试验，仍有开放问题。没有找到根 LICENSE 或 pyproject 许可证声明，复用源码前应确认许可 |
| [BR1ZB3AR/All3DScan](https://github.com/BR1ZB3AR/All3DScan) | 开发中的 Linux 扫描应用，涉及设备接入、配准、融合和界面；硬件矩阵把 POP4 列为实验采集，POP/POP2/POP3/MINI/RANGE 列为候选 | 可参考应用结构。候选列表不是成功记录；未证实 RANGE 2。部分文档状态存在不一致，不能仅据 README 的完成列表判断成熟度 |

### RANGE 2 的具体源码线索

`rccn-dev/revopoint_camera` 固定提交 `5dad032dbe56082c0c8b300db1a5bafeec8d30fe` 的 [Types.hpp 第 138 行](https://github.com/rccn-dev/revopoint_camera/blob/5dad032dbe56082c0c8b300db1a5bafeec8d30fe/3DCameraSDK-v3.2.229.20251110/inc/3dcamera/hpp/Types.hpp#L138) 明确有 `CAMERA_RANGE_2`，后面还有 MINI 2。它比此前 2023 年公开 3DViewer 所带 SDK 更新。

这给了我们一份可供与厂商现行 SDK 对照的接口样本，但型号枚举、设备激活和真机成功是三个不同事实。拿到官方试用包后，应对照版本、ABI、头文件、深度比例及回调约定，不直接替换 DLL 猜测兼容。

### 离线解析的具体源码线索

`jamesratzlaff/revopoint-viewer` 的 [cache_parser.py](https://github.com/jamesratzlaff/revopoint-viewer/blob/65fba550d4dc406b7ea0d998006f496e2ecd776a/cache_parser.py) 会读取项目中的深度比例与图像尺寸，利用 Q 矩阵从深度生成几何，再从 `.inf` 文件偏移 `0x10` 读取 float64 的 4×4 帧变换。它基于 [fxtentacle 原始解析示例](https://gist.github.com/fxtentacle/d3002f2c4084b9758c4228d5aedb276a) 扩展。

这是作者针对特定旧工程结构的实现，不是厂商公开格式规范。接入前需要一份本人的真实扫描工程副本，检查文件布局、版本、尺寸、字节序、单位和矩阵含义；不能把旧版偏移量直接当作 Revo Scan 6 的稳定规范。

## 其他有价值的尝试

- [X3msnake/revoscan-frame-player](https://github.com/X3msnake/revoscan-frame-player)：读取旧版 Revo Scan/Revostudio 5+ 缓存，播放或导出图像，helpers 中有深度/点云探索。CC0-1.0，可参考帧浏览；没有实时硬件采集。所查点云 helper 硬编码尺寸、深度比例及颜色偏移，也未应用 Q 和帧位姿，只适合作为探索代码。README 和旧 release 使用过不同版本写法，不能推断全部 5.x/6.x 兼容。[发布页](https://github.com/X3msnake/revoscan-frame-player/releases)。
- [TamedTornado/revopoint-pop3-linux-wifi](https://github.com/TamedTornado/revopoint-pop3-linux-wifi)：Rust/Linux 独立实现，明确实测 POP 3 Plus、固件 v3.2.36.20241219；Wi-Fi 深度/IR/RGB 采集、标定与彩色 PLY/回放有代码和试验说明。直接 USB 媒体采集尚未实现，精度仍待完整验证，也未证实 RANGE 2。可参考网络流解码、时间戳和数据归档设计。
- [PlusToolkit/PlusLib 的 Revopoint3DCamera 模块](https://github.com/PlusToolkit/PlusLib/tree/master/src/PlusDataCollection/Revopoint3DCamera)：[C++ 源码](https://github.com/PlusToolkit/PlusLib/blob/master/src/PlusDataCollection/Revopoint3DCamera/vtkPlusRevopoint3DCamera.cxx) 已包含开深度流、读取帧、读取内外参及深度比例、调用 `Pointcloud::generatePoints` 的链路。不过代码和日志指向 Revopoint Surface 相机，可参考采集层组织，不能当成 RANGE 2 成功案例。
- [Revopoint/3DViewer](https://github.com/Revopoint/3DViewer)：官方 C++ 接入与显示参考，最后默认分支提交为 2023-08-09；使用旧版 SDK。它有设备发现、参数控制、2D 和点云显示，适合与新的 SDK 接口对照，不是官方 Revo Scan 完整源码。

## 维护与许可证快照

以下日期为核对时默认分支最新提交日期（UTC 日期），不代表项目经过本机或 RANGE 2 验证。

| 项目 | 最近提交日期 | 许可说明 |
| --- | --- | --- |
| rccn-dev/revopoint_camera | 2026-02-24 | package.xml 声明 BSD-2-Clause；根目录未见 LICENSE，附带二进制 SDK 的许可需单独核对 |
| tycoon0804/revopoint_ros | 2024-08-17 | GPL-3.0；附带 SDK 的许可仍应单独确认 |
| HazenBabcock/revopoint-python | 2026-10-09 | MIT |
| jamesratzlaff/revopoint-viewer | 2024-04-23 | MIT |
| X3msnake/revoscan-frame-player | 2024-03-08 | CC0-1.0 |
| 1bigpig/REVOMOD | 2025-03-02 | 未发现明确 LICENSE |
| pranch555/CloudClean | 2026-10-13 | 未发现明确 LICENSE |
| BR1ZB3AR/All3DScan | 2026-10-14 | MIT；依赖项仍分别适用其许可 |
| TamedTornado/revopoint-pop3-linux-wifi | 2026-09-03 | MIT |
| Revopoint/3DViewer | 2023-08-09 | 仓库源码 GPL-3.0；SDK 二进制许可应分别确认 |

提交记录可从各仓库 Commits 页面复核；许可证标签只描述所核对的源码声明，不自动覆盖硬件授权、附带 SDK 或第三方依赖。

## 建议采用的路线

根据后续讨论，近期主线改为官方软件采集与离线逐帧解析，优先研究 `revopoint-viewer` 的工程解析和 REVOMOD 的帧筛选工作流。详细验真与开发顺序见 [离线逐帧解析计划](offline-ingestion-plan.md)。SDK 申请与实时接入作为后续工作，取得后以 `revopoint_camera` 和官方 3DViewer 对照采集接口；Windows 桌面应用可借鉴采集组织，不必整套引入 ROS。

设备和授权等待期间，优先研究 `revopoint-viewer` 的工程解析，以及 REVOMOD 的帧筛选工作流，让逐帧回放、人工删选、局部重新配准先形成可验证的功能。完整工作台的模块和交互可参考 CloudClean / All3DScan，但需要逐项审查实现与验证状态。Wi-Fi 独立实现保留为实验路线，待设备到场后验证其与 RANGE 2 固件的实际差异。

如果 RANGE 2 适配暂时受阻，而 MINI 2 先能到场，`tycoon0804/revopoint_ros` 明确的 MINI 2 / Windows 实测描述比套用初代 MINI 的网络配置更接近现有设备条件；仍需核对 SDK 与固件，并运行原版示例验证。

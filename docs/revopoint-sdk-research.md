# Revopoint RANGE 2 接口与开发准备调研

核对日期：**2026-10-15（Asia/Shanghai）**。目标是在 Windows x64 上开发面向三维扫描模型的交互式辅助重建软件，首先接收 RANGE 2 的逐帧几何数据，再实现自己的显示、交互、配准和重建流程。

当前设备不在手边，计划于 2026-10-16 由朋友拍摄设备编号。本文没有使用真实 SN，没有申请试用、购买授权、发送邮件或验证真机。

## 一、当前官方页面已经证实的事实

### 1. RANGE 2 在扫描仪 SDK 的兼容名单中

官方 **3D Scanner SDK Authorization Service** 商品页明确列出 RANGE 2；同页还列出 POP 2、POP 3、POP 3 Plus、MINI、MINI 2、RANGE、INSPIRE 和 INSPIRE 2。不能将该名单推及其他机型，也不能仅凭同属 Revopoint 推断它们共用授权。

来源：[官方 SDK 商品与试用入口](https://www.revopoint3d.com/products/3d-scanner-sdk-authorization-service)、[官方全球商店同款页面](https://global.revopoint3d.com/products/3d-scanner-sdk-authorization-service)。

### 2. 30 天试用与正式授权是两个步骤

商品页有 **Start Your 30-Day Free Trial** 入口。官方商店的可见表单说明，提交后由厂商通过邮件提供激活步骤；该表单要求以下信息：

| 字段 | 是否必填 | 当前准备方式 |
| --- | --- | --- |
| Name | 是 | 填真实申请人姓名 |
| Email | 是 | 填可接收 SDK 与授权邮件的邮箱 |
| Country | 是 | 按申请人所在地填写 |
| 3D Scanners | 是 | 选择 RANGE 2 |
| SN | 是 | 填设备机身背面的 16 位编号，示例格式为 XXXX-XXXX-XXXXXXXX |
| Phone Number | 否 | 按需要填写 |
| Industry | 否 | 如有对应选项，可选择教育或科研 |

表单预先定义的提交成功提示表示：激活码将通过邮件发送，未收到可联系 `customer@revopoint3d.com`。这只能证明“提交申请后等待邮件”的流程，不能证明提交后立即自动发码；页面也没有明确写需要人工审批，或承诺 SDK 试用申请的处理时长。不要把商品通用的 3–5 天配送文案、其他软件的试用时限当作 SDK 发码时限。本文仅核对页面文案，未提交表单验证。

公开页面同样没有明确试用从申请、发码还是首次激活时起算。设备未到位前可以准备开发环境、离线输入和界面；拿到 SN 并准备好联调时间后，再确认试用起算规则。安排进度时应为邮件往返和授权处理预留弹性，不能承诺当天获批或固定若干工作日内完成。

来源：[官方试用表单所在商店页面](https://store.revopoint3d.com/ia/products/3d-scanner-sdk-authorization-service)。

### 3. 正式费用与边界

核对时美元商店页面展示 **$2,000.00**；这是该区域页面的展示金额，不是人民币报价，最终币种、税费、学校优惠及具体合同需另行确认。商品说明为一次付款，对当前 SDK 支持的一个或多个设备提供永久授权，通过设备 SN 远程激活；不包含未来 SDK 升级及未来机型。

“一个或多个设备”不能自行解释为无限台，也不能写成每台固定 2,000 美元。实际 SN 数量、后续增加设备、换机及软件分发条件，应取得厂商书面说明。建议先试用验证数据接口，再决定是否购买。

来源：[官方授权条款与展示价格](https://www.revopoint3d.com/products/3d-scanner-sdk-authorization-service)。

### 4. RANGE 2 硬件与连接

官方规格支持 USB Type-C 和 Wi-Fi 6，工作距离 400–1300 mm，最高扫描速度 16 fps，带有 RGB 相机及九轴 IMU。最高速度是产品指标，不是当前 SDK 对某一分辨率、数据格式或电脑配置的保证；带有 IMU 也不等于 SDK 必然开放 IMU 或相机位姿。

建议首次真机联调采用 USB。Wi-Fi 模式需外接充电宝或墙充供电；如果从电脑 USB 供电，会默认识别为 USB 连接。设备指示灯变绿后，连接名为 `RANGE 2-REVO-XXXXXXXX` 的设备无线网络，无需密码。该网络没有互联网时，应保留连接。

来源：[RANGE 2 官方规格页](https://global.revopoint3d.com/pages/handheld-3d-scanner-range2)、[官方 Wi-Fi 连接说明，2026-07-10 更新](https://support.revopoint3d.com/hc/en-us/articles/23762930577691-Wi-Fi-Connection-wifi)、[RANGE 2 官方快速指南](https://download.revopoint3d.com/pdf/range2-guide.pdf)。上述步骤是官方硬件和应用连接说明；具体 SDK 的网络枚举和授权行为仍需实测。

### 5. 官方软件作为设备连通性基准

官方软件下载页提供按型号筛选。中国下载中心核对时列出 Revo Scan 6 Windows V6.4.1（2026-10-10 更新），兼容列表包含 RANGE 2；Revo Scan 5 Windows V5.5.5 也包含 RANGE 2。Windows 安装包要求 x86_64。准备阶段可保留官方软件，用来先确认供电、线缆和设备连接正常。

来源：[国际官方软件下载页](https://www.revopoint3d.com/pages/support-download)、[中国官方软件下载页](https://www.revopoint3d.com.cn/download.html)。软件版本会变化，应以下载时的型号筛选结果为准。

## 二、公开旧版示例证实了什么，不能保证什么

### 1. 官方 3DViewer 是代码参考，不是当前 RANGE 2 SDK 的兼容性证明

官方人员于 2023-07-06 在论坛发布支持二次开发的扫描仪 SDK，并指向 `Revopoint/3DViewer`。该仓库公开了相机控制、采集、显示及深度转点云代码。仓库文档介绍 USB 和网络连接、Z16/Z16Y8Y8/Pair 深度格式、RGB8/MJPG、单帧及多帧采集与回放。

来源：[官方人员发布说明](https://forum.revopoint3d.com/t/is-there-any-sdk-or-api/2410?page=2)、[官方 3DViewer 仓库](https://github.com/Revopoint/3DViewer)、[官方示例文档目录](https://github.com/Revopoint/3DViewer/tree/master/document/manual-md/English)。

公开仓库 `3DCamera.hpp` 显示 SDK 版本宏 **3.2.23**。这只是仓库内版本，不能当作厂商当前最新 SDK，也不能据此承诺支持 RANGE 2 当前固件。应向厂商索取适配该设备 SN、固件和 Windows x64 的现行包及说明。

来源：[仓库内 SDK 版本头文件](https://github.com/Revopoint/3DViewer/blob/master/thirdparty/3DCamera/include/3DCamera.hpp)。

### 2. 可参考的公开函数

下面名称来自公开旧版 C++ 头文件，只用于理解接口需求和后续对照，**不应在尚未取得对应 SDK 时伪造调用成功或承诺这些函数可直接用于当前设备**。

| 目标 | 公开旧版接口 |
| --- | --- |
| 连接、读取设备信息 | `connect`、`getInfo`、`disconnect` |
| 枚举设备支持的流格式 | `getStreamInfos`、`isStreamSupport` |
| 连续帧回调或主动取帧 | `startStream`、`FrameCallback`、`getFrame`、`stopStream` |
| 获取成对的深度和 RGB 帧 | `getPairedFrame`；其同步精度和真实时间戳仍需确认 |
| 曝光等参数及取值范围 | `getPropertyRange`、`getProperty`、`setProperty` |
| 深度比例及标定参数 | `getPropertyExtension`、`getIntrinsics`、`getExtrinsics`、`getDistort` |
| 深度图生成点云 | `cs::Pointcloud::generatePoints` |
| 获取几何及纹理映射 | `getVertices`、`getNormals`、`getTexcoords` |

来源：[旧版 Camera.hpp](https://raw.githubusercontent.com/Revopoint/3DViewer/master/thirdparty/3DCamera/include/hpp/Camera.hpp)、[旧版 Processing.hpp](https://raw.githubusercontent.com/Revopoint/3DViewer/master/thirdparty/3DCamera/include/hpp/Processing.hpp)。

可行的开发思路是先获取逐帧深度和 RGB，并读取相应标定参数及深度比例，再生成单帧 XYZ。该流程与后续多帧配准、融合、补洞、网格重建是不同阶段。现有公开依据不能证明能直接调用 Revo Scan 完整重建引擎或读取它的实时融合模型。

### 3. 平台、工具链和 Python 的证据边界

3DViewer README 列出 Windows 10 x64、Ubuntu 18.04 x64、macOS 10.15 x64；构建示例依赖 Qt 5（至少 5.10.1）、Visual Studio 2015 或更新版本、CMake、OpenSceneGraph 3.6.5 和 OpenMP。这些是旧版示例要求，当前 SDK 的 MSVC 工具集、运行库和 ABI 必须以厂商现行包为准。

2023-06-01 官方人员曾回复支持 C++ 和 Python。但 2026 年的公开论坛仍有人询问正式文档和 Python 支持，公开回复只引导联系支持，未给出现行 Python 包或版本表。因此目前建议以 C++ 原生采集作为接口准备方向，Python 可用于上层验证，但不能预设已有可安装的官方 Python wheel。

来源：[官方仓库 README](https://github.com/Revopoint/3DViewer)、[2023 年官方语言支持回复](https://forum.revopoint3d.com/t/is-there-any-sdk-or-api/2410?page=2)、[2026 年文档与 Python 问题](https://forum.revopoint3d.com/t/sdk-documentation-python-support/43567)。

### 4. 避免混用不同产品线与早期说法

- 工业相机站点中的 Acusense、Surface 和 Linescan SDK 有自己的产品及接口范围，不能直接视为 RANGE 2 授权包。来源：[工业相机 SDK 入口](https://3dcamera.revopoint3d.com/html/developer/)、[Acusense 产品说明](https://3dcamera.revopoint3d.com/html/acusense/index.html)。
- 2023 年初期论坛出现“只读取设备数据和设置参数，不支持 scanning”的说法；不能将其扩大成“现在不能得到深度/单帧点云”。后续官方发布和公开代码应一并核对，也不能反向推断开放了完整配准融合。来源：[同一论坛主题的时间顺序](https://forum.revopoint3d.com/t/is-there-any-sdk-or-api/2410?page=2)。
- 3DViewer 仓库标注 GPL-3.0。使用其源码与再分发随附 SDK 二进制是不同事项，应分别核查授权文件和厂商许可。来源：[仓库许可证](https://github.com/Revopoint/3DViewer/blob/master/LICENSE.txt)。

## 三、申请时必须确认的事项

1. 提供适配 **RANGE 2 + 当前固件 + Windows x64** 的现行 SDK、API 文档、最小采集示例、驱动及授权工具；明确是否需要特定固件。
2. 能否直接输出逐帧 XYZ/XYZRGB；若主要输出深度，是否提供深度单位/比例、相机内参、畸变、深度至 RGB 外参和有效像素规则。
3. 可用深度/RGB 格式、分辨率、帧率；RGB 与深度是否同步，时间戳来自设备还是主机，其单位、精度、时钟基准及丢帧检测方式。
4. 是否开放逐帧位姿、追踪状态、置信度、IMU 数据；若不开放，明确需要应用自行估计。
5. USB 和 Wi-Fi 是否都支持开发接口，网络模式如何枚举设备、建立连接及认证；是否允许同一设备被官方软件与自研程序同时占用。
6. C++ 编译器、MSVC 工具集、CRT `/MD` 或 `/MT`、Debug/Release、C++ ABI、DLL 依赖及部署要求；是否有稳定 C API。
7. 当前 Python 支持情况：官方封装是否仍维护，支持的 CPython 版本/架构，安装方式及可运行示例；若无官方封装，是否允许自行包装 C/C++ 接口。
8. 30 天从何时起算，能否在设备准备好后激活，是否可延期；申请是否必须同时连接真机。
9. 首次激活与后续使用是否需要联网；离线电脑、换电脑、重装系统、SN 增补及换机的处理方式。
10. 学术研究、毕业设计、论文/源码公开、SDK 头文件及 DLL 再分发、向其他持证设备部署的许可边界；提供正式报价和多设备授权条件。

## 四、今天与设备到位后的顺序

今天先完成本地开发环境检查、离线点云读取/显示/保存、统一帧数据结构、日志和设备适配层；使用模拟或回放数据时，在界面和日志明确标识来源。未取得授权和真机前，不把离线运行视为实时采集已经成功。

拿到 RANGE 2 设备编号后，先用官方应用确认真机连接，再按厂商流程申请/激活 SDK，运行官方最小示例，核对实际流格式、深度比例、时间戳和稳定帧率；最后才接入自研软件的采集层。第一阶段验收应是持续接收有效帧、显示单帧点云并保存可回放数据。

可复制的申请内容见 [SDK 申请邮件草稿](sdk-request-email.md)。草稿尚未发送。

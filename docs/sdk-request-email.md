# RANGE 2 SDK 试用与开发接口申请草稿

准备日期：2026-10-15（Asia/Shanghai）。**尚未发送。** 请将方括号占位符替换为真实信息后使用；设备 SN 计划于 2026-10-16 拍摄确认，不要猜测或使用示例编号。

官方公开的 SDK 支持邮箱：`customer@revopoint3d.com`。也可从 [官方 SDK 商品页](https://www.revopoint3d.com/products/3d-scanner-sdk-authorization-service) 的 30 天试用入口申请；[官方商店表单](https://store.revopoint3d.com/ia/products/3d-scanner-sdk-authorization-service) 要求姓名、邮箱、国家、型号和 SN。

## 中文版本

**主题：RANGE 2 扫描仪 SDK 30 天试用及逐帧数据接口申请（Windows x64，学术研究）**

Revopoint 技术支持团队您好：

我正在开展“面向三维扫描模型的交互式辅助重建软件设计与实现”课题，计划使用现有 RANGE 2 扫描仪，在 Windows x64 上开发自有桌面软件。首要目标是实时接收逐帧几何数据和 RGB，完成可视化、数据记录以及后续交互式配准和重建。

申请信息如下：

- 姓名：[真实姓名]
- 学校/单位及院系：[真实学校或单位、院系；如不适用请说明]
- 身份及研究用途：[真实身份，例如毕业设计/学术研究，请按实际填写]
- 国家/地区：[真实国家/地区]
- 联系邮箱：[真实邮箱]
- 设备型号：RANGE 2
- 设备 SN：[待核实的真实 16 位 SN]
- 固件版本：[当前版本；设备到位后补充]
- 系统：Windows [10/11，请填写实际版本]，x64
- 预计真机联调时间：[日期或时间段]

我们希望先申请 30 天 SDK 试用。烦请提供适配上述 RANGE 2 及固件的最新 SDK、授权/驱动工具、API 文档和最小可运行采集示例，并协助确认：

1. **逐帧几何数据**：能否直接获取每帧 XYZ 或 XYZRGB？若主要输出深度图，是否可同时读取深度单位/比例、深度/RGB 内参、畸变、深度至 RGB 的外参及无效像素定义，以便我们正确生成点云？可用分辨率、格式和帧率分别是什么？
2. **RGB 与时间信息**：能否获取对应 RGB 帧、帧编号和设备时间戳？深度与 RGB 是否同步，时间戳的单位、精度、来源及丢帧检测方式是什么？
3. **位姿与运动数据**：是否开放逐帧相机位姿、追踪状态、置信度或九轴 IMU 数据？如果不提供位姿，请明确说明，以便我们自行实现配准和追踪。
4. **C++ 与 Python**：Windows x64 SDK 支持哪些 Visual Studio/MSVC 工具集、C++ 标准、CRT 配置和运行库？是否提供稳定的 C API？当前是否仍提供官方 Python 封装，支持哪些 CPython 版本及架构，是否有安装包和示例？如果没有现行 Python 包，是否允许我们自行包装 C/C++ 接口？
5. **连接方式**：USB 和 Wi-Fi 是否都支持同样的数据采集接口？Wi-Fi 模式的设备发现、连接与认证如何配置？官方软件与自研软件是否必须交替使用、独占设备？
6. **申请处理与试用起算**：提交申请后是自动发码还是需要人工审核，通常需要多久、是否有可承诺的处理时限？30 天从申请提交、发放授权、首次激活还是首次连接设备起算？目前设备不在身边，能否先获取资料，在设备到位并完成环境准备后再开始激活？申请或激活是否要求设备现场连接？
7. **离线使用及部署授权**：首次激活后能否离线使用？换电脑或重装系统如何迁移？学术论文及自研代码公开、部署给其他已授权设备，以及随应用再分发必要头文件/DLL 的许可分别是什么？
8. **正式报价**：请提供适用于本学术项目的区域报价、税费和授权条款，说明现有版本支持的设备 SN 数量、增加设备的费用，以及未来 SDK 升级和新机型支持的处理方式。

我们会先验证接口与采集稳定性，再评估正式授权。请同时告知对设备固件、USB 连接、网络、防火墙及运行库是否有特别要求。

谢谢！

[真实姓名]
[真实学校/单位与联系方式]

## English version

**Subject: RANGE 2 SDK 30-day trial and per-frame data access request — Windows x64, academic research**

Dear Revopoint Technical Support Team,

I am working on an academic project titled “Design and Implementation of Interactive Assisted Reconstruction Software for 3D Scanned Models.” We plan to use an existing RANGE 2 scanner with our own Windows x64 desktop application. Our first milestone is to receive per-frame geometry and RGB data in real time for visualization, recording, and subsequent interactive registration and reconstruction.

Application details:

- Name: [actual full name]
- Institution and department: [actual institution and department, or indicate if not applicable]
- Role and research purpose: [actual role and academic project details]
- Country/region: [actual country/region]
- Contact email: [actual email]
- Scanner model: RANGE 2
- Scanner SN: [verified actual 16-digit SN — to be supplied]
- Firmware version: [current version — to be confirmed when the device is available]
- Operating system: Windows [10/11 — actual version], x64
- Expected hardware testing period: [date or period]

We would like to request a 30-day SDK trial. Please provide the current SDK compatible with this RANGE 2 and firmware, the required licensing/driver tools, API documentation, and a minimal working acquisition example. Could you also clarify the following?

1. **Per-frame geometry:** Can the SDK return XYZ or XYZRGB for each frame? If the primary output is a depth image, can we obtain its depth units/scale, depth and RGB intrinsics, distortion parameters, depth-to-RGB extrinsics, and invalid-pixel definitions to construct calibrated point clouds? What resolutions, formats, and frame rates are supported?
2. **RGB and timing:** Are corresponding RGB frames, frame numbers, and device timestamps available? Are depth and RGB synchronized? Please specify timestamp units, precision, clock source, and how dropped frames can be detected.
3. **Pose and motion data:** Does the SDK expose per-frame camera pose, tracking status, confidence values, or nine-axis IMU data? If pose is not provided, please confirm so that we can implement our own registration and tracking.
4. **C++ and Python:** Which Visual Studio/MSVC toolsets, C++ standard, CRT configuration, and runtime dependencies are supported on Windows x64? Is a stable C API available? Is an official Python wrapper currently maintained, and which CPython versions and architectures are supported? Please provide installation packages and examples if available. If no current Python package is available, may we wrap the C/C++ interface ourselves?
5. **USB and Wi-Fi:** Are the same acquisition features available over both connections? How should device discovery, connection, and authentication be configured over Wi-Fi? Must the official software and our application access the scanner exclusively and at separate times?
6. **Application processing and trial start date:** Is the code issued automatically after submission, or is manual review required? What is the typical processing time, and is there a committed turnaround time? Does the 30-day period begin upon application, license issuance, first activation, or first device connection? The scanner is currently off-site. Can we obtain documentation first and activate the trial once the device and development environment are ready? Does application or activation require the scanner to be connected?
7. **Offline use and distribution:** Can the SDK run offline after initial activation? How are computer changes or OS reinstallation handled? Please clarify the terms for academic publications, publishing our own application source code, deployment to other licensed scanners, and redistribution of required SDK headers and DLLs with our application.
8. **Commercial license terms:** Please provide the applicable regional academic quotation, taxes, and license terms, including the number of device serial numbers covered, the cost of adding devices, and the policy for future SDK upgrades and new scanner models.

We would like to validate the acquisition interface and stability before evaluating a permanent license. Please also advise on any required firmware versions, USB setup, network/firewall settings, or runtime components.

Thank you for your assistance.

Best regards,

[actual full name]
[actual institution and contact details]

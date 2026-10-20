# 面向三维扫描模型的交互式辅助重建软件

[GitHub备份范围与恢复方法](docs/backup-and-restore.md) · [可直接查看的研究成果快照](research/snapshots/2026-10-20/README.md)。仓库包含代码、文档与关键成果图；完整扫描数据、运行环境和厂商文件继续在本机单独保存。

[Web 工作台与启动方法](docs/web-studio.md)：在项目根目录运行 `& '.\scripts\start-web-studio.ps1'`，Chrome 打开 **http://127.0.0.1:8877**。现已接入33份工程、模型图层、原始帧回放、6个对应点工作台、22类实验及处理任务；WebGL不可用时可用Canvas兼容绘制。实际Chrome画面仍待核验，已有真实HTTP和CPU像素检查。

[点云数量与内存实测](docs/pointcloud-scale-and-local-interaction.md)：已解包11,932帧、370,243,304次重复深度观测；融合表面另计，使用逐帧融合、空间概览和局部完整点交互。

[2026-10-19 进度存档与转台/保存帧结论](docs/progress-archive-20261019.md)

已有 [对应点配准原型与使用方法](docs/landmark-workbench.md) 和 [离线覆盖、原帧回查与补扫方向](docs/offline-coverage-guidance.md)。[直接片段对齐研究](reports/range2-study-20261018/experiments/cup-direct-split/README.md) 使用同一扫描的训练帧拟合并检查留出帧，保留多组全帧融合候选。

[两工程 463 帧原始深度联合融合](reports/range2-study-20261018/experiments/cup-multi-scan-tsdf/README.md) 已完成单独/联合对照、来源着色和原帧回查；仍有局部冲突，候选尚未替代主结果。[失败工程的分段诊断](reports/range2-study-20261018/experiments/cup-segment-pose-graph/README.md) 保留转轴、几何与颜色尝试及人工审阅入口。

[离线工作流执行原型](docs/offline-workflow-runner.md) 已注册九类确定性工具，实际完成[五步分析链](reports/range2-study-20261018/workflow-prototype-run/index.html)和[三步空间工具链](reports/pointcloud-scale-20261019/workflow-spatial-run/index.html)，保存输入版本、依赖产物、状态与日志。Web原型已接入空间与对齐任务；工程撤销历史和语言模型服务仍待实现。

2026-10-19 追加：[相同原像素的交叉检查](reports/range2-study-20261018/experiments/cup-piecewise-crosscheck/README.md) 发现分段对齐存在阈值敏感与遮挡变化，仍保留为候选；[帧元数据调查](reports/range2-study-20261018/frame-metadata/README.md) 记录了序号重置、跳号和状态反例，尚不能自动恢复真实时间线或据此删帧。

本软件以 **官方扫描软件生成的离线数据包** 为输入。用户已确认解包能力实现；接下来衔接现有解包成果，集中开发重建后处理、高效交互工作流与 Agent 辅助。SDK 实时接入留待本项目完成后探索。

新增 [2026-10-18 扫描研究首页](reports/range2-study-20261018/index.html) 和 [研究记录与复现方法](docs/range2-study-20261018.md)：29 份工程中解出 9,434 帧，完成 26 份独立 TSDF，保留 4,719 张原始 JPEG 与 41,974 次标记观测。支持 [彩色三维审阅](reports/range2-study-20261018/review.html)、[原预览三色对比](reports/range2-study-20261018/comparison/comparison.html) 和 [人偶工程的官方保存融合对比](reports/range2-study-20261018/official-fusion-comparison/comparison.html)。新格式的深度头、位姿、坐标及颜色顺序均与旧四份工程有所区别，须使用新解析器。

本轮还保留了 [物体选区实验](reports/range2-study-20261018/experiments/cup-roi/README.md)、[深度支持/冲突着色](reports/range2-study-20261018/experiments/cup-visibility/review.html)、[翻面组合探索候选](reports/range2-study-20261018/experiments/cup-complementarity/review.html) 和 [固定 0.4 mm 稀疏融合对比](reports/range2-study-20261018/experiments/tensor-tsdf/comparison.html)。实验分别记录选择、变换和参数，保留主基线；更密的表面和更小的内部残差不等同于更高物理精度。

完整处理流程与运行命令见 [从离线工程解包到融合重建：完整链路与使用手册](docs/offline-reconstruction-pipeline.md)，包括数据格式、位姿与坐标转换、TSDF、跨扫描组合、失败扫描修正和三色对比。

想先理解原理，可阅读 [从解包到点云：直观理解版](docs/unpacking-to-pointcloud-explained.md)，用深度快照和相机位置说明数据怎样变成三维点、怎样摆到一起。

新增 [官方与自研三色交互对比](reports/four-scans/comparison/comparison.html)：绿色为双方支持，蓝色为仅自研支持，橙色为仅官方支持；支持容差切换、同步视图和点击点检查。[分析结论](reports/four-scans/comparison/README.md) 表明目前主体几何可复现，但失败扫描底座仍有额外表面，自研基线尚未证明全面优于官方。

设计见 [工作流与 Agent 架构](docs/workflow-agent-design.md) 和 [课题范围](docs/project-scope.md)。现已对本地四份原始工程完成全部 2,498 帧深度、2,500 条保存位姿及 886 条另存全局位姿的读取，生成四份独立 TSDF 模型和跨扫描组合候选。详见 [四份工程实测](docs/four-scan-experiment.md)，可直接查看 [三维交互预览](reports/four-scans/review.html) 和 [多视角总览](reports/four-scans/reconstruction_overview.png)。第一份几何匹配尚未通过，作为身份待确认的对照样例单独保留；失败扫描未整份强行并入。

此前私有仓库书本案例的位姿漏读调查保留在 [位姿恢复实测](docs/pose-recovery.md) 和 [接入契约](docs/recovery-integration.md)。当前已有离线解析、重建、配准脚本、结果审阅和Web交互原型；通用原帧重融合桥接、工程历史与模型 Agent 服务继续开发。

## 已准备的内容

- 已建立项目独立 `.venv`：Python 3.12.14、NumPy 2.5.4、Open3D 0.20.0、Pillow 12.3.0、SciPy 1.18.1，以及可编辑安装的本项目。项目改名后的安装路径已修复并校验。
- 完整离线读取、164 字节与可变长位姿解析、全局配准位姿读取、独立 TSDF 和体素融合、跨扫描配准、组合三角化、原件与 ZIP 完整性校验；原始工程不改写。
- `downloads/`：官方 Revo Scan 6.4.1 Windows 安装包及 RANGE 2 中文快速指南；`manifest.json` 记录来源、大小、SHA256、Windows 签名结果。安装包仅下载，尚未安装。
- 统一点云帧、合成点云源、PLY 回放/导出、Open3D 预览；模拟及回放均明确标识来源。
- [SDK 调研](docs/revopoint-sdk-research.md)、[中英文申请草稿](docs/sdk-request-email.md)、[接口与联调清单](docs/range2-integration.md)。
- [相关 GitHub 项目调研](docs/github-projects.md)：实时驱动、离线逐帧解析、关键帧编辑及重建工作台的证据与适用范围。

## 运行

在本项目根目录打开 PowerShell，直接调用虚拟环境，不需要更改系统执行策略或全局 Python：

```powershell
$env:PYTHONUTF8 = '1'
# 显示合成点云；数据播完后窗口保留，按 Q 或关闭窗口退出。
& '.\.venv\Scripts\python.exe' -m reconstruction_probe

# 无窗口生成并保存最后一帧，单位为米。
& '.\.venv\Scripts\python.exe' -m reconstruction_probe --headless --frames 3 --output-ply data\synthetic.ply

# 回放 PLY。必须根据文件真实单位指定 m 或 mm。
& '.\.venv\Scripts\python.exe' -m reconstruction_probe --source ply --ply data\synthetic.ply --ply-unit m

# 测试和实际 Open3D 文件/渲染检查。
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
& '.\.venv\Scripts\python.exe' scripts\check_environment.py --render
```

渲染检查产生 `reports/environment-check.json` 和 `reports/synthetic-preview.png`，只反映本机图形与点云文件链路，不代表设备精度或实时帧率。CLI JSON 的 `hardware_verified` 为 `false`；尝试 `--source revopoint` 会明确报 SDK 尚未接入。

## SDK 申请

以下材料保留供项目完成后的 SDK 探索使用，当前阶段不继续推进设备实时接入。

[官方 30 天 SDK 试用入口](https://store.revopoint3d.com/ia/products/3d-scanner-sdk-authorization-service#FreeTrial)。若没有跳到表单，点击 **Start Your 30-Day Free Trial**。

RANGE 2 在兼容名单内。表单要求姓名、邮箱、国家、型号和背部 16 位 SN。提交后等官方邮件获取激活步骤/激活码；公开页面没有说明是否人工审批、处理时长或试用起算时间。建议与客服确认发放节奏，设备具备测试条件后再协调激活。

以后开展 SDK 方向时，可使用上述表单或 [邮件草稿](docs/sdk-request-email.md)，索取匹配 **RANGE 2 固件 + Windows x64** 的 SDK、文档和最小采集示例。正式收费条款见调研，当前没有购买或提交申请。

## 换电脑或重建环境

本次 `.venv` 使用 Codex 随附的稳定版 Python 3.12，依赖该运行时路径继续存在。系统默认 `python` 当前为 3.13.0rc2。之后重建时优先指定已安装的稳定版 x64 Python：

```powershell
& '.\scripts\setup.ps1' -Python 'C:\path\to\stable-python\python.exe'
```

`setup.ps1` 只创建/安装项目虚拟环境。已有虚拟环境时会复用它；若要更换基础 Python，先自行重命名已有 `.venv`，再运行该命令。`requirements-windows-py312.lock.txt` 记录本次 Python 3.12 Windows 环境的依赖版本，供复现使用，不保证适用于厂商未来提供的 Python 绑定。

重新下载准备包可运行 `scripts/download-official.ps1`。最新软件地址以 [官方下载中心](https://www.revopoint3d.com/pages/support-download) 为准。

`vendor/`、下载软件、授权文件、设备 SN 本地配置、点云数据与运行报告不纳入版本控制。`config/range2.example.json` 只是待核对配置清单，当前程序不会把它当成已生效的设备配置。

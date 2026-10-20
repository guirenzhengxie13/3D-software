# 当前交接与续接入口

更新：2026-10-20。项目根目录为 `G:\project\revopoint software`。远端为 `guirenzhengxie13/3D-software`，目前只有 `main` 分支，备份基点 `045405236c7fcf1ba12a2d71dd2fca8b2406495f`。

## 用户最新要求

1. 准备handoff后继续研究。
2. 网页点云全部无法显示，优先修复真实数据到界面的完整链路。
3. GitHub README中指向未上传文件的404链接先移除。
4. 提高网页集成度，减少分散入口。Git当前只有main；主要混乱来自页面与实验候选分支，不能擅自删除研究结果来“清理”。

## 固定范围

官方Revo Scan负责采集，本项目从离线工程包开始，处理解析、重建后处理、交互工作流和后续Agent工具层。SDK/实时读取后置。原始扫描、解包数据和主基线不覆盖。

## 已有数据和实现

- 33份新旧工程，共11,932帧、370,243,304次重复深度观测；新批26份主融合表面合计2,047,250点。
- 默认彩色人偶精细模型793,214点，概览39,141个实际原顶点；同源官方融合533,469点。
- Web入口 `http://127.0.0.1:8877`，启动 `& '.\scripts\start-web-studio.ps1'`。
- Web前端 `web/studio/`，本地HTTP后端 `src/reconstruction_probe/web_studio.py`。
- 有6个对应点工作台、22类实验、逐帧回放、空间预览/索引/局部点、固定任务及日志。
- 真实空间任务 `ccde9d7d48704057` 与已有候选对齐任务 `a3cdecd17c1e4f31` 完成。自动回放已有候选不是人工选点。
- 前次123项Python检查、Node数值/模拟控制、HTTP和CPU像素检查通过；这些没有证明实际Chrome页面可用，用户本次明确反馈仍全部不显示。

## 当前发现：渲染输入字段冲突

后端模型元数据使用 `points: 整数点数`，真实点坐标在base64字段 `xyz`。前端 `PointViewer.setClouds` 却用 `row.points || decode(row.xyz)`，把非零整数优先当成坐标数组，触发“点云数组格式不完整”。原回归只喂了typed-array，没有将真实HTTP响应接到真实viewer，因而漏过。

本次已修复：前端只把数组视为直接坐标，标量点数不再遮蔽base64；后端几何响应移除了歧义的 `points` 标量，目录仍以该字段记录点数。新增回归先复现原代码失败，再验证修复。下次续接仍须以用户实际显示情况确认Chrome状态，不能仅凭离线检查宣布实机显示成功。

## 本次完成与证据

- README已重写，保留5个存在且会入库的文档/快照链接，不链接未上传的reports。
- 顶层导航为工程工作区、实验与证据、处理任务；模型/保存帧/对应点共用当前工程与工作模式，离开再返回时保持模式。
- 对应点任务按工程归属展示，可以选择目录中两份模型建立新工作台。实验的主要结果优先，其他研究视图折叠；不删除旧候选，也不创建新Git分支。
- 新增真实HTTP到真实viewer的集成检查：`scripts/check_web_render_pipeline.py`。8例实际数据均产生非空CPU像素，包含精细人偶、官方融合、主基线、扫描预览、联合融合、失败扫描片段和两份保存帧。
- 本机证据：`reports/web-studio/render-fix-20261020/summary.json` 与 `contact.png`。图像明确不是Chrome截图。
- 随Git保存的简短方法和结果图见 [渲染修复验证](research/verification/2026-10-20-rendering/README.md)。
- 真实自选模型工作台任务：`63058f8db1b04a05`，固定官方533,469点，移动精细自研793,214点，归属彩色人偶工程。现有与新建共7个工作台、21个CPU视图非空。
- 当前123项Python检查通过，Node检查覆盖标量字段冲突、项目模式保持、PLY导入、选点/父页面提交与实际CPU像素。
- Chrome实机/GPU仍未通过工具验证。若用户刷新后仍报错，优先定位其实际入口、页面报错、资源加载和尺寸；不能再次只跑孤立的HTTP或数组mock后宣称修好。

## 优先工作与验收

1. 继续以真实payload连接实际viewer检查，保持此次输入字段冲突回归。
2. 确认用户实际Chrome入口与显示效果，检查实际资源/Canvas尺寸/GPU回退；初始化和绘制异常有可见提示。
3. 后续逐步让旧对应点/研究审阅也复用统一viewer，减少独立页面实现。保留已有研究输出。
4. 衔接通用对应点变换→明确帧归属→原深度重融合，不把已生成对齐PLY冒充重融合完成。
5. 工程状态与撤销历史、区域选择、Agent工具层继续开发；保持main上的清晰提交。

## 数据位置、备份与约束

- 原工程：`%APPDATA%\Revopoint\RevoScan6\Projects`，另有 `item/`。
- 新批研究：`reports/range2-study-20261018`；规模研究：`reports/pointcloud-scale-20261019`；Web任务：`reports/web-studio/runs`。
- 完整reports、原始扫描、虚拟环境、厂商代码/授权不上传公开GitHub。仓库保留代码、文档与 `research/snapshots/2026-10-20` 的研究快照。
- Git写入需要工具的受控提权，正常沙箱不能创建 `.git/index.lock`。提权执行时使用每条命令的精确 `-c safe.directory='G:/project/revopoint software'`，避免改全局信任设置。
- 浏览器工具曾拒绝file协议，禁止用其他浏览器接口、CDP或localhost绕过该次浏览器限制。普通本地HTTP集成和离线渲染代码检查可以做，但不能冒充Chrome截图。
- 没有转台逐帧遥测或可信采集时间；没有独立几何真值。通用对应点到任意片段原帧融合的桥接、工程撤销历史、模型Agent服务仍未完成。

## 可复现检查

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests
& 'C:\Program Files\nodejs\node.exe' tests\check_web_studio.cjs
& 'C:\Program Files\nodejs\node.exe' tests\check_point_viewer_cpu.cjs
& 'C:\Program Files\nodejs\node.exe' tests\check_landmark_workbench.cjs
# 本地服务运行后，将真实HTTP数据交给实际viewer并检查CPU像素。
& '.\.venv\Scripts\python.exe' scripts\check_web_render_pipeline.py --port 8877
```

真实HTTP检查会使用本机研究数据并可能另存任务，先读 `scripts/check_web_studio_live.py`。后台服务重启仅操作自己启动的 `serve_web_studio.py --port 8877`，不要影响其他本地服务。

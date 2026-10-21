# 当前交接与续接入口

## 2026-10-21 本轮同步与研究（当前入口）

以下状态优先于后续历史记录；旧机与另一台电脑的原记录保留。

### 同步与源数据

- 当前工作根为 `G:\project\revopoint software`。从共享目录收到另一台电脑检查点 `20261020T152813Z-cd7578`，17份文件SHA全部匹配；15份代码/文档已先独立提交并推送为 `37de939`，另外两份本地展示证据保留在reports。原件快照在 `.cache/heartbeat-20261021/incoming/`，没有用GitHub旧版本覆盖它们。
- 开始与提交前均检查GitHub，远端没有额外的并行提交；本轮源代码、文档和精简验证作为main上的后续提交同步。具体本轮提交及读回结果保存到 `reports/web-studio/sync-20261021/git-sync.json`。
- 扫描原件实际已移动到 `G:\revo data`。旧AppData目录只余GlobalMarkerLibrary，不能因父目录存在就认为原扫描仍在那里。新增明确的只读外部路径映射，本机 `config/path-mapping.local.json` 已设置，且被Git忽略。迁移机器仍默认使用 `data/revo-scan-projects`，不要复制本机配置覆盖另一台机器。
- `scripts/check_source_relocation.py` 已对29工程快照列出的388份原文件、3,031,514,347字节逐份重算SHA，全部一致。官方533,469点融合也匹配原记录SHA。报告 `reports/web-studio/sync-20261021/source-relocation.json`。没有改写原件、历史索引、候选JSON或原位姿。
- 同时修复原采集机器的AppData只读访问、已知C盘续接目录与UNC旧路径识别、配置覆盖优先级；别名哈希键冲突会拒绝。未生成的可选fuse/preview不再误报为复制失败；真实损坏和缺帧仍会显示。

### 新增真实执行链路

- 已实现 **单一保存工程、两个显式片段** 的 `build_fragment_plan_from_alignment.py` 与 `fragment_bridge.py`。工作台会话重新核验原模型SHA、原点或已有候选；绑定文件明确原帧ID、保存扫描毫米坐标依据、选择说明和可选ROI。不能根据PLY文件名或显示行号自动推断帧归属。
- 固定工作流现在11个工具，新增 `fragments.plan` 与 `fragments.fuse`，可通过依赖引用运行控制组和校正组。当前要求每个选中帧有有效depth和 `pose_optimized.npy`；未自动退回其他位姿。
- 计划记录每份深度/位姿的SHA，融合前后核对固定输入。计划和索引SHA由实际解析的原字节计算；引用输入验证后保留预期SHA，修复了“期间换版后再次取hash被记为新基线”的空隙，新增并行换版回归。
- 最终真实验证位于 `reports/web-studio/sync-20261021/final-bridge/`，238份输入固定。失败杯子 `scan_20261018131222` 的目标31帧、源83帧，共114帧，积分3,611,081次ROI前有效深度观测；另外222条记录保留。帧号有间断，不能以ordinal替代原始ID。
- 两组使用相同帧及原ROI像素摘要 `5c899c637d54df68f358d9bcdb597689ce32b97a08f0d2031de2cd8a8e621736`。原位姿组67,226点、校正组66,376点；与各自之前冻结结果的全部点双向最近邻最大差均0mm。**这是新执行链路的忠实复现，没有新的物理精度/几何改善结论，没有人工选点，也没有修好336帧整份失败扫描。**
- 早期测试输出保留在 `reports/range2-study-20261018/experiments/fragment-bridge-20261021/` 及其verified目录；当前实验统一进入 `current-review.html`，不需在多份试验页面中猜选。

### 展示与验证

- 本地软件 `http://127.0.0.1:8877`；本轮仅重启自己的8877服务，先检查无运行任务。模型、保存帧和实验目录均正常提供；启动命令仍为 `scripts/start-web-studio.ps1`。
- 新双栏网页复用同一PointViewer、原点选择与CPU光栅代码，支持联动相机、视角、伪彩、兼容显示与原点编号。当前入口：`/reports/range2-study-20261018/experiments/fragment-bridge-20261021/current-review.html`。最终工作流含日志、配方、输入输出哈希。
- 两组分别显示39,032/38,741个原顶点，CPU可见像素49,545/47,791；新页面全部4段可执行脚本语法通过。最终154项Python测试、3项Node回归、compileall、diff空白检查通过。另8例真实HTTP→实际viewer→CPU像素通过，报告 `reports/web-studio/sync-20261021/http-render/`。
- 本轮不宣称新增Chrome/GPU验证；下方另一台电脑已有的浏览器观察保留其原日期和来源。11932帧的目录存在性统计不等于本轮已逐份解析所有NPZ/4719份JPEG。
- 可随仓库查看的精简结果、图与测试边界：[2026-10-21验证](research/verification/2026-10-21-fragment-bridge/README.md)。完整使用方法：[对应点结果到原帧重融合](docs/fragment-fusion-bridge.md)。

### 下一阶段

1. 在工程工作区添加显式帧归属与坐标依据编辑，连接已核验对齐结果到计划预览/执行；显示缺失优化位姿与重复归属，先审阅再运行，不能让任意PLY自动“拥有”原帧。
2. 加入工程派生历史与撤销（切换派生版本，不删原件）；减少同结果多入口。跨工程通用桥接仍需单独的坐标契约。
3. 失败杯子其余连接仍需交互对应点、原深度留出和局部冲突证据；不要把此次链路复现写成新的重建效果提升。Agent仍是固定工具底座，未连接语言模型服务，SDK继续后置。
4. 另一台电脑续接前先保存自己的未提交文件，核对37de939检查点，再fetch/比较main；共享目录已有本轮新改动，旧同步哈希会阻止覆盖，必须先合并，不能reset/force覆盖。



## 持续研究检查点（2026-10-20 23:20）

### 已验证并准备第二轮同步（23:28）

- 首轮检查点 `20261020T151944Z-3e5904` 已成功回写网络，7文件读回SHA一致，网络原内容留有备份。不是等额度耗尽才尝试保存。
- 显示控制已实现：原始色、视深/高度伪彩、图层和单色共5模式，正面/侧面/顶面/透视4视角，1万/4万/6万概览预算。默认增亮1，统一灰模型有明确说明，原RGB/原编号不变。真实浏览器中同一工程03、Canvas兼容模式已验证58,156点的6万预算视深伪彩，截图 `reports/web-studio/local-demo-20261020/display-controls-browser.jpg`。
- 新 `path_mapping.py` 精确映射旧英文/中文G根、P根和旧AppData扫描根。Web索引、官方模型、旧任务、LOD、工作台HTML数据和POST会话均运行时迁移；历史文件不改写。旧未结束任务在内存中标记interrupted，不阻止新任务。
- 服务已重启接入。当前目录快照33工程、11,932索引帧、89模型、3工作台；彩色人偶可同时找到精细自研793,214点、主基线139,848点、官方预览56,172点、官方融合533,469点。数据仍在复制，数量会增长；帧存在性计数不等于完整载荷校验。
- 最新全套Python137项通过；Node控制器与真实CPU/WebGL颜色上传回归通过，覆盖5模式不修改原RGB/ID、视深随旋转更新、预算重载和缺失默认工程回退；diff空白检查通过。
- 下一阶段桥接研究记录在 `docs/fragment-fusion-bridge-next.md`。通用来源绑定→片段计划→原深度重融合尚未实现；其他历史CLI未统一接入路径映射。不要把新增显示选项、路径恢复或表面对齐当作该闭环完成。

用户要求根据 handoff 持续研究到额度限制，并测试耗尽前是否保存/同步研究进度。已建立持续目标；采用阶段检查点主动同步，不依赖额度耗尽时才触发收尾。

- 用户标注工程03白点且选项少。真实 PLY 的171,360个顶点RGB全部为 `[165,165,165]`；前端默认增亮1.8把165截到255，故白色。不是Canvas回退丢色。正在加入原色/高度/深度等明确区分的显示模式、视角与显示点预算控制。
- 同时实现历史绝对路径的运行时映射、旧任务/官方模型/工作台恢复与显式目录刷新；不改写历史报告原字节或SHA。尚在实现和测试，不能把以下旧机可用选项数量当成本机已恢复。
- 新增 `scripts/sync_network_checkpoint.py`：仅同步明确选定或Git中改动的代码/文档/证据，不传递删除，不写虚拟环境/扫描原件；网络文件须匹配Git基线或上次同步哈希，独立修改会阻止覆盖。每次替换备份原内容，并读回核对SHA。检查点日志为 `.cache/continuation-sync/latest.json`，网络备份为 `P:\revopoint software\.cache\continuation-sync/`。
- 首轮先同步已知进度和交接；后续每批功能通过检查后再同步。新研究产物另存新目录，保留失败结果，持续更新本节。

## 本机续接：2026-10-20

### 当前展示状态（2026-10-20 23:05，优先于下方早期移机记录）

- 用户要求直接在 Codex 展示当前软件，可先用已经完整复制的真实数据。已启动 `scripts/serve_web_studio.py --port 8877`，入口 `http://127.0.0.1:8877`；Codex 内嵌浏览器标签已标记为保留的展示结果，当前显示彩色人偶的模型页。
- 程序/附属文件复制成功，Robocopy 状态 3、失败 0；扫描原件复制成功，状态 1、失败 0，共 393 文件、3,044,547,535 字节。之前两份 `frames.dataset` 的 ERROR 64 已重试成功。完整 `reports/` 仍在后台复制，最终状态继续看 `.cache/migration-20261020/copy-final-status.json`。
- 已完整验证早期四份融合模型：`scan_01` 61,417 点，`scan_02` 76,339 点，`scan_03` 171,360 点，`scan_04` 170,856 点。对应复制分批日志成功结束，文件长度、全部坐标与稳定性检查通过。
- 优先复制并核对彩色人偶 `scan_20261018122607` 的精细模型：793,214 点，21,417,153 字节，源流与本地 SHA256 一致 `16a3ef2355ee1ad7778dbe93543d9d1adb70376ecf8b2aa0703a1fd88a9d8d33`。位于 `reports/range2-study-20261018/experiments/tensor-tsdf/reconstruction/scan_20261018122607/tsdf_pointcloud_mm.ply`。
- 人偶索引563帧，但目前只优先保证 ordinal 0 的 `frame.npz` 与 optimized/stored 位姿完整。浏览器已显示该帧 25,000/36,230 个有效深度点；早期 `scan_02` 的 ordinal 0/1 也可读取。列表中的工程数、帧总数来自索引，不能当作数据全量已复制。
- 本次确实在 Codex 的实际浏览器观察到彩色点云和保存帧，已实际旋转、缩放、调亮及查看原顶点编号，显示徽标为 WebGL；未进一步验证物理 GPU 型号或硬件加速来源。模型概览显示39,141个原顶点，完整模型仍为793,214点。
- 仅修改产品文件 `web/studio/style.css`：新增≤600px响应规则，修复窄侧栏导航和工具栏文字竖排，缩短工程选择区并保留有效画布。实际窄屏和随后自然展开的桌面布局均已观察；`git diff --check` 通过。
- 实机截图和简短证据：`reports/web-studio/local-demo-20261020/model-browser.jpg`、`frame-browser.jpg`、`verification.json`。本次是本地展示与界面小修，尚未回写网络项目；后续回同步时包含 CSS、交接文档及需要保留的截图证据。

用户要求：另一台电脑额度用完，先把项目与扫描数据复制到本机、熟悉项目并继续开发；开发完成后同步回网络项目目录，必须补写 handoff。用户授权直接安装、配置本机依赖，无需 VS Code；本机新建 Python 环境，不搬旧虚拟环境。

- 本地主工作目录：`C:\Users\5gvs4\Documents\my project\revo software`。
- 网络项目与最终回同步目标：`P:\revopoint software`（`\\192.168.1.105\project\revopoint software`）。
- 扫描原件网络目录：`Q:\revo data`；本地复制目标：`data/revo-scan-projects/`。
- 接手基线：源仓库 `main`，工作区干净，HEAD `7676c02`（`Fix cloud payload rendering and unify project workspace`）。
- 核心代码已复制并与源提交核对；Git 历史从同一公开仓库恢复到完整提交 `7676c026eec48675588fa15d23cc989433085bae`，连通性检查通过。当前完整研究报告和扫描数据仍在复制；以下旧机验证不能视为本机验证。
- 本机独立 `.venv` 已建立，Python 3.12.14；锁定依赖安装完成，包括 NumPy 2.5.4、Open3D 0.20.0、Pillow 12.3.0。editable 安装指向本地 `src/`，`pip check` 通过。
- 本机 123 项 Python 测试通过，`check_landmark_math.py` 的 80 组 NumPy SVD/JavaScript 求解交叉检查通过。三项 Node 检查亦通过：`check_web_studio.cjs`、`check_point_viewer_cpu.cjs`、`check_landmark_workbench.cjs`。这些包含临时合成 HTTP 服务、DOM/Canvas 与 CPU 检查，尚未验证本机真实扫描 HTTP 数据、实际浏览器或 GPU。
- 已确认旧报告含 `G:\project\...`、旧扫描目录、任务目录和工作台会话绝对路径。产品尚无统一路径映射；不要批量改写历史 JSON/HTML，以免破坏已有 SHA256 引用。
- 已有显式片段计划到原帧 TSDF 重融合底座；仍缺通用对应点工作台到帧归属计划、重融合和工程撤销历史的交互闭环。本轮先接手与配置，不把这些功能写成已经完成。

完整迁移问题、路径表和回同步要求见 [本地续接与移机记录](docs/local-continuation-20261020.md)。复制日志保存在 `.cache/migration-20261020/`。本机依赖和 Git/Node 可执行文件来自 Codex 自带运行时，旧机的提权规则、安装位置与浏览器工具限制仅作来源记录，不能当成本机当前检查结果。

数据复制当前由后台进程继续。已出现两份 `frames.dataset` 的 Windows ERROR 64（网络名称不再可用），所以不能把目录已创建或大小非零视为复制成功。`.cache/migration-20261020/finish_copy.py` 已启动：等待项目、扫描原件、报告三部分任务结束，失败部分最多再补拷两轮，并将最终成功/失败及重试结果写到 `.cache/migration-20261020/copy-final-status.json`，最后自动追加到本文件末尾。续接先读这个状态；若仍为 `copying`，先确认对应进程与日志，不要启动重复的大批复制。该任务仅回写本地 handoff，尚未向网络项目同步本轮文档。

回同步前必须先核对网络端是否出现并行改动，再合并、同步代码/文档/需要保留的新结果并复查 handoff；不使用镜像删除，不覆盖扫描原件，不把本机 `.venv` 或本机专属路径配置覆盖到旧机。后续每次收尾都更新本节的真实状态。

## 上轮来源记录（旧机器）

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

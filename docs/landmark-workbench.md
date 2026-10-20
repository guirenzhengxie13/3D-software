# 片段对应点配准原型

2026-10-20：已接入[Web工作台](web-studio.md)，可在Chrome通过本地HTTP选择已生成页面、查看模型文件、兼容绘制，并直接提交后端另存对齐结果。开发模板 `web/landmark-workbench/index.html` 不含模型，不能当成已生成工作台打开。

此原型承接离线研究中的多候选问题：自动配准可能有几个合理的位置，用户可以直接指出两个片段上的同一位置，再检查对齐。它是独立的离线 HTML 工具和 Python 后端，统一工程编辑器与模型 Agent 层仍待接入。

本次入口：[对应点工作台](../reports/range2-study-20261018/experiments/cup-direct-split/landmark-workbench.html)。用支持 WebGL 的浏览器打开。实际 GPU 画面尚未在当前受限浏览器中验证；数值、导入导出和交互状态已经做程序检查。

## 页面如何使用

1. 左侧是固定片段 0，中间是原坐标的移动片段 1，右侧是当前对齐预览。
2. 可以先切换已有候选。移动片段单独视图保持原始坐标；候选变换只作用于右侧叠加预览。
3. 按住 Alt 单击固定片段上的一点，再在移动片段中单击同一物理位置。也可开启“点选模式”。普通拖动旋转，Shift 拖动平移，滚轮缩放。
4. 至少选择三对不共线的点。优先选杯柄连接处、明确的边缘或纹理交界等有辨识力的位置，分散覆盖物体；不要把杯口与杯底当成同一个位置。
5. 点击“计算刚体对齐”，检查叠加结果和每对残差。选点残差只描述这些对应点，不能代表整个模型精度。工具不拟合缩放或镜像。
6. 需要改点时移除对应对或撤销上一对。修改了已求解的选点后，导出会暂时禁用，直到重新求解或恢复已有候选，防止旧变换配上新选点。
7. 导出 `alignment-session.json`。可以在同一页面重新载入；原文件哈希、单位和预览选点编号必须匹配。

点选使用预览抽样，但每个显示点保留原 PLY 的顶点编号。后端会读取完整原模型，核对该编号与坐标，从原始精度坐标重新求解。

## 导出后交给现有重建程序

在项目根目录 PowerShell 运行。以下假定把导出的 JSON 放在 `data/alignment-session.json`；结果目录使用新的空目录。

```powershell
$prepared = 'reports\range2-study-20261018\experiments\cup-direct-split'

& '.\.venv\Scripts\python.exe' scripts\apply_landmark_alignment.py `
  --session 'data\alignment-session.json' `
  --out 'reports\manual-landmark-alignment'
```

手工对应点输出的候选名称是 `manual_landmarks`。如果导出的是已有候选，则名称形如 `selected_direct_best_training`，程序会核对已有候选文件的哈希及矩阵，而不是把它冒充成手工选点结果。

可选的 `--refine-icp` 会另外保留一个 `manual_landmarks_icp` 候选。初始对应点变换仍保留；ICP 残差是同表面拟合指标，不是独立精度结果。

```powershell
& '.\.venv\Scripts\python.exe' scripts\reconstruct_direct_group_candidates.py `
  --prepared $prepared `
  --registration 'reports\manual-landmark-alignment' `
  --labels manual_landmarks `
  --out 'reports\manual-landmark-reconstruction'
```

这一步把组 1 的每帧位姿左乘对应点变换，保持组 0 不变，然后用同一原始 ROI 深度像素重新融合。原工程、原位姿和主基线均不覆盖。输出含 PLY、网格、三维审阅页、变换与参数记录。

## 导出数据结构

```text
format_version: 1
kind: manual_landmarks 或 existing_candidate
unit: mm
source / target:
  path、sha256、group_id_high
prepared_path: 对应片段研究目录
candidate_reference: 已有候选记录路径与 SHA256
point_pairs:
  source: 原点编号 id、预览坐标 xyz
  target: 原点编号 id、预览坐标 xyz
transform_source_to_target: 4×4 行优先刚体矩阵
fit: 选点残差等描述
```

手工选点时后端验证原点编号、内容哈希、预览舍入误差及刚体变换，并以原始坐标重新计算。错误哈希、重复编号、错误点坐标、非刚体矩阵或与选点明显矛盾的变换会明确失败，不生成冒充成功的结果。

## 已做验证

- 浏览器四元数求解与 Python SVD 独立实现交叉检查 80 组，包含三点、共面点和带噪声对应；另有反射、共线和遮挡选点控制。
- 模拟 DOM/WebGL 检查初始化、导入求解导出、旧结果失效、失败导入保留状态、左右选点顺序。模拟检查不能替代实际 GPU 渲染。
- 合成数据验证 JSON → 完整原点核对 → 新 PLY，并检查可选 ICP 保留初始解、错误哈希在输出前拒绝。
- 自动回放真实已有候选，输出 PLY 与此前记录的候选逐字节相同；没有伪造人工对应点。见 [验证记录](../reports/range2-study-20261018/experiments/cup-direct-split/workbench-validation.json)。

复现检查：

```powershell
& '.\.venv\Scripts\python.exe' scripts\check_landmark_math.py
& 'C:\Program Files\nodejs\node.exe' tests\check_landmark_workbench.cjs
& '.\.venv\Scripts\python.exe' scripts\check_landmark_session_roundtrip.py
```

Agent 后续可以使用同样的选点/变换 JSON 和确定性处理工具，提出候选并解释差异。当前没有接入模型服务，也没有让 Agent 代替用户确认真实物理对应点。

## 任意两个已知单位的离线点云

现在也可以把两个普通 PLY 传给工作台，不要求它们来自最初的两组 ID。必须确认文件坐标单位为毫米；程序不从物体尺寸猜单位。

```powershell
& '.\.venv\Scripts\python.exe' scripts\build_landmark_workbench.py `
  --target-cloud 'data\fixed-mm.ply' --source-cloud 'data\moving-mm.ply' `
  --target-fragment-id 1 --source-fragment-id 2 --unit mm `
  --out 'reports\pair-workbench.html'
```

未指定已有配准时，程序另存初始单位变换候选表。可用 `--registration 目录` 导入包含 `summary.json` 的既有候选。导出会同时记录候选表哈希，避免同名候选后来被改写而仍被误用。

这种通用模式记录 `fragment_id`，`group_id_high` 和 `prepared_path` 可以为空。后端 `apply_landmark_alignment.py` 仍能核对并生成对齐点云，但最初的 `reconstruct_direct_group_candidates.py` 专用于原两组 ID 研究，不能直接拿它重建任意通用片段；接回原帧时还需明确每帧所属片段。

已有四处失败片段的[实际工作台](../reports/range2-study-20261018/experiments/cup-segment-pose-graph/manual-workbenches/README.md)。颜色后续检查发现其中 4→3 保留原始关系较合理，页面仍保留原自动失败候选供对照。

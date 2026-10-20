# 可执行的离线重建工作流

目前已有确定性任务执行原型：把融合、证据分析、原帧回查、空间预览和局部完整点读取工具串成配方，自动记录步骤状态、输入版本、产物哈希和日志。它没有连接语言模型；后续界面和 Agent 可以调用同一套工具。当前共九类已注册工具。

已用真实扫描完成[五步工作流](../reports/range2-study-20261018/workflow-prototype-run/index.html)：来源证据 → 互补区域回查 → 冲突区域回查 → 像素邻域 → 局部表面距离。此次用 1,000 个表面样本验证执行链；完整研究使用的 40,000 点诊断另行保留，不能混用抽样统计。

## 使用

项目根目录 PowerShell：

```powershell
# 查看实际可调用工具与参数范围
& '.\.venv\Scripts\python.exe' scripts\run_reconstruction_workflow.py --list-tools

# 只核对配方与固定输入版本，不启动计算
& '.\.venv\Scripts\python.exe' scripts\run_reconstruction_workflow.py `
  --plan 'reports\range2-study-20261018\workflow-prototype-plan.json' --validate-only

# 输出必须是 reports 下尚不存在的新目录
& '.\.venv\Scripts\python.exe' scripts\run_reconstruction_workflow.py `
  --plan 'reports\range2-study-20261018\workflow-prototype-plan.json' `
  --out 'reports\workflow-run-new'
```

结束后生成 `index.html`、`state.json`、`plan.json`、`logs/` 及每个步骤独立的 `nodes/步骤编号/`。失败时保留已完成结果和错误日志，停止后续步骤。当前没有自动续跑；可用新输出目录重跑或另写剩余步骤配方。

## 配方结构

```json
{
  "format_version": 1,
  "name": "检查联合重建中的互补区域",
  "nodes": [
    {
      "id": "evidence",
      "tool": "multi_scan.evidence",
      "parameters": {
        "fusion": "reports/range2-study-20261018/experiments/cup-multi-scan-tsdf",
        "max_points": 1000
      }
    },
    {
      "id": "trace",
      "tool": "multi_scan.trace",
      "parameters": {
        "fusion": "reports/range2-study-20261018/experiments/cup-multi-scan-tsdf",
        "evidence": {"node": "evidence", "path": "."},
        "category": "source_only"
      }
    }
  ]
}
```

步骤依次执行，依赖只能引用更早步骤。引用路径必须留在该步骤输出目录内。外部相对路径以项目根目录为基准。

可选 `input_sha256` 是“输入文件路径 → SHA256”的映射，用于固定既有版本。实际示例配方已经固定联合融合的摘要版本。运行前及每一步执行前检查这些固定输入；每次使用前序输出，还核对该步骤全部产物的哈希，避免旧选点或旧分析套到改变后的模型上。

## 已注册的工具

| 工具 | 输入 | 新产物 |
| --- | --- | --- |
| `multi_scan.fuse` | 解包研究目录、已有配准记录 | 两份单独与联合原深度融合、来源贡献、对照 |
| `multi_scan.evidence` | 联合融合目录、抽样数量 | 逐来源支持/冲突/遮挡、原顶点编号、三维着色 |
| `multi_scan.trace` | 融合与证据目录、类别或点编号 | 具体工程、帧、深度像素、对齐颜色与数值 |
| `multi_scan.pixel_sensitivity` | 融合与证据目录 | 像素邻域分歧和原冲突的分别统计 |
| `multi_scan.local_planes` | 融合与证据目录 | 轴向差、局部法向差和未合格平面 |
| `landmarks.align` | 工作台导出的对应点会话 | 核对原点后的对齐候选、可选独立 ICP 候选 |
| `cloud.preview` | 完整点云、明确毫米单位、显示预算 | 绑定原顶点编号的空间预览 |
| `cloud.index` | 完整点云、毫米单位、空间块尺寸 | 每个有效原顶点保留一次的磁盘索引 |
| `cloud.region` | 索引、原顶点编号列表、毫米半径 | 多个局部范围内的精确原顶点并集 |

新增空间工具已完成[真实三步运行](../reports/pointcloud-scale-20261019/workflow-spatial-run/index.html)。配方中 `vertex_ids` 是1–64个不同的原模型编号，不能使用预览行号；毫米参数必须有限且为正。具体使用方法见[点云规模与局部交互](pointcloud-scale-and-local-interaction.md)。

融合工具当前专用于已支持的两工程实验格式，尚不是任意扫描集的通用工程管理器。所有工具使用固定脚本和参数列表，配方不能指定任意脚本或 shell 命令。工具产生候选，不自动把“计算完成”解释成“重建正确”。

证据分析可以使用独立输出目录，再通过 `--evidence` 交给回查、邻域和局部平面工具。它们会核对该证据确实属于同一个融合版本，旧结果不会仅因目录结构相似而被接收。

## 取消、失败与检查

`--cancel-file 'reports/cancel.request'` 指定取消标记。创建该文件后，执行器完成当前步骤，在下一步骤开始前停止，保留已完成产物。当前没有实现强行终止正在运行的几何子进程；界面不能把它标成即时取消。

单元控制覆盖输入版本改变、依赖产物改变、未知工具、参数越界、路径逃逸、失败中止、步骤间取消及含空格路径。真实五步链路已全部完成，每步产物和依赖哈希另有总体验证。实际 GPU 显示仍未验证；任务执行成功不代替画面或几何质量审阅。

接下来仍需统一项目编辑器、交互命令与版本选择，再接入模型服务的工具调用与结果解释。现有执行器解决的是可重复运行与可检查记录，没有替用户完成真实物体对应关系的判断。

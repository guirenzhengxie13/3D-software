# 面向三维扫描模型的交互式辅助重建软件

官方 Revo Scan 负责采集，本项目读取离线工程，进行深度/位姿解析、点云融合、片段配准和交互辅助重建。软件从本地 Web 工作台开始，SDK 与实时设备读取后置。

## 启动 Web 工作台

已有本项目运行环境时，在项目根目录执行：

```powershell
& '.\scripts\start-web-studio.ps1'
```

Chrome 打开 `http://127.0.0.1:8877`，保持服务终端运行。不要把 `web/` 中的开发模板当作带数据的结果页面直接打开。

新环境建议使用稳定版64位Python 3.12：

```powershell
py -3.12 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-windows-py312.lock.txt
& '.\.venv\Scripts\python.exe' -m pip install -e .
& '.\scripts\start-web-studio.ps1'
```

## 软件入口

顶层入口收拢为工程工作区、实验与证据、处理任务。工程内切换模型、保存帧和对应点，使用同一工程上下文。

- **模型**：空间预览、图层叠加、本地PLY浏览、原点编号和局部完整点。
- **保存帧**：反投影保存深度，结合保存位姿查看逐帧点云与深度图；不假定真实采集时间。
- **对应点**：选择固定/移动模型，保存和恢复未完成选点草稿，核验刚体变换；显式绑定原帧，审阅输入后运行原位姿与校正位姿两组重融合。
- **实验与任务**：保留融合候选、失败尝试、来源证据、处理参数、日志与状态。

当前没有连接语言模型Agent服务。同一工程的显式帧归属、对应点核验与原深度重融合已接通网页、CLI和固定工作流。模型组合可保存为固定版本，切换支持撤销重做；跨工程通用绑定与完整参数/帧编辑历史仍在开发。

## 数据与验证边界

本机研究覆盖33份新旧工程，共11,932帧、370,243,304次有效深度观测；观测包含大量重复，不能当成同样数量的独立表面点。已有独立融合、原两片段358帧演示和两次扫描463帧联合融合，仍保留孔洞、重影与冲突。

用户反馈网页点云未显示后，已定位真实接口的标量 `points` 点数字段被前端误当坐标数组的问题。修复通过“真实HTTP数据 → 实际viewer代码 → 像素”检查；此前数值、HTTP或模拟DOM检查不能单独证明Chrome画面可用。最新状态以交接文档为准。

## 仓库内容

```text
src/reconstruction_probe/   数据、几何、工作流与本地HTTP后端
web/                       Web界面、对应点和共享点云绘制
scripts/                   解包、重建、分析、启动与验证
tests/                     数值、数据契约与交互回归
docs/                      方法、设计和使用说明
research/snapshots/         可随仓库查看的精简研究快照
HANDOFF.md                 当前进度、问题、验收与续接入口
```

完整 `reports/`、扫描原件、`item/`、虚拟环境和厂商授权没有上传。新克隆的仓库不会自动拥有本机工程；可以查看研究快照，或载入本地PLY。原报告路径仅作本机研究记录，不在此README中提供无法访问的链接。

## 使用与续接

- [当前交接文档](HANDOFF.md)
- [Web工作台使用说明](docs/web-studio.md)
- [解包到融合的处理链路](docs/offline-reconstruction-pipeline.md)
- [网页原帧绑定与两组重融合](docs/web-fragment-workflow.md)
- [工程结果版本与撤销重做](docs/project-result-history.md)
- [未完成对应点草稿与恢复](docs/landmark-drafts.md)
- [局部几何约束与错配诊断](docs/local-constraint-diagnostics.md)
- [原深度双向检查与视图数量](docs/reserved-view-density.md)
- [对应点结果到原帧重融合](docs/fragment-fusion-bridge.md)
- [备份范围与恢复方法](docs/backup-and-restore.md)
- [仓库内的研究快照](research/snapshots/2026-10-20/README.md)

## 检查

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests
& 'C:\Program Files\nodejs\node.exe' tests\check_point_viewer_cpu.cjs
& 'C:\Program Files\nodejs\node.exe' tests\check_web_studio.cjs
& 'C:\Program Files\nodejs\node.exe' tests\check_fragment_editor.cjs
& 'C:\Program Files\nodejs\node.exe' tests\check_project_history.cjs
& 'C:\Program Files\nodejs\node.exe' tests\check_landmark_drafts.cjs
```

Node路径按实际安装位置调整。测试使用合成控制和可用的本地数据；没有独立几何真值，内部残差和更多表面点不等于物理精度更高。

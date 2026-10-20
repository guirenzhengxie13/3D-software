# 项目备份与恢复

备份仓库：<https://github.com/guirenzhengxie13/3D-software>。首次备份日期2026-10-20。目标仓库当前为公开仓库，因此备份范围按现有项目忽略规则组织。

## 本次包含的内容

- `src/`：离线数据格式、点云/位姿、融合辅助、空间预览/索引、工作流与Web后端。
- `web/`：Web工作台、对应点页面、CPU兼容绘制与浏览器端求解。
- `scripts/`、`tests/`：解析、重建、分析、启动、验证和回归检查。
- `docs/`：处理链路、研究结论、设计、使用方法与进度存档。
- `config/range2.example.json`、`native_probe/`、依赖配置与锁定文件。
- [研究成果快照](../research/snapshots/2026-10-20/README.md)：关键数量、CPU实测和7张实际结果图。它不要求访问本机报告路径即可查看。

## 继续保留在本机的内容

下列内容未上传GitHub：`.venv/`、`.cache/`、`vendor/`、下载的厂商软件、`item/`原始工程、完整`reports/`、除说明外的`data/`、本机设备配置、授权文件及环境变量文件。原件没有删除或搬动。

当前`reports/`约4.63GB，含约89,729个文件，主要是解包帧、点云、网格与实验中间数据。官方原始工程还可能位于：

```text
%APPDATA%\Revopoint\RevoScan6\Projects
```

**GitHub备份不是扫描数据的完整异地备份。** 若需要换电脑继续处理真实工程，应另行复制原始工程，以及需要保留的`item/`、`reports/`和自有`data/`。厂商SDK和授权须按授权条件单独保存；用户提供的私有恢复参考仓库仍需原账号访问，不复制进本公开仓库。

## 换电脑恢复

```powershell
git clone https://github.com/guirenzhengxie13/3D-software.git
cd 3D-software

# 使用稳定版64位Python 3.12创建新环境。
py -3.12 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-windows-py312.lock.txt
& '.\.venv\Scripts\python.exe' -m pip install -e .

& '.\.venv\Scripts\python.exe' -m unittest discover -s tests
& '.\scripts\start-web-studio.ps1'
```

若新电脑没有`py`启动器，使用实际Python3.12可执行文件替换`py -3.12`。锁定文件记录当前Windows环境；其他操作系统不保证这些轮子版本均可用。

Chrome打开 <http://127.0.0.1:8877>。没有复制真实数据时，工程目录不会自动出现；可先看研究快照或载入本地PLY。Web功能说明见 [web-studio.md](web-studio.md)。Node回归检查需要安装Node.js；部分脚本目前仍记录本机Node路径，移机后按实际路径调整。

原报告含本机绝对路径与输入哈希。移动工程后不要直接把旧路径当有效输入，应通过解析/重建脚本重新生成清单，或有记录地迁移对应数据引用。

## 后续备份

```powershell
git status --short
git add src scripts tests docs web config native_probe README.md pyproject.toml requirements-windows-py312.lock.txt .gitignore research
git commit -m "Update reconstruction software"
git push origin main
```

提交前查看待提交文件。不要用强制添加忽略目录的方式把扫描原件、厂商软件或授权文件塞进代码仓库。

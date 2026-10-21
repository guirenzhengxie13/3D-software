# 2026-10-20 本地续接与移机记录

最新展示结果：程序与扫描原件两部分复制已成功结束，原件393文件、约3.04GB；历史 `reports/` 仍在复制。已在 Codex 内嵌浏览器实际显示793,214点的彩色人偶模型（概览39,141点），验证旋转、缩放、增亮、原点编号及保存深度第0帧。索引563帧不代表563帧已复制。实机截图与证据见 `reports/web-studio/local-demo-20261020/`；当前状态以根目录 `HANDOFF.md` 的“当前展示状态”一节为准。产品新增改动仅为 `web/studio/style.css` 的窄屏布局修复，尚未回写网络项目。

## 用户安排与当前状态

另一台电脑额度用完，本次在这台电脑复制项目、继续开发；开发完成后同步回网络项目目录。用户明确要求补写 handoff，后续每轮结束及同步前均应更新根目录 `HANDOFF.md`，写明完成项、验证结果、遗留问题和下一步。

本记录创建时的状态：

- 网络源为 `P:\revopoint software`，对应 `\\192.168.1.105\project\revopoint software`。源 Git 为干净的 `main`，基线提交 `7676c02`。
- 当前本地项目为 `C:\Users\5gvs4\Documents\my project\revo software`，代码已复制。
- 完整 `reports/`、`item/`、`vendor/`、`downloads/` 及 Q 盘扫描原件仍在复制，不能视为已经完成或校验一致。
- 全新 Python 环境正在安装；产品的路径映射尚未实现，尚不能认定本地工作台可运行。
- 本文记录已读源码得到的迁移问题；最终复制、环境和验证结果由主续接工作补充。

后续本机检查（2026-10-20）：独立 `.venv` 和锁定依赖已安装完成，Python 3.12.14、NumPy 2.5.4、Open3D 0.20.0、Pillow 12.3.0，editable 包指向本地 `src/`，`pip check` 通过。123 项 Python 测试、80 组 NumPy/JavaScript 求解交叉校验和三项 Node 界面/CPU 检查均通过；未完成实际浏览器/GPU或本机真实扫描 HTTP 验证。Git 历史从同一公开仓库恢复，远端 main 与接手提交均为 `7676c026eec48675588fa15d23cc989433085bae`，完整性检查通过，产品代码相对该提交无改动。

历史报告的逐帧小文件较多，当前按互不重叠的目录分批并行复制。复制命令、每批日志与结果写在 `.cache/migration-20261020/`；完成前不能将已创建文件的大小相加当作复制成功，仍须以每批成功退出和最终核对为准。原有虚拟环境的未完成副本保存在同目录下的 `partial-source-venv/`，未用于运行。

扫描原件复制曾出现 Windows ERROR 64，两份 `cache/frames.dataset` 需重传。已启动本地 `finish_copy.py` 收尾进程，等待现有三部分复制，失败时最多补拷两轮；实时状态和最终结果写在同目录的 `copy-final-status.json`，结束后自动在根目录 `HANDOFF.md` 末尾追加结果。当前不能宣称全量数据复制完成，不能将待完成副本用于正式计算。本轮只更新本地交接，网络项目仍保留原状态；开发完成后的回同步要求继续有效。

## 路径对应关系

| 用途 | 原位置或网络位置 | 本机位置 / 处理方式 |
| --- | --- | --- |
| 旧机项目根 | `G:\project\revopoint software` | `C:\Users\5gvs4\Documents\my project\revo software` |
| 项目回同步目标 | `P:\revopoint software` | 完工后核对差异并同步回此目录 |
| 新批扫描原件 | 旧机 `C:\Users\5gvs4\AppData\Roaming\Revopoint\RevoScan6\Projects`；本机网络入口 `Q:\revo data` | 复制目标为本地 `data\revo-scan-projects`；复制与校验尚在进行 |
| 早期原件及研究数据 | 旧项目内 `item/`、`reports/` 等 | 保持项目内相对目录结构复制到本地 |
| 旧虚拟环境的创建位置 | `G:\project\面向三维扫描模型的交互式辅助重建软件设计与实现\.venv` | 这是旧 `pyvenv.cfg` 的历史记录；本机环境单独建立，检查 editable 安装指向本地 `src/` |

以上是迁移需要遵循的对应关系，尚不是已经生效的运行时配置。不要仅凭本机用户名相同，就把旧 `%APPDATA%` 路径视为已经存在或属于同一份扫描数据。

## 已证实的绝对路径问题

源码位置均相对项目根，行号对应基线 `7676c02`。

| 位置 | 当前行为及迁移影响 |
| --- | --- |
| `src/reconstruction_probe/web_studio.py:82` | 仅载入 `job.folder` 与实际 `job.json` 父目录一致的任务。旧机绝对目录不一致时，旧任务不会进入任务列表。第 307 行读取任务日志时还会再次使用该目录。 |
| `src/reconstruction_probe/web_studio.py:127`、`:135` | 直接用解包索引的 `source_directory` 找官方保存融合及预览；旧路径不存在会使这些模型被跳过。 |
| `src/reconstruction_probe/web_studio.py:154`–`:164` | 工作台 HTML 的 `alignment-data` 内保存 `clouds[*].path` 等绝对引用。内嵌点可能仍可画出，但后端模型发现、工程归属和后续操作会受旧路径影响。 |
| `src/reconstruction_probe/web_studio.py:193` | LOD 缓存以 `source_path` 与当前模型路径匹配；移机后不匹配会退回重新生成预览。 |
| `src/reconstruction_probe/web_studio.py:275`–`:281` | 对应点会话的源、目标、候选及 prepared 路径须匹配当前目录或工作台。仅重定位模型目录而保留旧页面导出的会话路径，提交仍会被拒。 |
| `scripts/reconstruct_scans.py:184` | 直接读取解包清单的 `source_directory`，通用重建脚本不会自动找到迁移后的扫描原件。 |
| `scripts/apply_landmark_alignment.py:28`–`:43` | 直接读取会话源/目标、prepared、候选路径；另读 `prepared/training.json` 内的模型路径并核对候选文件哈希。 |

保存帧预览使用解包索引附近的 `frame_*/frame.npz` 和保存位姿，相对结构较适合迁移；仍须等完整复制后实际验证。`scripts/check_web_render_pipeline.py` 可用 `--node` 覆盖其默认旧 Node 路径。

## 保留历史文件字节与哈希

不要为修路径批量替换历史 `reports/` JSON、HTML、索引或候选文件。`scripts/reconstruct_fragment_plan.py:30` 将 `decoded/index.json` 的 SHA 传入片段计划核对，第 36 行还会校验计划引用的输入哈希；`scripts/apply_landmark_alignment.py:42` 校验已有候选文件的 SHA。仅改路径也会改变文件字节，从而使已有证据链失效，随后需要级联修改其他记录。

优先实现有记录的运行时路径映射，让旧路径解析到本地同一内容，保留原文件字节、输入哈希和原始来源。映射需同时覆盖目录发现、旧任务、提供给浏览器的工作台数据、提交的会话和后续 CLI。若必须生成迁移版本，应另存新文件，记录原文件哈希、映射和新文件哈希，并明确验证引用关系；不要覆盖研究原记录。

## 后续续接与回同步

1. 完成复制并核对文件数量、大小及关键内容；确认本地扫描原件、解包帧和主要模型齐全。
2. 检查新环境、editable 安装与路径映射，再验证本地目录、保存帧、模型预览及对应点任务。尚无本机实测结果时不要写成已经可运行；CPU 像素检查也不等于 Chrome/GPU 验证。
3. 本地继续开发，保留扫描原件、研究候选和基线，新增结果使用新目录。
4. 每轮结束及回同步前更新 `HANDOFF.md`，包含本机入口、环境与数据状态、修改及验证、未完成项和下一步。
5. 回同步前重新读取网络目录的 Git 状态及文件差异，对照 `7676c02` 和本次复制基线，查明另一台电脑是否产生新修改。发生并行改动时先合并、保留双方成果，再同步。
6. 按核对后的清单将代码、文档、handoff 和需保留的开发结果同步到 `P:\revopoint software`。不用 `robocopy /MIR` 或其他镜像删除操作；不要让本地缺失文件删除网络原件或研究结果。
7. 不将本机 `.venv/` 回写网络项目覆盖另一台机器的环境；本机专属配置、临时缓存和迁移日志也先检查适用范围。运行时路径配置需要区分两台机器，不能让网络副本依赖这台电脑的 C 盘目录。
8. 同步后核对变更文件和 `HANDOFF.md`，记录同步完成状态；不要在未完成核对时宣称另一台电脑已经接续成功。

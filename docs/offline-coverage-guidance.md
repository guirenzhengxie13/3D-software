# 离线覆盖诊断、表面点回查与补扫方向

这条链路用已经保存的深度、位姿和标定工作，不依赖实时 SDK：

```text
重建表面 → 投影到每个已存深度视图 → 支持/冲突/遮挡
                      ↓
             支持帧编号与原像素
                      ↓
             观察方向分布与弱区域
                      ↓
          回查原帧 → 提出补扫方向候选
```

## 为什么不能只数支持帧

研究的直接配准候选抽取 40,000 个表面点，以全部 358 帧检查。典型点有几十帧支持，但连续帧可能从近似相同方向观察。当前分别保存：

- 深度在 2/4 mm 内支持的视图数、自由空间冲突数和遮挡数。
- 组 0、组 1 各自提供的支持。
- 支持视图的位图；可以恢复具体原帧 ID。
- 与第一个支持视角的最大夹角，以及方向向量集中程度。
- 最佳法向入射视图、对应深度像素和平均观察距离。

“与第一个支持视角的最大夹角”是实际观测到的角度分离，下限于完整的最大两两夹角；它不是完整立体角、独立样本数或准确性置信度。法向只为诊断和建议统一到首个支持相机的一侧，原模型不因此改变。

两份融合结果各抽取 40,000 点，原保存片段关系约 30.1% 有重复自由空间冲突，直接对齐候选约 5.6%。两份表面的采样位置不同，因此这是表面内部诊断，不能当作同点留出精度结果。此前固定相同原像素的留出检查另存。

直接候选中约 16.9% 的点有至少三帧支持，但相对首支持视角最大夹角仍小于 15°。这类区域即使观测很多次，也可能缺少足够不同方向。完全没重建出的区域无法在表面着色图中出现。

[覆盖分类与三维查看](../reports/range2-study-20261018/experiments/cup-direct-split/view-coverage/README.md)。

## 点能回查到哪一帧、哪一个像素

本次选择的大弱区域代表点：原表面点编号 29,546，覆盖抽样编号 6,928。它有 27 个支持视图，但首支持方向的最大夹角只有 9.77°。回查图中可定位到杯内壁附近；另一方向的测量先碰到杯壁，对该点属于遮挡。

[原帧与像素证据图](../reports/range2-study-20261018/experiments/cup-direct-split/point-trace-weak-region/README.md) 列出帧 ID、像素坐标与深度差。图像由已解包、对齐到深度像素的颜色恢复，无深度区域显示黑色，不是完整原 JPEG。

```powershell
$direct = 'reports\range2-study-20261018\experiments\cup-direct-split'

& '.\.venv\Scripts\python.exe' scripts\analyze_surface_view_coverage.py `
  --prepared $direct --fusion "$direct\full-reconstruction" `
  --label direct_best_training --out 'reports\coverage-new'

& '.\.venv\Scripts\python.exe' scripts\trace_surface_point.py `
  --coverage 'reports\coverage-new' --sample-index 6928 `
  --out 'reports\point-trace-new'
```

抽样编号依赖具体输入和抽样上限，应从该次 `coverage-data.npz` 查询，不能跨模型硬套。

## 怎样提出补扫方向

原型仅聚类已经观察到、但支持较弱或角度集中的表面。重复冲突区先建议检查配准，不直接归因于“需要再扫一次”。对每个区域：

1. 选取真实表面中的代表点，估计局部法向的一致程度。
2. 以已经支持该点的相机到点距离中位数作为候选观察距离。
3. 在球面采样 192 个方向，要求与已有最近支持方向至少相差 15°，且法向入射条件满足固定门槛。
4. 用当前三角网格做射线检查，同时检查相机视野。至少 80% 的区域抽样点可见才保留；每区最多检查 64 点。
5. 按固定启发式的可见比例、入射方向和新颖角度保留候选，并记录未通过原因。

射线实现参考 [Open3D 官方说明](https://www.open3d.org/docs/latest/tutorial/geometry/ray_casting.html)。本次检查六个区域，保留五个方向候选，一个区域因当前网格遮挡未给出建议。见 [方向图、参数和建议位姿](../reports/range2-study-20261018/experiments/cup-direct-split/scan-view-proposals/README.md)。

```powershell
& '.\.venv\Scripts\python.exe' scripts\propose_offline_scan_views.py `
  --coverage 'reports\coverage-new' --out 'reports\view-proposals-new'
```

这些是物体参考系下的观察建议，不是房间中的真实相机轨迹或可执行设备命令。当前模型不完整，网格射线判断也可能有误；建议必须结合实物和局部几何查看。启发式得分不是最优信息增益，也不保证补扫后精度提升。

它已经给课题形成一个可演示的离线闭环：导入官方扫描工程 → 辅助修正/融合 → 解释弱区域 → 建议补扫 → 用官方软件追加扫描 → 再导入比较。实时采集后续可以接入，同一套诊断仍可复用。

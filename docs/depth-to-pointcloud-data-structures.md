# 按数据结构理解：解包数据怎样变成点云

本文使用 `scan_03/frame_0000000000` 的真实数据演示，读取核对日期为 2026-10-18。

本文表名、16 字节深度头和坐标翻转属于旧工程。新扫描改为 `Frame_Attr_*` 属性表、20 字节深度头及 132 字节位姿，实测轴约定为 `[1,1,1]`；请查阅 [新工程的数据结构与实测](range2-study-20261018.md)。

**最主要的结构变化是：`二进制字节 → 深度二维数组 → XYZ 二维数组 → 扫描坐标系中的 XYZ 数组`。**

## 1. 文件里最初是什么

工程 `cache/frames.dataset` 的临时副本恢复标准 SQLite 文件头后，可以按表读取：

```text
FrameRGBD
  id       用于识别和关联某一帧
  width    深度宽度
  height   深度高度
  version  深度编码版本
  data     这一帧深度的二进制字节（BLOB）

FrameInfo
  id       与深度帧按 ID 关联
  bin      保存位姿等信息的二进制字节（BLOB）
```

相机内参位于工程的 `param/Pl.bin`，不在深度 BLOB 中。部分工程还在 `cache/global_register_pose.pose` 中另存了一套位姿。

深度和位姿按 **ID** 关联，不能只把两张表按行号拼起来。

## 2. 深度 BLOB → `depth_mm[300, 400]`

当前样例保存的是稀疏深度：先说明哪里有数据，再按顺序保存那些位置的值。

真实第 0 帧的结构为：

| 部分 | 数据结构 | 实际内容或大小 |
| --- | --- | --- |
| 头 | 4 个小端 `uint32` | `[400, 300, 51672, 0]`：宽、高、有效数、载荷类型 |
| 有效位图 | 每像素 1 bit，低位优先 | 120,000 个位置，共 15,000 字节 |
| 深度序列 | `float32[51672]` | 51,672 个有效深度，单位 mm |
| 颜色 | 本帧没有 | 载荷类型为 0 |

总长度为 `16 + 15000 + 51672×4 = 221704` 字节。

解码时，先建一个全零数组，再把有效深度依次填到位图标为 1 的位置。下面用一个小数组说明，数值为示意：

```text
有效位图：             保存的有效深度：
1 0 1                 [200, 202, 198, 201]
0 1 1

填回二维图：
200    0  202
  0  198  201
```

真实输出保存到 `frame.npz`，里面有一个命名数组：

```python
depth_mm.dtype == np.float32
depth_mm.shape == (300, 400)  # 行数、高度在前；列数、宽度在后
z = depth_mm[v, u]           # v 是行，u 是列
```

每个元素只有一个深度值。**它此时还不是 XYZ 点。** 本帧 120,000 个位置中，51,672 个有有效深度，其余为 0。

## 3. 生成点云还需要两个矩阵

### 相机内参：`K[3, 3]`

```text
K = [ fx   0  cx ]
    [  0  fy  cy ]
    [  0   0   1 ]
```

`fx、fy、cx、cy` 负责把画面位置换算成相机坐标。解包后的 `index.json` 保存 `intrinsics.Pl.K` 及其标定图像尺寸。

本批标定尺寸为 800×600，深度尺寸为 400×300，因此使用前应将 `fx、fy、cx、cy` 分别按宽高比例缩放。当前深度尺寸对应：

```text
K_depth ≈ [568.547791    0           74.629387]
          [  0          568.547791  159.841431]
          [  0            0           1       ]
```

这里的主点 `cx、cy` 使用文件中的值，不能自行替换为画面几何中心。

### 保存位姿：`M[4, 4]`

```text
M = [ r00 r01 r02 tx ]
    [ r10 r11 r12 ty ]
    [ r20 r21 r22 tz ]
    [   0   0   0  1 ]
```

左上角 `R[3,3]` 表示旋转，最后一列的前三个数 `t[3]` 表示平移，单位为毫米。

本批 `FrameInfo.bin` 为 164 字节，其中偏移 16 开始的 128 字节是 16 个 `float64`，解析后保存为 `pose_stored.npy`。如果存在匹配的另存全局位姿，还会保存 `pose_global_registration.npy`；默认重建优先使用后者。

## 4. `depth_mm[H,W]` → `points_camera[N,3]`

先找出全部有效像素，再逐个计算 XYZ：

```python
v, u = np.nonzero(depth_mm > 0)  # 两个长度 N 的整数数组
z = depth_mm[v, u]              # 长度 N 的深度数组

x = (u - cx) * z / fx
y = (v - cy) * z / fy

points_camera = np.column_stack((x, y, z))
```

结构变化：

```text
depth_mm：300×400，一个格子一个深度
       ↓ 取出 51,672 个有效格子，利用格子位置和内参计算 XYZ
points_camera：51672×3，一行一个三维点

[ x0  y0  z0 ]
[ x1  y1  z1 ]
[ ...        ]
```

这就是一帧的光学相机坐标点云，单位仍为毫米。上述代码中，`points_camera[i]` 对应原像素 `(u[i], v[i])`，因此仍然可以追溯来源。

**真实数值例子：** 本帧 `depth_mm[150, 200]` 为 `205.764999 mm`。结合上面的内参，换算得到：

```text
像素：(u=200, v=150)
光学相机坐标：(45.373291, -3.561745, 205.764999) mm
```

所以“一个像素的深度”成为“一个三维点”，需要同时知道像素位置与相机内参。

## 5. `points_camera[N,3]` → `points_scan[N,3]`

每帧的相机参考系会变，因此还要将点变到共同的扫描参考系。

当前四份工程使用的坐标约定包括 Y、Z 翻转，然后用保存位姿旋转和平移：

```python
R = M[:3, :3]
t = M[:3, 3]

points_scan = (points_camera * [1, -1, -1]) @ R.T + t
```

`@ R.T` 是按“每行一个点”的数组写法进行旋转，最后加上平移 `t`。此处的轴转换是本批工程已验证的约定，其他格式应另行核对。

```text
输入：N×3 点数组 + 4×4 位姿矩阵
输出：N×3 点数组

点的数量没变，改变的是它们所在的坐标系和位置。
```

此真实示例第 0 帧使用的全局位姿恰好为单位矩阵，因此上面的示例点转换后为 `(45.373291, 3.561745, -205.764999) mm`，变化来自当前坐标轴约定。其他帧还会应用相应旋转和平移。

## 6. 多帧到融合输出：数组有什么变化

如果只是将各帧已经对齐的点放在一起：

```python
all_points = np.concatenate([points_scan_0, points_scan_1, ...], axis=0)
# shape = (N0 + N1 + ..., 3)
```

这得到叠加点云，重复观测仍然存在。上面是结构示意，实际处理大量数据时应分批累计，避免一次性占用过多内存。

我们有两种后续输出：

| 分支 | 内部组织方式 | 最后得到什么 |
| --- | --- | --- |
| 全观测体素累计 | 按空间小格累计坐标和、观测次数 | `points_mm[M,3]` 和 `observation_counts[M]` |
| 主链路 TSDF | 将深度、内参、位姿积分进三维距离场 | 提取表面点 `points[P,3]`，以及网格 `vertices[V,3] + triangles[F,3]` |

其中网格的 `triangles` 每一行是三个顶点索引，例如 `[12, 35, 88]`，表示由这三个顶点组成一个三角形。

实际 TSDF 主链路直接接收深度图、内参和外参，内部使用米；无需先为每帧导出点云文件。最后输出再换回毫米。上面的点数组转换帮助理解其几何关系，也是全观测体素分支实际执行的步骤。

融合后的点数一般与全部有效像素数不同：多帧会重复测量同一表面，融合会聚合观测，TSDF 还要提取表面。

## 7. 可直接运行的单帧示例

在项目根目录的虚拟环境中运行以下 Python。它只读取解包结果，在内存中计算，不修改原件：

```python
import json
from pathlib import Path
import numpy as np

scan = Path("reports/four-scans/decoded/scan_03")
folder = scan / "frame_0000000000"
index = json.loads((scan / "index.json").read_text(encoding="utf-8"))

with np.load(folder / "frame.npz", allow_pickle=False) as data:
    depth = data["depth_mm"].copy()

cal = index["intrinsics"]["Pl"]
K = np.array(cal["K"], dtype=np.float64)
height, width = depth.shape
K[0, :] *= width / cal["width"]
K[1, :] *= height / cal["height"]

v, u = np.nonzero(depth > 0)
z = depth[v, u]
points_camera = np.column_stack((
    (u - K[0, 2]) * z / K[0, 0],
    (v - K[1, 2]) * z / K[1, 1],
    z,
))

pose_file = folder / "pose_global_registration.npy"
if not pose_file.exists():
    pose_file = folder / "pose_stored.npy"
M = np.load(pose_file, allow_pickle=False)
points_scan = (points_camera * [1, -1, -1]) @ M[:3, :3].T + M[:3, 3]

print(depth.shape, depth.dtype)          # (300, 400) float32
print(M.shape, M.dtype)                  # (4, 4) float64
print(points_camera.shape)              # (51672, 3)
print(points_scan.shape)                # (51672, 3)，坐标单位 mm
```

代码里的 `points_scan` 已经是一份点云数据：**点云在内存中的核心，就是一个每行保存 XYZ 的数组。** 将这个数组交给点云库即可显示或导出 PLY；它目前只包含本帧观测，没有执行多帧融合。

直观解释见 [从解包到点云](unpacking-to-pointcloud-explained.md)，完整参数、运行命令与坐标约定见 [完整链路手册](offline-reconstruction-pipeline.md)。

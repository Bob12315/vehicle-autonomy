# P19 第一步：只读 Nav2 二维路径规划

环境：Ubuntu 24.04 amd64、ROS 2 Jazzy、Nav2 1.3.13。本阶段为 Rover 增加“地图 + 明确起点/目标 → 可校验几何路径”。不启动 Controller Server、BT Navigator、MPPI、任务执行或车辆命令入口。验收结果见 [P19 记录](autonomy/phase-19.md)。

## 设计与边界

```text
已保存的 P18 地图               当前只读 Application status + MappingInput
          └──────────────────────┬──────────────────────────────┘
                         固定地图内容/来源/Frame epoch
                                  ↓
                  ReadOnlyPlanningService（独立调用进程）
                                  ↓
                     保守车体余量网格 → Nav2 Planner Server
                                  ↓
                 SmacPlanner2D → 候选路径 → 框架独立校验
                                  ↓
                  几何路径 JSON（executable=false）
```

`planning/` 的不可变模型、坐标转换、碰撞校验和 `application/planning.py` 不依赖 ROS、车辆端口、协议或 Transport。`app.plan` 是独立的显式只读入口，普通 Python 即可运行；ROS 环境只加载到它创建的 backend 子进程。长运行车辆 App 的周期、Mission、Action、双 SEND、Lease、Safety 和唯一 writer 没有改变。

每次请求创建独立 namespace、ROS domain 和自有进程组，只启动 Nav2 Planner Server。地图和 TF 使用请求私有 topic；没有车辆连接或运动命令 topic。P19 本身不接现有 Goto；后续显式路径准入与跟踪见 [P20](rover_path_following.md)，规划入口仍为只读。

## 安装与快速运行

复用 P18 用户目录 ROS 环境，增加 Nav2 Planner、Smac Planner、Nav2 消息及其 APT 依赖：

```bash
python scripts/setup_ros2_local.py --navigation
scripts/with_ros2.sh ros2 pkg prefix nav2_planner
```

仍为签名校验的用户目录包提取，不运行系统安装或 maintainer scripts；普通系统 Jazzy 安装也可使用同名包。若系统 `/opt/ros/jazzy` 与用户目录混用，显式指定 `VAF_ROS2_ROOT` 选择完整的用户提取树，见 [P18 环境说明](ros2_mapping.md)。

仓库提供一份 **P18 实际 SLAM 输出的记录地图**（非手绘地图），内容 SHA：

`e0e7a625e27ed2ac86b9621543cd9fd934af395b04431efd884e63f71af34081`

元数据和原报告来源见 [recorded_map.json](../simulation/planning/recorded_map.json)。可直接规划：

```bash
python -m app.plan \
  --map-store simulation/planning/maps \
  --map-sha256 e0e7a625e27ed2ac86b9621543cd9fd934af395b04431efd884e63f71af34081 \
  --frame map --start 0 0 --goal 1.9 3.5 \
  --output artifacts/simulation/example-plan.json
```

起点和目标均为所选 `map` Frame 下的米；`--start-yaw`、`--goal-yaw` 默认为 0，单位 rad。`--clearance` 默认 0.55 m，`--timeout` 默认 15 s（最大 20 s，另有有界进程清理宽限）。没有隐式读取车辆当前位置、命名点转换或最近空闲点吸附。非法/不可达目标会明确失败，不返回一条伪造的直线。

### 在线地图

已有显式只读 Rover App、P18 Mapping 栈时，保持两者运行，再在独立进程调用：

```bash
python -m app.plan --mapping-config /absolute/path/mapping.toml \
  --control-socket /absolute/path/app.sock \
  --frame map --start 0 0 --goal 1 0 \
  --output artifacts/simulation/live-plan.json
```

这里只调用原公开 `status` 用例；要求 Rover、READY、已连接、双 SEND 关闭和地图被 WorldModel 采用。所选目标仍必须位于足够大的已观测空闲区域。不同地图的可用目标范围不同，启动期 SLAM 图尤其可能缺少足够的已知空间。

## 地图、坐标与时间

- 记录地图明确标记 `source_kind=recorded_map`、`captured_ns=null`；这不声称记录仍是当前环境。Frame epoch 为内容 SHA 派生的记录身份。
- 在线地图标记 `live_map`，复用 P18 原 capture、内容 SHA、ResourceReference 和应用 frame epoch。计算前后均检查原地图新鲜度；返回前重读当前地图，拒绝内容、源 generation、资源身份或 frame epoch 改变。
- 同一来源/Frame、完全相同内容的新发布 revision 可视为几何等价，但结果保留**原输入版本和采集时间**；不把原图刷新成新数据。
- Nav2 内使用请求私有的网格局部坐标；原点平移、平面旋转均显式转换起点/目标和返回路径。不能假设 ROS Costmap 会处理 OccupancyGrid 的任意旋转。
- Costmap 生命周期所需 TF 为私有 `grid → planning_anchor`，是算法运行锚点，不是车辆位姿或 SLAM 定位。每次请求均 `use_start=True`，使用显式起点。
- ROS Map header 是规划快照发布时间；原传感器 capture 仅保留在源依赖中，不能用 header 重标成新鲜遥测。
- 响应携带 request ID、原图 SHA/版本、Frame/epoch、请求/校验时间、有效截止、起终点、余量和路径。到期后不可当作当前规划结果；以后执行仍须重新验证世界和授权。

## 碰撞策略

默认 0.55 m 余量采用包住当前 Rover 模型平面包围盒的保守尺度。用户可显式配置其他平台的余量（0.1–2 m）；这不自动更新车辆 SafetyPolicy。

1. 只有原栅格 `0..19` 视为空闲；未知 `-1` 和 `20..100` 均阻挡。
2. 给 Nav2 的派生配置网格采用包住圆形余量的轴对齐方形，再留一个栅格余量。前缀和构建有界，不改写原地图。代价是部分实际可通过的狭窄区域也可能被拒绝。
3. 从 Nav2 读取实际 Costmap，核对 Frame、原点、分辨率、尺寸和全部数据，确认使用固定输入。
4. 框架重新检查候选的 request/map/frame 身份、≤0.10 m 的起终点位置误差、≤8192 个路径点与 ≤1 km 长度。
5. 原图上逐段做线段与膨胀障碍矩形的相交检查，包含擦边接触；不能只检查路径点。车体余量不能碰未知、占据或地图边界。
6. 仿真验收另用原图密集采样和圆/AABB 距离做独立补充检查；不读取生产校验器的派生网格。

这是几何路径，不是带时间的轨迹。不保证最终 yaw、非完整约束、速度、加速度、动态避障或实际可跟踪性。

## 验收命令

```bash
python -m unittest tests.test_planning -v
python -m unittest discover -s tests -q
python -m tests.simulation.nav2_planning
```

在线链使用本机已有的 SITL 构建：

```bash
export VAF_SIMULATION_SITL_BIN_DIR="$PWD/artifacts/simulation/suite-e8ba09fa/build/ardupilot/sitl/bin"
python -m tests.simulation.nav2_live
```

在线 runner 复用 P18 独立世界、激光、SLAM、公开 App 和清理机制；**没有 `--allow-send`**。`smoke_only=true` 表示不运行 P18 运动路线，P19 只读规划是否通过由 `readonly_planning` 单独记录。Nav2 每次请求保存输入、配置网格、params、原始响应、日志、源码哈希和进程组清理 manifest；deadline 触发时销毁自有进程组。

## 保留限制与下一步

P18 的轴对齐地图边界缺陷仍开放；本阶段既不补画墙面，也不证明地图本身完整。规划依赖输入地图质量。P19 验收不含路径执行、在线重规划、动态障碍或真实设备。

后续 [P20](rover_path_following.md) 实现独立的在线路径消费/失效、map↔odom 绑定和 Guidance/跟踪 Action，再通过原 Effect、授权、Safety、唯一 writer 验证有限仿真运动。执行需要主动轮轴参考点及至少 0.95 m 余量，不能直接消费默认 0.55 m 记录图示例。直接将 Nav2 `/cmd_vel` 接到 MAVLink 不属于此接口。

上游依据：[Smac Jazzy](https://github.com/ros-navigation/navigation2/blob/jazzy/nav2_smac_planner/README.md)、[Planner Server](https://github.com/ros-navigation/navigation2/blob/jazzy/nav2_planner/src/planner_server.cpp)、[ComputePathToPose](https://github.com/ros-navigation/navigation2/blob/jazzy/nav2_msgs/action/ComputePathToPose.action)。

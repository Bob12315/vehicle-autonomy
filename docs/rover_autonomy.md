# Rover 命名导航与业务编排

本机 ROS 2 Jazzy / SLAM Toolbox / Nav2 / ArduRover SITL / Gazebo 的显式可选装配。阶段结果见 [P21](autonomy/phase-21.md)、[P22](autonomy/phase-22.md)、[P23](autonomy/phase-23.md)、[P24](autonomy/phase-24.md)、[P25](autonomy/phase-25.md)；未通过的门槛不能由下列配置示例替代。

## 依赖和装配

车辆、实际激光、ROS 时钟、SLAM 和 MappingInput 须先按 [Mapping](ros2_mapping.md) 启动。既有的 [路径跟踪](rover_path_following.md) 准入和安全边界继续适用。默认入口不启用这些装配，也不连接生产设备。

所有文件路径为绝对路径。以下坐标只用于已有仿真场景，不是任意地图的安全目标；未知/障碍区域仍拒绝。坐标表示**已注册导航参考点**，不自动沿用 Environment 的车体原点语义。

`goals.toml`：

```toml
schema = 1
environment_id = "environment:rover-training-v1"

[policy]
planning_timeout_s = 15
total_timeout_s = 240
max_replans = 0
retry_delay_s = 2
planning_reserve_m = 0.0

[[goals]]
name = "POINT_A"
frame = "odom"
reference_point = "navigation_reference"
position = [0.4, 2.5]

[[goals]]
name = "POINT_B"
frame = "odom"
reference_point = "navigation_reference"
position = [0.4, 1.5]

[[goals]]
name = "HOME"
frame = "odom"
reference_point = "navigation_reference"
position = [0.25, 0.0]
```

`navigation.toml`：

```toml
schema = 1
model = "target_rover_front_axle_v1"
plan_path = "/absolute/run/plan.json"
goals_path = "/absolute/run/goals.toml"
timeout_ns = 70000000000
tracking_mode = "stop_turn"
allow_reverse = true
# recipes_path = "/absolute/run/recipes.toml"
```

原前驱模型参考点在 base_link 前 0.25 m；`compact_rover_front_axle_v1` 在前 0.18 m，须配套 `simulation/profiles/compact_rover.toml` 及其实际 SDF。紧凑模型有不同轴距、轮距、车身及质量。不匹配的 Deployment 在连接前拒绝；切换 TOML 不会改变现有 Gazebo 车体。模型、配置、SDF 和参数内容进入状态/manifest。省略 `tracking_mode` 时默认仍为 `smooth`；上述业务配置显式选择停转策略。

`allow_reverse` 默认 false。上述巡检配置显式允许倒车：路径在车后方时，在首次跟踪周期选择并冻结行驶方向，倒车命令限为 0.10 m/s；Action 与最终 writer 同时约束。不会因运行中目标或航向噪声来回切换方向。此选项没有开启 SEND，也不绕过租约、地图、时间、围栏或停车屏障。

启动 Application 时显式传入上述配置：

```bash
python -m app.main run --profile rover_sim \
  --config /absolute/run/profile.toml \
  --control-socket /absolute/run/app.sock \
  --ros2-mapping-config /absolute/run/mapping.toml \
  --navigation-config /absolute/run/navigation.toml --allow-send

python -m app.main ctl --profile rover_sim \
  --control-socket /absolute/run/app.sock start --mission navigate:POINT_A
```

`status` 查询规划/执行/结果，`cancel` 取消当前任务，`shutdown` 退出。规划期间无武装和 SEND；结果本身没有运动权限。任务通过原 Mission、Action、Effect、双 SEND、Lease、Safety 和唯一 writer。只读 Nav2 入口的 READY/禁用 SEND 规则保持。

## 有限重规划

### 低速导航的实际仿真装配

原 `target_rover/model.sdf` 及默认平滑基线保留。扩展导航场景显式加载 `simulation/models/target_rover/navigation.sdf`，紧凑车加载 `simulation/models/compact_rover/model.sdf`。两者的轮速执行器仍通过关节力闭环，使用 P=4、I=0；不更换成运动学插件，也不使用测试真值驱动。

SITL 在原 Rover/skid/telemetry defaults 之后，显式追加 `simulation/params/rover_navigation.parm` 或 `compact_rover_navigation.parm`。0.11 m 轮半径、每个电机单位 5 rad/s 给出速度前馈标定 `CRUISE_SPEED=0.55`、`CRUISE_THROTTLE=100`；两车按实际轮距分别使用转向前馈 0.47272727、0.52727273，并降低积分累积。原生 PID、传感器及碰撞动力学仍运行。

这些是受验收的仿真装配参数。Application 不通过 MAVLink 自动改参数或改 SDF；复现脚本在车辆启动前加载，并记录实际源文件、参数 SHA 和黑盒。`tracking_mode` 本身不等于完成了这项装配。真实设备没有继承这些标定。

### 重试策略

`max_replans` 默认为 0；显式选择 1 或 2 才允许地图路径阻断后的重试。先观察旧任务停止并 Disarm，再读取新输入、规划、重新准入及授权。总期限不会随重试续期。地图源丢失、定位/时间/代际变化、对齐漂移、断连、配置修改及取消均不能通过重试绕过。

动态障碍验收场景使用遥测里程计对齐地图，显式关闭 scan matching，选用 `tracking_mode="stop_turn"`；普通静态路线保留 `smooth`。这不等于任意动态环境的连续避障。

## 地图坐标与锚点

SLAM Toolbox 边界修复的构建、ABI 限制及独立墙面证据见 [P23](autonomy/phase-23.md)。修复库只加载到显式选定的 SLAM 子进程，不能省略构建 manifest 或替换到未经审查的 ROS 版本。

`map` 目标须在目标目录顶层声明 `anchor_path="/absolute/run/anchor.json"`，目标 `frame="map"`。在当前 App/地图会话 READY、原点核对完成、停稳且 Disarm 时登记：

```bash
python -m app.anchor --control-socket /absolute/run/app.sock \
  --output /absolute/run/anchor.json
```

锚点绑定 Environment/HOME、车辆 epoch、地图源、内容及 map←odom 关系。重启/重载后须重新登记并核对命名点，不自动继承旧锚点。不支持在同一 ROS 发布者内部绕过框架替换 pose graph 后继续旧目标。活动定位仍是车辆遥测；SLAM 候选只读，`control_eligible=false`。

## 命名路线与对象巡检

配置 `recipes_path` 后，可提交 `autonomy:INSPECT`。例如：

```toml
schema = 1
[[recipes]]
name = "INSPECT"
goals = ["POINT_A", "POINT_B", "HOME"]
total_timeout_s = 480
inspection_label = "bucket_1"
inspection_at = "POINT_A"
```

不填写两个 inspection 字段即为普通命名路线。巡检必须有标准 Observation 输入；使用现有仿真传感器时附加 `--sim-sensor-config /absolute/run/sensor.toml`。配置不包含真实设备支持。

目标须有效、新鲜、固定生产者/对象身份；接近点是已注册的 odom 目标，与对象相距 1–2 m。到点后观察停稳、Disarm，记录观测来源、原采集时间和 World 版本，再继续路线。对象在巡检前丢失、过期或移动，业务失败并执行 Stop/Disarm 清理。重复取消不打断清理；清理未知明确报告失败。巡检后的返程不再依赖目标仍可见。

## 复现范围

各场景入口为 `python -m tests.simulation.goal_navigation --allow-send --case CASE`，支持原导航故障、规划取消、不可达、重规划/封路/重规划中取消、地图目标、业务正常/取消/对象消失；`--navigation-model` 显式选择两种真实 SDF。`map_goal` 可配合 `--room-yaw 0 --boundary-library /absolute/build/libvaf_slam_boundary.so` 验证轴对齐地图。

这些脚本创建所属 localhost 仿真进程和独立端口，顺序执行，不控制现有物理车辆。Gazebo truth 只用于独立测量，不输入生产控制或建图。原始日志在 `artifacts/simulation/`，便携证据和支持范围在各阶段审计。P26 的重复任务、长运行和统一版本发布，以及 P16 真实硬件仍单独验收。

# RViz2 Visualization V1 — Phase 0 审计

日期：2026-10-28；起点 `8e3faf0`；工作区开始时干净。
已检查 README、architecture、V1.0 行为规范和 V1.1 七模块归属规范。
本文件先于实现编写；以下“方案”不是已完成能力声明。

## 现状

| 检查项 | 实际代码及结论 |
|---|---|
| Web 场地图 | 上一轮 `/control` 已改为无画布控制台；只读硬件 console 也将大地图留给 ROS。Studio 的画布是 Mission 节点编辑器，保留。没有需迁移的新地图依赖或地图执行 API。 |
| UI 与认证 | 原生 HTML/CSS/JS，统一 `tool-console.css`、侧栏、`VAFAuth` Cookie/CSRF 登录。不得再增密钥输入框。 |
| Tool Agent | `app/tools/local.py` 负责自有进程组、Registry、依赖和就绪；`builtins.py` 已有 RViz profile，但只检测 RViz 节点和 TF，不能证明当前车辆数据接通。 |
| Workspace | `app/tools/workspaces.py` 已有依赖排序、实际就绪、共享引用、失败/重启对账。复用，不能让 RViz 生命周期取消 Mission。 |
| ROS 环境 | 系统无 `/opt/ros`；独立 Jazzy prefix 位于用户目录，`scripts/with_ros2.sh` 可加载 rclpy、RViz2、ros_gz_bridge、SLAM Toolbox、Nav2。DISPLAY=:1。ROS 不进入默认服务导入路径。 |
| ROS bridge | `world/mapping/ros2_node.py` 与 `world/sensors/ros2_streams.py` 绑定已有仿真 IPC、Phase 5 传感器及 `/clock`；不是三车型 Web 的通用接口，不应复制其车辆状态管理。 |
| MAVROS2 / AP_DDS | 仓库没有可直接复用的完整装配；当前唯一车辆数据链为已有 MAVLink → VehicleState → WorldSnapshot。不会另开 MAVLink 连接或第二个 writer。 |
| 状态合同 | `contracts/vehicle/models.py` 已提供 Stamped Pose3、Twist3、GeoPoint、health、operation、telemetry；Driver 有不可变发布切面 `read_view()`。 |
| Rover | 上游 `RoverTelemetryState` 用 GPS_GLOBAL_ORIGIN 与 GLOBAL_POSITION_INT 生成受范围约束的 ENU；不应再次转换为 ENU。 |
| Copter | 上游处理 LOCAL_POSITION_NED、姿态 FRD/NED 到 FLU/ENU；可视化必须保留完整三维旋转，不能只旋转 yaw。 |
| Plane | `PlaneTelemetryState` 受签名 GPS_GLOBAL_ORIGIN 和五公里投影域约束；显示飞行姿态/轨迹，不接 Nav2 地面控制。 |
| 时间与原点 | VehicleState 使用带 clock domain 的 host monotonic；World generation 与 link session 为原点/数据 epoch 围栏。现有 `RosClockBridge` 可在明确本机仿真 `/clock` 下映射时间。跨主机不能直接比较 monotonic。 |
| GPS 高度 | 原始 MAVLink global altitude 为 AMSL，不能假装是 NavSatFix 要求的 WGS84 椭球高。没有大地水准面数据时将该字段标为未知。 |
| TF | 现有 Phase 5 工作者可能拥有 map/odom/base_link。可视化默认使用隔离 namespace/frame island，不发布假的 map→odom；外部 TF 只展示，必须显式绑定参考原点才能融合。 |
| 仿真 | 现有三个 start_*_sim.sh、签名 SITL、独立 Gazebo truth oracle、真实 Web 控制验收均可复用。默认 Rover 模型无雷达，不能冒充已有 SLAM/点云。 |
| 传感器 | 已有 RS16 官方 SDK/标准 PointCloud2、LaserScan 和可选 SLAM/Nav2 worker；本轮只接标准 topic，不重写驱动。是否有当前在线硬件数据须另行验证。 |

## 选定实施方案

1. 在 `app/visualization` 添加仅依赖标准库的状态投影、候选目标存储和专用导出能力。
   数据来自现有 Driver 只读切面；不是第二套 VehicleState。专用凭据不能调用控制 API，
   浏览器仍使用现有会话，Agent 凭据继续独立。
2. 显式启动的可选 ROS worker 消费受限接口，将新鲜 ENU/FLU 状态转为 Odometry、
   TF、实际 Path、有效 GPS Fix 和带有效期的可视化标记。轨迹有界；过期、时间异常、
   定位跳变、session/generation 改变时清空/降级，不重新打时间戳伪造旧位置。
3. 三车型独立 RViz 配置共用规范 topic；模型仅为标注过的示意 marker，未校验 URDF
   不启用 RobotModel。标准扫描、点云、地图、路径和 costmap 留给已有数据源。
4. 在可信 Registry 增加 Visualization Bridge 与三车型 RViz profile，通过原 Workspace
   先启动 bridge，再启动桌面 RViz；缺 GUI、安装或数据如实显示失败/降级。
   Web 一键入口自动选择有匹配能力的在线 Agent，复用当前 Vehicle Context。
5. RViz 标准 SetGoal 只发布到专用 pending topic，不加载 Nav2 Goal 插件。目标先通过
   类型、frame、epoch、TTL 验证；Web 仅在明确确认、现有控制权与安全准入后才能
   调用已有 Action。Plane 或没有合法 Action 的上下文只预览，不开绕行控制路径。
6. 分阶段以完整原有单元、真实 ROS/RViz 和 Rover 优先的 SITL 闭环验证，再扩展两类
   飞行器。原生软件证据与 fixture 区分，不用 Mock 代替 GUI、TF 或运动验收。

## 采用的 ROS 合同

坐标约定遵循 [REP-103](https://github.com/ros-infrastructure/rep/blob/master/rep-0103.rst)。
RViz 默认目标工具会发布 `/goal_pose`，因此必须改到候选接口，见
[RViz 文档](https://github.com/ros2/rviz/blob/rolling/rviz2/doc/index.rst) 与
[Goal Tool 源码](https://github.com/ros2/rviz/blob/rolling/rviz_default_plugins/src/rviz_default_plugins/tools/goal_pose/goal_tool.cpp)。
已有 Vehicle 安全、SEND、Lease、TTL、唯一 writer、UNCONFIRMED 与只读硬件边界保持不变。

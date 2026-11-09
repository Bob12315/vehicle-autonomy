# MID-360 纯仿真接入：操作与数据说明

当前验收结论、真实 Gazebo/ROS/RViz 截图和原始运行证据见 [目标一验收报告](MID360_GOAL1_ACCEPTANCE.md)。以下是普通 Rover/Copter 的操作流程；组件始终明确标注为均匀快照近似模型。

目标二的显式逐切片输入、FAST-LIO2 和地图工具另见[三维建图说明](MID360_SLAM_GOAL2.md)。本文保留目标一均匀快照模式的范围与原验收记录，不把该模式重新标作合格 LIO 输入。

## 范围与运行环境

只支持原有普通 `rover`、`copter` 的显式 MID-360 选项。默认不启用；Plane、VTOL、救援专用 Copter 不接此组件。不启动 Livox 硬件驱动、物理串口或物理雷达网络。没有新增 SLAM、定位融合、Nav2 或避障。

复用 `HostEnvironment` 的机器索引，不在仓库安装第三方软件。已发现的环境是 Ubuntu 24.04.1、Gazebo Sim 8.15.0（Harmonic）、ROS 2 Jazzy、Python 3.12.3。需要已有的 `gz.transport13`、`gz.msgs10`、`rclpy`、`sensor_msgs`、`tf2_ros`、`rosbag2_py`、sqlite3 存储插件及 RViz2。ROS 依赖只在显式工作进程中导入。

## Rover / Copter 启动流程

两种车型均从原控制台启动：

```bash
cd /home/level6/vehicle-autonomy-framework
source .venv/bin/activate
./control-center
```

1. 登录原控制台，进入“仿真中心”，选择新增 `L01 / MID-360 几何检查场`。
2. Rover 选择“地面车”；Copter 选择“多旋翼”。勾选“为本次会话的 Rover / Copter 启用 MID-360 仿真近似模型”。该选择会应用到本次配置中的所有普通 Rover/Copter，也可在添加车辆时使用。
3. 选中心出生点，创建会话，点击“启动”。可同时配置 Rover 和 Copter，使用不同出生点，原有碰撞/安全距离检查仍生效。
4. 点击“打开 Gazebo 三维窗口”，连接本次已有 Server 的 GUI。Server 与 GUI 分开管理，图形方式明确可用，不需要重启另一套仿真。
5. 选中当前车辆，查看“MID-360 · 纯仿真”。等待实时状态在线，点击“打开 MID-360 RViz2”。控制中心或车辆页原来的 RViz 打开入口，在选中启用 MID-360 的车辆时也会使用该显示配置。
6. RViz 默认按世界高度 Z 着色；在 PointCloud2 显示项可改 `Intensity / intensity` 或 `Intensity / range`，查看实际强度或距离。强度字段不存在时输出 0，状态明确标记不可用。
7. 车辆移动使用原“车辆控制”或原任务入口，按原流程启用操作权限、系统/Action SEND、SafetyPolicy。传感器和显示工具不获取车辆命令端口。Rover 建议低速移动；Copter 通过原 Takeoff/Goto/Land Action 完成受控仿真运动。
8. 可以独立关闭/重新打开 RViz。停止仿真会先走原车辆安全退出，再关闭所属传感器、录制、回放和 RViz 工具。退出控制台继续使用原有 systemd cgroup 清理。

配置等价的已认证 API 请求如下，使用原浏览器会话/CSRF 或原 API 认证，不能裸调用绕过认证：

```json
{
  "scene_id": "L01",
  "vehicles": [
    {"kind": "rover", "spawn": {"id": "center"}, "sensors": {"mid360": true}},
    {"kind": "copter", "spawn": {"id": "north"}, "sensors": {"mid360": true}}
  ],
  "parameters": {"obstacle_count": 0}
}
```

请求原 `/api/simulation/create` 后，向原 `/api/simulation/start` 提交返回的会话 `id`。新增 `/api/simulation/mid360` 只接受 `id`、`vehicle_id`、注册的 `action`、`source` 和录制 `bag_id`，不接受命令行、进程号、Domain 或文件路径。

## 录制、回放和数据来源

实时状态在线后点击“开始录制”，完成后点击“结束并保存录制”。只有生成最终 metadata 且 sqlite3 内实际含有 points、IMU、动态 TF、静态 TF、clock、车辆描述、轨迹和来源状态这 8 类消息，录制才标记为完整。记录文件位于本次运行会话的 `sim-…/vehicle-…/mid360/bags/bag-…/`，具体绝对路径在状态的 `bags[].path` 中显示。

选择已保存录制，点击“循环回放”，将 RViz 数据来源切换为 `rosbag2 回放`，再打开 RViz。实时与回放分配不同 Domain；回放只播放录制的 `/clock`，不会额外生成第二个时钟。回放的当前 `/status` 标记 `source=rosbag2`；原录制中的实时状态移至 `recorded_status`。RViz 显示项标题同样含 LIVE / REPLAY。

停止仿真时会关闭正在回放的工具；之后可从保留的该会话页面重新打开录制回放。控制台后台重启时，从 `RuntimePaths.sessions/control-center` 的以前自有会话恢复完整录制，旧会话显示在“运行与监控”中，选择原车辆后即可回放。只恢复录制元数据，不接管旧 PID、旧 DDS 域、旧车辆权限或旧实时源；不从 `artifacts/` 加载历史软件。录制开始即原子保存“不完整”索引，上次崩溃且未完成落盘的 bag 不会被冒充完整录制。

工具动作白名单：`status`、`sensor_start`、`sensor_stop`、`record_start`、`record_stop`、`replay_start`、`replay_stop`、`rviz_start`、`rviz_stop`、`fault_on`、`fault_off`。关闭实例的实时数据桥不能重新激活；需要新的仿真实例。

## 坐标、时间和消息

每个实体使用 `/vaf/<entity>/sensors/mid360`（下称 `NS`）。Gazebo topic 和 frame 都带不可复用的实例实体名。每个实时实例及其回放分别租用 ROS Domain 120–199；请不要把其他手动 ROS 工具固定在这个保留范围内。域租约存放在 `RuntimePaths` 的持久状态目录。清理未确认或进程崩溃时隔离旧域，避免旧节点尚在退出时重用 `/clock`。不自动删除未知租约。

| Topic | 类型 | QoS / 含义 |
| --- | --- | --- |
| `NS/points` | PointCloud2 | Best Effort、Volatile、depth 5；原始采集 stamp |
| `NS/imu` | Imu | Best Effort、Volatile、depth 5；SI：m/s²、rad/s |
| `NS/status` | String JSON | Reliable、Volatile；在线状态、来源、采集时间和故障 |
| `NS/tf` | TFMessage | Reliable；Gazebo 世界到模型的真实动态位姿 |
| `NS/tf_static` | TFMessage | Reliable、Transient Local；实际模型体坐标与传感器安装外参 |
| `NS/robot_description` | String URDF | Transient Local；明确标注的示意车体和雷达外形 |
| `NS/trajectory` | Path | Reliable；Gazebo 模型真值轨迹，仅用于显示 |
| `/clock` | Clock | 该隔离域的 Gazebo 仿真时间；回放时为原 bag clock |

世界为 Gazebo ENU，传感器/车体为右手 FLU。动态链是 `<entity>/world → model → base_link → mid360`。Rover 原模型 `base_link` 比模型原点高 0.19 m，保留该事实；Copter 基体位于原 `iris_with_standoffs` 子模型。安装 pose 相对 base_link：Rover `(0,0,0.22,0,0,0)`，Copter `(0,0,0.16,0,0,0)`。没有用假的静态 world→base TF 代替运动。

这些 Gazebo 真值 TF 不进入 World 定位融合或 AP 控制。车体显示是原尺寸基础上的简化示意 URDF，不是原车型所有网格/关节的完整重建。

点云采用小端 40 字节点：

| 字段 | offset | 类型 / 单位 |
| --- | --- | --- |
| x / y / z | 0 / 4 / 8 | float32，米 |
| intensity | 12 | float32，原 Gazebo 值；不可用时为 0 |
| range | 16 | float32，米 |
| ring | 20 | uint16，源消息栅格行号，不代表 Livox 通道 |
| time | 24 | float32，秒，当前快照模型为 0 |
| offset_time | 28 | uint32，纳秒，当前快照模型为 0 |
| timestamp | 32 | float64，绝对仿真纳秒，与原 header stamp 对应 |

保留了以后做消息转换和时间校验所需的字段，但没有声称它是 `livox_ros_driver2/CustomMsg` 或已验证 FAST-LIO2 输入。当前模型不能验证真实非重复采样去畸变；未来的 Livox 接入还要审核通道语义、逐点采样、IMU 外参和单位。

## 仿真方案和物理限制

使用 Gazebo 原生 `gpu_lidar` 和 `Imu`，点云来自场景渲染的真实几何射线计算；没有预生成点云、随机障碍点或重新手写扫描求交算法。Rover/Copter 复用同一 SDF 配方，只改变实际挂载链和外参。装配只修改已验证、实例独占的模型副本，并单独记录配方、修改文件和基础模型 SHA；原质量、惯量、碰撞、执行器映射及源模型锁不变。

近似参数为水平 360°、垂直 −7°…52°、720×28 均匀光线、10 Hz、0.1–40 m、2 cm 高斯距离噪声。实际一帧有效返回数量取决于场景。水平首尾方向可能重合，是均匀栅格近似的限制。

**不是 MID-360 非重复扫描。** 每帧全部光线同时计算，所有逐点 offset 明确为零；没有编造扫描先后顺序或运动畸变。不模拟真实反射率相关量程、雾雨、激光干扰、多回波或物理雷达网口。200 Hz IMU 是 Gazebo 理想 SI 数据，安装在近似雷达原点，未建真实内部 IMU 杆臂和器件噪声。雷达外壳只增加 visual，不改变车辆负载动力学。

候选组件调研和不选用原因见验收报告。若后续验证专用插件，仍应保留当前近似后端的明确标识，不能静默把栅格数据改称真实 Livox 扫描。

## 测试入口

```bash
.venv/bin/python -m unittest tests.test_mid360_simulation -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tests.simulation.mid360 \
  --run-dir artifacts/mid360-native-new --allow-send --gui
.venv/bin/python -m tests.simulation.mid360_center_native \
  --run-dir artifacts/mid360-center-new
```

运动入口只允许原有自有 loopback SITL，通过原 Action/Safety 控制运动；GUI、录制和回放要求实际消息、采集时刻完整 TF 和可见自有窗口，截图仍需人工查看。RS16 回归使用真实 Gazebo bag 通过原 RS16 转换器的显式回放模式，验证实际 LaserScan，绝不启动物理雷达驱动。控制台入口使用新的私有运行目录和只读部署，实际执行浏览器操作、三次后台启动及自有后台 SIGKILL 清理；若已有操作者控制台运行，拒绝接管。每次验收目录必须为新目录，失败或未执行项目保留 FAIL / NOT TESTED。

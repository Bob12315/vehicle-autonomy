# P18：本机 ROS 2 / Rover 二维建图

状态：**P18 限定 Rover 二维仿真场景 PASS**（2026-10-19）；后续 P23 已完成受审 2.8.5 原生边界修复和地图锚点，见 [P23](autonomy/phase-23.md)。环境：Ubuntu 24.04 amd64、Gazebo Sim 8.15.0、ROS 2 Jazzy、SLAM Toolbox 2.8.5、ros_gz_bridge 1.0.24。仅连接本机自有 SITL/Gazebo；真实设备、三维和生产时钟同步未验收。

## 运行链与职责

```text
Application → basic_route Mission → Action → Effect → Execution/Safety/Authority
    → 原唯一 MAVLink writer → ArduPilot Rover SITL → Gazebo 车辆运动

App 只读状态 → ROS 2 sidecar → odom/base_link TF
Gazebo 激光 + /clock → ros_gz_bridge → ROS 2 sidecar → /scan
SLAM Toolbox → map/odom TF + /map
    → ROS 2 sidecar → 不可变地图内容 + 有限元数据
    → MappingInput → WorldModel → WorldSnapshot.map
```

ROS 2 在单独进程内运行，`contracts/`、Core、Action、Mission、WorldModel 不依赖 rclpy 或 ROS 消息。`integrations/ros2/mapping_node.py` 只查询 App 的公开 `status` 用例，发布遥测 TF/扫描并接收地图；不存在车辆命令订阅或第二个 MAVLink writer。车辆运动仍从正式 `app.main ctl start --mission basic_route` 发起。

ROS 的 `map→odom` 校正由 SLAM Toolbox 提供，`odom→base_link` 由遥测适配器提供，`base_link→laser` 来自明确的仿真安装外参（z=0.2 m，相对 base_link）。现有导航 Action 使用原 P10 遥测定位；SLAM 的地图位姿随地图版本作为只读诊断提供，尚未被选择为车辆控制反馈。这避免将回环校正直接套到原有 odom 目标上。地图资源可供下一阶段 Planning/地图查询消费，当前不据此声称已实现避障或 Nav2 导航。

| 接口 | 来源与用途 |
| --- | --- |
| Gazebo `/vaf/lidar` → ROS `/scan_raw` | 720 线、360°、10 Hz、0.15–12 m 的实际仿真激光 |
| `/world/<本轮世界>/clock` → ROS `/clock` | 单向桥接本轮时钟，独立 ROS_DOMAIN_ID/GZ_PARTITION |
| ROS `/scan` | 保留扫描原时间；等待有限的时钟与遥测 TF 配对后转发 |
| ROS `/tf`、`/tf_static` | 一个明确来源负责一条边；不假设 map/odom 相同 |
| ROS `/map` | 只接受一个地图发布者；发布者重启使用新的 source epoch |
| `<exchange>/maps/<sha256>.json` | 独立、不可变、内容校验的 OccupancyGrid 资源 |
| `<exchange>/bridge.json` | 原子发布的有限元数据，包含 frame/source epoch、采集时间、地图版本和对应 TF |
| `WorldSnapshot.map` | 当前可采用的 ResourceReference；过期、断流、跨会话等情况为空 |

## 依赖与本机环境

已有 `/opt/ros/jazzy` 时，按 [ROS 官方 Ubuntu 安装说明](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html) 配置仓库，再安装 SLAM Toolbox、rclpy、tf2_ros、ROS CLI 和 ros_gz_bridge。本项目也提供 Ubuntu 24.04 amd64 的可选用户目录提取方式：

```bash
python scripts/setup_ros2_local.py
scripts/with_ros2.sh ros2 pkg prefix slam_toolbox
```

用户目录方式下载 APT 签名验证的包及依赖，提取到 `~/.local/share/vehicle-autonomy/ros2-jazzy/root`，不安装到系统目录、不运行 maintainer scripts。默认镜像为清华 TUNA，ROS 签名密钥从官方 rosdistro 获取并核对指纹 `C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654`；APT 保持签名校验。包文件 SHA256 清单保存在该目录的 `manifest.json`。这是针对本机已安装系统依赖的运行环境，不是可复制到任意机器的完整系统镜像。

`scripts/with_ros2.sh COMMAND ...` 只为子进程加载 ROS 环境；优先采用 `/opt/ros/jazzy`，否则使用上述目录，也可用 `VAF_ROS2_ROOT` 指定用户提取树。根框架的普通 Python 启动与单元测试无需 source ROS 环境。

## 一次完整演示与验收

本机当前已有的自有 SITL 构建可这样使用：

```bash
export VAF_SIMULATION_SITL_BIN_DIR="$PWD/artifacts/simulation/suite-e8ba09fa/build/ardupilot/sitl/bin"
python -m tests.simulation.ros2_mapping --allow-send
```

新机器须将 `VAF_SIMULATION_SITL_BIN_DIR` 指向已经构建的 Copter/Rover SITL bin 目录；现有框架 Gazebo/ArduPilot 依赖见 [仿真说明](simulation/README.md)。不传 `--allow-send` 时，完整运动场景拒绝启动；`--smoke` 仅验证只读建图启动，不能计作完整 Mission 验收。

演示创建独立世界、匹配的 TCP/JSON 端口、ROS domain、仿真激光、4 面墙和一个不对称柱体；启动现有正式 App、单向 Gazebo Bridge、ROS sidecar 和 SLAM Toolbox，明确 configure/activate 生命周期。房间相对 odom 旋转 0.15 rad；几何验收使用相同的明确场景旋转，不改变占据值或验收邻域。默认在有 DISPLAY 的本机使用 server-only GLX，不弹出 Gazebo GUI；无 DISPLAY 时尝试 EGL，须有实际可用的驱动。本机混合显卡 EGL 曾出现驱动崩溃，未以虚构扫描或地图替代，已切换到可用的 GLX。

**原 P18 未打补丁组合的缺陷：轴对齐封闭房间可能缺失边界墙面。** 失败证据 `ros2-mapping-6f3d5b6a` 保留，与 [上游 #689](https://github.com/SteveMacenski/slam_toolbox/issues/689) 现象一致。P23 现提供显式原生覆盖库修正栅格上界，原扫描/ray tracing 不变，没有补画墙面；轴对齐与旋转房间均重新匹配四壁并通过。构建/ABI/加载规则见 [修复审计](autonomy/phase-23.md) 和 [装配](rover_autonomy.md)。默认不自动加载补丁；未经审查的版本或任意场景不能继承这些 PASS。

场景依次验证：

1. 地图必须来自真实 LaserScan/SLAM 输出，已知栅格≥500、占据栅格≥100，4 面墙在对应 map/odom 坐标下均匹配；该检查的邻域为 3 个栅格，分辨率为 0.05 m。
2. 从公开 CLI 执行原 `basic_route`，到 A、B、HOME；沿用 ≤0.75 m 的物理到达误差、≤0.10 m/s 的 Rover Stop 真值速度，以及原 Action 退出屏障。
3. 保存内容寻址 JSON、PGM/YAML，并校验读取后与原栅格一致。
4. 通过 SLAM Toolbox `serialize_map` 保存实际 pose graph，重启 SLAM、`deserialize_map` 后恢复地图，来源 epoch 必须更换。
5. SLAM 断流后地图不可继续采用。重新启动路线并确认车辆运动，再停止 sidecar、公开取消任务；沿用原 8 s 停止期限、≤0.10 m/s 且持续 2 s 的独立真值检查，确认 SEND 撤销，再通过现有 safe_recovery 确认 Disarm。
6. 验证只清理自有进程、socket 和端口。ROS 生命周期 CLI 使用 `--no-daemon`；长期 ROS 程序直接 exec，避免遗留 ros2-run 包装进程。

报告位于 `artifacts/simulation/ros2-mapping-<id>/`：`summary.json`、`manifest.json`、完整 App 状态与独立 Gazebo truth、原始 world/model/profile、ROS/Gazebo/SITL 日志、地图内容和导出文件。SLAM Toolbox 5 cm 栅格、720 线扫描等建图参数独立配置在 `simulation/mapping/slam_toolbox.yaml`；未修改原车辆导航/Stop 验收阈值。

## 接入普通应用进程

显式创建配置，例如：

```toml
schema = 1
directory = "/absolute/path/to/exchange"
clock_domain_id = "host-monotonic-simulation"
max_age_ns = 10000000000
```

先启动自己的本机仿真，再运行 App 与 ROS sidecar：

```bash
python -m app.main run --profile rover_sim --control-socket /path/to/app.sock \
  --ros2-mapping-config /path/mapping.toml
scripts/with_ros2.sh python -m integrations.ros2.mapping_node \
  --config /path/mapping.toml --control-socket /path/to/app.sock
```

Gazebo Bridge 和 SLAM 还需使用同一 ROS domain、GZ partition、世界时钟和 profile；演示 runner 自动生成匹配配置及准确启动命令。App 不传 `--allow-send` 时只读连接，ROS sidecar 也不能开启 SEND。当前仅允许 Rover 仿真 profile 加载该地图输入。

## 数据与故障边界

地图只含明确 Frame、原点 Pose、分辨率、宽高和行优先 `-1..100` 占据值；冻结的 WorldSnapshot 合同未变。WorldModel 新增有时间语义的 Map 引用输入，记录 Map 依赖和新鲜度。最多接受 250000 个栅格、2 MB 内容文件与 16 KB 元数据；拒绝畸形尺寸、非法占据值、非有限数、哈希不一致及 symlink 文件。

源 ROS 时间通过本机 `/clock` 与 host monotonic 的有限成对采样插值，禁止外推；重复 tick 不刷新年龄，暂停/回跳使源 epoch 失效。原始 scan 与 TF 可以乱序到达，最多等待 16 条扫描、750 ms；无法配对就丢弃，不能改时间戳伪造新鲜数据。地图默认最多 10 s，App 可配置更短时限。源发布者重启换新 epoch，旧 source epoch 不得重放；应用 world epoch 改变后必须重启对应 ROS 建图栈，不能自动将旧图绑定到新 origin。

单元测试：`python -m unittest tests.test_mapping -v`；全量 Python 测试：`python -m unittest discover -s tests -q`。最终 190 项全量测试及实际场景证据见 [P18 验收记录](autonomy/phase-18.md)。该能力不认证硬件时钟同步、真实雷达外参、长期地图存储清理、任意 ROS 发布源、三维地图、实机定位切换或路径规划。

参考实现：[SLAM Toolbox](https://github.com/SteveMacenski/slam_toolbox)、[ROS OccupancyGrid](https://github.com/ros2/common_interfaces/blob/jazzy/nav_msgs/msg/OccupancyGrid.msg)、[ROS 时间设计](https://design.ros2.org/articles/clock_and_time.html)、[Gazebo ROS 2 集成](https://gazebosim.org/docs/harmonic/ros2_integration/)。

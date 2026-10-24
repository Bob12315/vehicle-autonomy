# Vehicle Autonomy Framework

Vehicle Autonomy Framework 是面向多旋翼、无人车、固定翼、VTOL 及未来自主移动平台的**可复用自主系统框架**。它通过合同、插件和受控执行边界组合 Vehicle、Sensor、Perception、World Model、Mission、Action、Intelligence、Protocol、Transport 与 Deployment。通用 Core 不绑定特定比赛、机型、飞控、计算板或感知模型。

系统行为与安全边界见 [V1.0 系统规范](Vehicle_Autonomy_V1.0.md)，七模块归属见 [V1.1 文件结构规范](Vehicle_Autonomy_File_Structure_V1.1.md)，类型与端口语义见 [基础合同冻结规范](docs/foundation_contracts_v1.md)。目标设计不代表全部能力已经实现。

## 安装与七模块源码布局

正式 Python 源码唯一位于 `src/vehicle_autonomy/`：`contracts`、`engine`、
`actions`、`vehicles`、`world`、`autonomy`、`app`。配置在 `configs/`，仿真资源在
`simulation/`；旧根包已移除。先在独立环境安装，再运行下文命令：

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e '.[mavlink]' -r requirements-vision.txt
vehicle-autonomy status
vehicle-autonomy-hardware --check
python -m unittest discover -s tests -v
```

`python -m vehicle_autonomy` 等价于 `vehicle-autonomy`。只读硬件、Web、规划、
锚点与 supervisor 分别使用 `vehicle-autonomy-hardware`、`vehicle-autonomy-web`、
`vehicle-autonomy-plan`、`vehicle-autonomy-anchor`、`vehicle-autonomy-onboard`。
普通 wheel 同时携带配置/仿真资源和所需 ROS 启动脚本；源码安装从仓库定位资源，
不依赖调用者的当前目录。显式外部资源集可通过 `VAF_RESOURCE_ROOT` 指定。
相对用户输入和输出路径仍相对调用目录。完整路径变化及验证见
[架构迁移报告](docs/ARCHITECTURE_MIGRATION_REPORT.md)。

## V1.1 阶段一基础控制

改造范围与增量合同见 [V1.1 记录目录](docs/v1.1/README.md)。专用入口只创建
自己的 loopback Rover/Copter SITL + Gazebo，执行两次独立的 A–F 验收，原始证据
保存在 `artifacts/phase1-control/`。需先按上文安装依赖并使用已配置的 Gazebo/AP 环境：

```bash
./scripts/test_phase1_control.sh --allow-send
```

该入口不连接串口或实车；缺少显式参数不会启动控制测试。默认应用 SEND 仍关闭。
不包含阶段二或外部感知/导航/智能功能。

原开发侧结果保留在[历史阶段一报告](docs/PHASE1_MAVLINK_CONTROL_REPORT.md)，
两个 P1 和两个 P2 的修复记录保留在[第二轮修复报告](docs/PHASE1_REMEDIATION_REPORT.md)。
第二轮独立审查仍为 FAIL：序号回绕后旧 ACK/HEARTBEAT 可错误完成 Disarm。
第三轮修复后，374 项单元测试和两轮完整 Rover/Copter 真实 SITL/Gazebo A–F
均通过，当前状态为 **READY FOR RE-AUDIT**，等待独立审查，未宣布最终阶段一通过。
接收认证、未认证链路的保守功能限制和新证据见
[第三轮修复报告](docs/PHASE1_REMEDIATION_ROUND3_REPORT.md)。
修复回归入口为 `./scripts/test_phase1_control.sh --remediation --allow-send`，
第三轮原始证据另存于 `artifacts/phase1-round3/`。原始审查结论和非敏感证据保留；
条件验收后的 P2 清理销毁了 30 个历史测试 EEPROM，原二进制不再可用，详情见
[凭据清理修复报告](docs/PHASE1_CREDENTIAL_CLEANUP_REPORT.md)。该修复未包含阶段二扩展。

## Phase 2 三车型基础仿真控制

已实现常规 Plane 的原生 TAKEOFF、GUIDED 航点配置、LOITER、RTL、AUTOLAND 接口，
以及独立 Rover profile 的原生 RTL 和 HOLD 回收。默认双 SEND 仍关闭；控制经过
Execution、Safety、Authority 和唯一 MAVLink Writer。Plane 取消保留续飞不确定性，不能用零速停车。
模式确认、目标配置确认与物理运动验收分别记录，详见
[能力矩阵](docs/phase2/CONTROL_CAPABILITY_MATRIX.md)。

开发侧 415 项单元测试、两轮三车型共 18 个真实 SITL/Gazebo 场景通过，包含 Plane
轮式滑跑起飞、实际 AUTOLAND、已写出 TAKEOFF 的取消窗口，以及原生目标排队取消、
Action 交接和只读重连边界。原候选独立 FAIL 已保留，三项缺陷修复后的独立代码及证据
复核建议为 **READY FOR RE-AUDIT**，未发现未解决的 P1/P2/P3；
最终独立验收结论以[三车型报告](docs/PHASE2_THREE_VEHICLE_CONTROL_REPORT.md)及其审查记录为准。

```bash
./scripts/test_phase2_control.sh --allow-send \
  --sitl-bin-dir artifacts/phase2-control/ardupilot-source/build/sitl/bin
```

该入口必须显式提供自有三车型 SITL 二进制；依赖与隔离构建见
[基线记录](docs/phase2/BASELINE.md)。Plane 是专用 SimulationRuntime/仿真验收接口，
尚未开放到 Web/业务任务目录；不包含实机或下一阶段感知/智能开发。

## 当前实现

根目录目前提供 P1 基础合同、P2 离线 World Model 状态链、P3 Typed Action/Mission 决策链、P4 控制边界、P5 ArduCopter/MAVLink/TCP 插件，以及 P6 本机 SITL 单进程模式任务运行组合。通用 TransformTree 求解静态/动态 Frame 关系。P5 已在内存传输、本机 Copter SITL 和已连接 Copter 飞控的受限 USB 模式诊断中验证；此前还完成 Rover 飞控的受限 USB HOLD 诊断。P6 将 Effect 经双 SEND、Lease、Safety 和唯一 writer 分派，并等待 ACK 与后续模式状态。新增显式机载只读部署、认证 Web 控制台和 LLM 提案适配；**尚无经过整车安全验收的生产运动连接**。

2026-10-21 Hardware-Ready 开发：NanoPC-T6/ARM64 的只读应用和 Web 已实际启动，官方 RS16 驱动适配器在 PC/ARM64 编译，真实服务器 LLM 提案已验证。P26 的 10 分钟/100 任务资源门槛通过，但统一导航回归发现越轨和定位新鲜度失败，**P26 尚未通过**。真实 Camera 输入、合格的硬件控制定位、实车动态避障与运动验收仍阻塞。详见 [最终审计](docs/HARDWARE_READY_AUDIT.md)、[启动部署说明](docs/hardware_deployment.md)及[首次接车清单](docs/FIRST_VEHICLE_TEST_CHECKLIST.md)。`hardware_controlled` 配置会被拒绝，不能通过修改 SEND 字段解锁。

用户接线后的增量检查：已修复雷达专用口接收 IP 不匹配，官方 ARM64 SDK 与真实
PointCloud2/LaserScan、真实 PCAP 回放通过，隔离 Humble/Nav2/SLAM 环境已运行；
电脑 USB 收到 Rover 遥测。实际导航资格仍受 GPS/EKF、校准/外参、有限回波覆盖及
安全验收限制；当前命令和完整状态以[接线与环境配置](docs/HARDWARE_CONNECTION_SETUP.md)为准。

当前操作分工：Web 提供任务选择、状态/视频、日志和 AI 提案；地图、点云、TF、
定位与路径使用 ROS 2/RViz2 工具。入口和尚未接入的实车 Nav2 边界见
[ROS 2 操作流程](docs/ROS2_OPERATOR_WORKFLOW.md)。

仿真新增 [LLM 参数化任务编排](docs/LLM_TASK_DESIGN.md)：独立 `yard` 场景提供
装卸点往返、多点巡逻、定距前进、定角旋转、有限绕圆和停留；最多 8 步，
经静态场景、完整车体、环境/会话预检和人工批准执行。Gazebo 提供 3D 场景，
Web 审阅步骤；每步之间必须观察到停车并释放权限。已知静态场景不等于实时避障。
不开放实车运动入口。
历史 LLM 实用场景的 340 项单元、8/8 场景及独立轨迹审计通过；保留的原生启动崩溃及 P26 失败见
[实用场景审计](docs/autonomy/llm-practical-scenarios.md)。

车辆基础仿真使用共享 `SimulationRuntime`、Rover 插件和两主动轮/两后万向轮模型；历史完成范围见[基础车辆审计](docs/simulation/completion-audit.md)。迁移后 342 项单元测试通过，21 个仿真场景中 19 PASS、2 个既有 oracle 启动失败，见[迁移报告](docs/ARCHITECTURE_MIGRATION_REPORT.md)。

后续 **P21–P25 已完成限定本机 Rover 自主导航范围**：命名目标、有限停车后重规划、地图锚点、对象巡检和两种前驱几何。260 项单元测试、最终装配 13 项物理门槛通过；见 [最新完成审计](docs/autonomy/navigation-completion-audit.md)。P26 长运行版本验收及真实硬件仍未完成。

一键构建、启动、真值验收、故障测试和清理：

```bash
./scripts/test_simulation_v1.sh
```

环境与报告位置见[仿真说明](docs/simulation/README.md)。这仅覆盖 localhost SITL + Gazebo；真实飞控和整车仍未验收。

P6 的 localhost SITL 范围已完成；**当前暂缓真实飞控接入**。P5 整车实机验收仍是未完成项，当前能力与缺口以[实现边界](docs/architecture.md)和[硬件审计](docs/HARDWARE_READY_AUDIT.md)为准。

车辆发送默认关闭。P5 命令端口在唯一字节写入点前重新检查系统 SEND、Action SEND、Lease、代际、会话和期限；断链时停止结果保持未确认。TCP/串口连接只能由调用方显式创建；显式 `run-sitl`/`run-sitl-arm` 和受控仿真脚本装配 localhost TCP 与专用 Safety，默认入口不连接车辆。旧演示网关仍使用旧 Effect 测试端口，不能据此宣称已支持实机飞行。

```bash
python -m vehicle_autonomy.app.cli status
python -m unittest discover -s tests -v
```

P6 的配置为 [configs/sitl.toml](configs/sitl.toml)，仅接受数值 loopback 地址和 ArduCopter 四旋翼。先单独启动本机 ArduCopter SITL 的 TCP 5760 端口，再运行 `python -m vehicle_autonomy.app.cli run-sitl --config configs/sitl.toml --allow-send`。省略 `--allow-send` 会连接并发布状态，但 ModeEffect 被授权边界拒绝，且不会写出车辆命令。可用 `tests/manual_p6_sitl.sh configs/sitl.toml '<SITL 版本>'` 验收 ACK 与新心跳状态；版本参数由操作者报告，日志标明来源。P6 只请求一次未解锁 `GUIDED` 模式，不发解锁、起飞、运动或 StopMotion。

另有独立的 **SITL 解锁验收任务**：`python -m vehicle_autonomy.app.cli run-sitl-arm --allow-send --allow-arm` 使用 [解锁专用 profile](configs/sitl_arm.toml)，依次确认 `GUIDED`、Arm 和 Disarm，最终回到未解锁。全新本机 SITL 的验证命令、拒绝记录、取消及未知结果边界见 [SITL 解锁任务验收](docs/sitl_arm_mission.md)。该入口只允许 loopback SITL；不提供起飞或运动命令。

ArduCopter 插件使用 [requirements-p5.txt](requirements-p5.txt) 中的可选依赖。本机 SITL 验证需先自行启动 ArduCopter 的 TCP 5760 端口，再显式运行 `PYTHONPATH=. python tests/manual_p5_sitl.py --allow-send`；脚本仅连接 `127.0.0.1`，确认未解锁后请求 `GUIDED` 模式并等待 ACK。它不会执行起飞或实机连接。

USB 飞控诊断须显式运行 `PYTHONPATH=. python tests/manual_p5_rover_usb.py --port /dev/ttyACM0 --allow-send`（实际设备路径可用 `/dev/serial/by-id/...`）。脚本仅接受 ArduPilot Rover 心跳，要求飞控已处于未解锁的 HOLD 模式，经过同一 Execution/双 SEND/Safety/唯一 writer 链发送一次 HOLD 请求，并等待 ACK 与后续状态。该诊断不提供解锁、运动或参数修改能力；这不等于 Copter 实机或整车运动验收。

Copter USB 诊断使用 `PYTHONPATH=. python tests/manual_p5_copter_usb.py --port /dev/ttyACM1 --allow-send`（连接路径可能改变，优先使用对应 `/dev/serial/by-id/...`）。脚本仅接受 ArduPilot 四旋翼心跳，要求飞控未解锁且已在 STABILIZE 模式，只发送一次 STABILIZE 同模式请求并检查 ACK 与后续状态。它不提供解锁或运动请求；USB 控制器通过不等于整车飞行或停止验收。

当前裸飞控的 `FRAME_CLASS=0`（未定义），持续报告机架类别/类型预解锁错误。机架参数须按实际装配选择，且改变后需重启；目前未为裸飞控指定一个假定机架，也未关闭预解锁检查。USB 遥测检查见[迁移记录](docs/migration_plan.md)。

裸飞控台架曾临时配置 `FRAME_CLASS=1`、保留 `FRAME_TYPE=1`（四旋翼 X）并重启。通过受控端口验证未解锁的 `STABILIZE → ACRO → STABILIZE`；Arm 请求由飞控预解锁检查拒绝，随后 Disarm 请求获确认。测试结束已恢复 `FRAME_CLASS=0` 并重启复核。复现台架脚本须分别显式运行 `PYTHONPATH=. python tests/manual_p5_copter_bench_mode.py --port /dev/ttyACM0 --allow-mode-roundtrip` 与 `PYTHONPATH=. python tests/manual_p5_copter_bench_arm.py --port /dev/ttyACM0 --bare-controller --allow-arm-bench`；路径随重新连接可能变化，**Arm 脚本仅供确认没有执行器连接的裸飞控使用**。预解锁阻断、日志存储错误和未验收项见[迁移记录](docs/migration_plan.md)。

[当前实现边界](docs/architecture.md)说明已有能力与限制；[历史迁移与台架记录](docs/migration_plan.md)保留早期合同、模式诊断和安全审计。P9–P17 的结果见[基础自主系统审计](docs/autonomy/completion-audit.md)，P21–P25 见[自主导航完成审计](docs/autonomy/navigation-completion-audit.md)。未通过的 P26 门槛见[验收规范](docs/autonomy/phase-26-plan.md)。

## 本机仿真应用进程

先启动自己的 localhost SITL/Gazebo，再运行：

```bash
python -m vehicle_autonomy.app.cli run --profile copter_sim --allow-send
python -m vehicle_autonomy.app.cli ctl --profile copter_sim status
python -m vehicle_autonomy.app.cli ctl --profile copter_sim start --mission disarmed_mode
python -m vehicle_autonomy.app.cli ctl --profile copter_sim shutdown
```

Rover 使用 `rover_sim`。不传 `--allow-send` 为只读；任务目录包括 disarmed_mode、action_probe、basic_route 与 safe_recovery；显式对象源可启用 object_inspection，Copter 另需显式仿真载荷才可运行 cuadc_demo。没有活跃任务时撤销双 SEND 与租约，重连只读恢复。`--config` 可提供经严格验证的 loopback 仿真 profile；`--control-socket` 指定本机端点。不是实机或 Web 入口。

两车命名路线从公开控制入口启动：

```bash
python -m vehicle_autonomy.app.cli ctl --profile copter_sim start --mission basic_route
python -m vehicle_autonomy.app.cli ctl --profile rover_sim start --mission basic_route
```

记录视觉需要 [可选 CPU 依赖](requirements-vision.txt)。`python scripts/prepare_vision_fixture.py` 下载并校验公开模型/照片，生成虚拟标定与有限记录清单。以下命令仅用于已启动的 localhost Copter 仿真：

```bash
python -m vehicle_autonomy.app.cli run --profile copter_sim --allow-send --sim-payload \
  --recorded-vision-config artifacts/simulation/vision-assets/recording.json
python -m vehicle_autonomy.app.cli ctl --profile copter_sim start --mission cuadc_demo
```

视觉源和 `--sim-sensor-config` 互斥，默认不加载任何对象源或载荷。该 fixture 的 COCO bus→bucket_1 映射只验证传感器替换边界；真实比赛识别、相机空间标定、物理载荷与 RKNN 均未验收，见 [P17](docs/autonomy/phase-17.md)。

## 可选 ROS 2 Mapping

本机 Rover 仿真增加可选 ROS 2 Jazzy / SLAM Toolbox 二维建图组合，复用正式 Application、`basic_route` Mission 和原有安全执行链。实际 Gazebo 激光经单向桥接进入 SLAM，地图作为带时间和版本的只读资源进入 `WorldSnapshot.map`；ROS 不直接控制车辆，普通框架运行无需安装 ROS。

安装、运行、坐标/时间边界和已知地图边界缺陷见 [Mapping 说明](docs/ros2_mapping.md)，验收范围见 [P18](docs/autonomy/phase-18.md)。P18 不含 Nav2、地图避障、SLAM 控制定位切换或真实设备；新增只读规划见下节。

## 可选 Nav2 只读路径规划

新增 `python -m vehicle_autonomy.app.planning`，从记录地图或当前只读 Rover App 的 P18 地图计算几何路径。使用 ROS 2 Jazzy / Nav2 SmacPlanner2D，返回前核对地图内容、版本来源、Frame epoch、时间和整段车体碰撞。规划入口输出保持 `executable=false`；显式路径消费使用下一节的独立准入与原安全执行链。

安装与可直接运行的记录图示例见 [Nav2 规划说明](docs/nav2_planning.md)；206 项单元测试、真实 Nav2 拒绝/绕墙/超时及在线只读链证据见 [P19 第一步验收](docs/autonomy/phase-19.md)。

## 可选 Rover 路径跟踪

显式 `--navigation-config` 为本机前驱两轮/后万向轮 Rover 模型注册 `follow_path` Mission。它按主动轮轴参考点消费新鲜在线路径，经 GUIDED、Arm、Typed Twist、观察停车和 Disarm 完成有限任务；持续检查当前地图、map/odom 对齐、路径文件和横向偏离。地图失效时走原 Stop 屏障，默认双 SEND 仍关闭。

配置、参考点/余量语义和操作步骤见 [路径跟踪说明](docs/rover_path_following.md)，实测范围见 [P20 审计](docs/autonomy/phase-20.md)。P20 基线复现命令 `./scripts/test_navigation_v1.sh`，仅创建自有 localhost SITL/Gazebo。

## 可选命名目标、自主路线与车型装配

显式目标目录可注册 `navigate:POINT_A`，由 Application 在后台组织 Nav2 规划、最新地图准入及原 Mission/执行链。策略默认不重试；明确授权后可在路径阻断、观察停车及 Disarm 后有限重规划。`autonomy:INSPECT` 组合命名路线、有效对象观测及检查点结果，取消/失败执行 Stop/Disarm 清理。

导航模型显式注入参考点、几何包络和运动界限；第二种已验收车型是不同轴距/轮距/质量的紧凑前驱 Rover，不能只换配置就声称既有世界已换车。地图锚点绑定 Environment/HOME、地图源及车辆会话；SLAM 位姿仍是只读候选，活动控制继续使用遥测 Localization。

配置、实际 SDF、地图边界修复及阶段验收范围见 [自主导航说明](docs/rover_autonomy.md) 和 [验收记录](docs/autonomy/navigation-completion-audit.md)。顺序复现入口：`./scripts/test_autonomy_navigation.sh --allow-send`。各阶段以独立审计中的 PASS 为准；P26 统一版本/长运行及真实设备不由此完成。

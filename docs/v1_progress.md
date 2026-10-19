# Vehicle Autonomy Framework V1：模块进度与未完成项

> 复核日期：2026-10-19。本机 ROS 2 Mapping 见 [P18](autonomy/phase-18.md)，只读 Nav2 规划见 [P19](autonomy/phase-19.md)，正式 Mission 路径消费与物理跟踪见 [P20](autonomy/phase-20.md)。P9–P15 与 P17 软件基线见 [自主系统完成审计](autonomy/completion-audit.md)。本文只计新框架根目录；`legacy/cuadc_2026/` 的历史实现不计入新框架进度。目标职责见 [V1 目标架构](framework_v1.md)。

## 进度口径

后续优先级、依赖与验收门槛见 [P20 之后的总计划](autonomy_roadmap.md)。该路线图是规划，不改变本文按实际证据记录的完成度。

下面的百分比是**按证据分档的模块成熟度估计**，不是代码量、工时或整个系统的加权完成率。同一模块只取当前达到的最高档；目录占位不算实现。

| 档位 | 判定依据 |
| --- | --- |
| 0% | 尚无该模块的具体能力实现。 |
| 25% | 有合同、假实现、示例或局部工具，但不能完成目标职责。 |
| 50% | 有可独立运行且经过离线测试的目标能力，尚未进入完整运行组合。 |
| 75% | 已进入仿真或受限设备链验证，仍缺所声称使用环境的完整验收。 |
| 100% | 已完成该行写明的明确范围及相应验收；不代表所有未来插件和场景都实现。 |

**阶段进度：** P0 是限定范围的基线审计；P1–P4 已完成各自阶段门槛。P5 已完成 ArduCopter 软件组合、本机 SITL 和受限 USB/裸飞控台架验证。P6 已完成 localhost SITL 持续运行模式任务，其后的独立 SITL 解锁/上锁任务也已验证。**整车实机验收未完成，当前暂缓真实飞控接入。** 阶段状态不是整个系统的加权完成率。

本轮另按 [SIMULATION_COMPLETION_PLAN](../SIMULATION_COMPLETION_PLAN.md) 执行 **Phase 0–8**，与历史迁移 P0–P6 分开计数。Phase 0–8 的 mandatory gates 已完成，**基础车辆控制 Simulation Complete：PASS**。Copter/Rover 基础控制的仿真范围有完整正常/故障/重复回归证据，见[完成审计](simulation/completion-audit.md)。实机、其他车辆及无关模块没有据此升为 100%。

**历史车辆基线完成度：100%（仿真基础车辆控制，9/9 阶段）**。最终干净构建回归为 `artifacts/simulation/suite-015782bd/`：125 单元测试、5 场景、0 失败/跳过/未运行，清理通过。下面的通用模块成熟度不等于本轮范围完成度，真实设备缺口保持未验收；新增业务能力以以下当前证据为准。

## 1. 基础语义与状态链

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| P1 基础合同 | **100%** | 时间、Frame、Observation、VehicleState、WorldSnapshot、Typed Effect 和端口已有实现及测试；见 [时间合同](../contracts/core/time.py)、[世界合同](../contracts/world/models.py)、[合同测试](../tests/test_foundation_contracts.py)。 | 此 100% 仅指冻结的**基础合同范围**；未来可选模块的合同随具体组合增加。 |
| Transform 求解 | **75%** | P10 在线 `odom↔base_link`、同源 cut、动态历史有界、插值/无外推和重连 epoch 已经进入两车正式 App；见 [P10](autonomy/phase-10.md)。 | 真实设备、其他 Frame 来源与实际标定未验收；World Model 不隐式转换。 |
| VehicleState 遥测适配 | **75%** | Copter 状态适配及 [Rover GPS 原点/ENU 适配](../vehicles/rover/mavlink_state.py)已在 SITL + Gazebo 验证；仿真源时钟按会话映射，延迟/重复样本保留年龄。 | 生产设备采集时间和硬件同步未验收；USB 接收时间代理不能直接用于真实运动 Safety。 |
| Sensor Adapter | **75%** | 显式只读 Gazebo 对象源及有限记录图像源已有来源、capture/receive、质量、版本、失效、健康和丢帧处理；见 [P14](autonomy/phase-14.md)、[P17](autonomy/phase-17.md)。 | 未接真实 Camera/LiDAR 设备；记录图像使用虚拟标定。 |
| Perception | **75%** | CPU OpenCV DNN YOLOX 实际推理、像素检测和显式平面投影通过离线与 App 业务替换验收。 | 仅限公开 bus fixture；比赛目标模型、现场精度、真实标定、跟踪、障碍物和 RKNN 未验收。 |
| Localization | **75%** | P10 将遥测自报位姿投影到正式版本化状态链，保留源 capture/epoch，GPS fix 使用同一已验证 SITL boot 时间域。 | 自报位姿不构成独立定位真值或 GPS/VIO/SLAM 融合；真实时间同步未验收。 |
| Mapping | **75%（限定 Rover 二维仿真场景）** | 真实 Gazebo 激光→ROS 2/SLAM Toolbox→不可变版本地图→WorldSnapshot.map；导出/pose graph 重载见 [P18](autonomy/phase-18.md)，限定在线路径消费见 [P20](autonomy/phase-20.md)。 | 轴对齐房间的边界墙面缺失尚未解决；无任意场景可靠性、真实 LiDAR、三维或长期存储验收。 |
| Environment | **100%（命名仿真资源范围）** | P11 不可变 origin/home/geofence/命名点/区域、内容 SHA、会话绑定、原点检查和资源热变更拒绝已通过；见 [P11](autonomy/phase-11.md)。 | 不含地图生产、实测现场原点或设备校准。 |
| World Model | **75%** | 正式 App 持续发布同源 Vehicle/Localization、Environment、对象 Observation；P18 增加带时间/版本/依赖的可选地图引用，拒绝过期/异域/冲突序号。 | 不做隐式跨 Frame 转换或 SLAM 位姿融合；真实设备采集时间未验收。 |
| 状态链组合 | **75%** | [SimulationRuntime](../deployment/simulation_runtime.py)共享两车遥测→World Model 链；正常、断连、重启和时钟故障验收通过。 | 无真实传感器或生产设备时间映射；当前仅覆盖 Copter/Rover 仿真组合。 |

## 2. 决策链

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Action | **75%** | 有限基本运动、目标业务与前轴参考点路径跟踪均只读状态、产 Typed Effect，有物理结果及停车屏障；见 [P12](autonomy/phase-12.md)、[P15](autonomy/phase-15.md)、[P20](autonomy/phase-20.md)。 | 实车行为、任意路径和通用动态避障未验收；业务能力按注册参数限制。 |
| Mission | **75%** | 两车 basic_route、CUADC、inspection 和显式 follow_path 均通过公开 CLI；路径跟踪、取消、地图丢失、文件修改和超时见 [P20](autonomy/phase-20.md)。 | 不含自动重规划、AI 提案或生产任务配置。 |
| Intent / MissionProposal | **0%** | [目标架构](framework_v1.md#3-四类核心数据及其边界)定义了上层目标进入系统的边界，当前无对应的 V1 类型与校验用例。 | 仅在接入操作者提案或 Intelligence 时实现标准提案、校验和转 Mission/Action 的流程。 |
| Planning | **75%（限定 Rover 二维仿真）** | [P19](autonomy/phase-19.md) 真实 Nav2 后端和独立几何校验；[P20](autonomy/phase-20.md) 增加在线计划准入、map/odom 绑定、当前地图复核及正式 Mission 物理路径跟踪。 | 自动重规划、动态避障、时间轨迹、其他车辆和任意场景未验收；记录计划仍只读。 |
| Guidance | **75%（限定前驱 Rover 二维仿真）** | 前轴参考点、单调局部进度、自适应前视和航向反馈；经原 Typed Effect / 安全链完成路径、取消及故障停车，见 [P20](autonomy/phase-20.md)。 | 仅支持已验收模型与有限静态路径；其他运动学、长复杂路径、最终 yaw、轨迹和真实设备未验收。 |
| Intelligence | **0%** | 仅有包占位。 | 无 Intent/MissionProposal 的实际生成、校验或模型接入；不是首个无 AI 组合的必需条件。 |

## 3. 控制、车辆与设备链

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Execution | **75%** | [VehicleExecution](../core/vehicle_execution.py)经双 SEND、Lease、Safety 和唯一 writer 分派；两车运动、Stop、Cancel、deadman 与故障结果有 Gazebo 真值证据。 | 实车执行器、物理停止、长期部署和其他副作用尚未验收。 |
| 非车辆 Effect | **75%** | 独立合同 ReleasePayloadEffect、专属 PayloadExecution/SimPayloadPort 与显式授权/Safety/幂等/结果链经过验收。 | 仅仿真库存/位置标记；真实载荷、拍照、文件等其他副作用需独立合同及验收。 |
| Authorization | **75%** | [ControlAuthority](../core/control_authority.py)默认关闭双 SEND，管理 Lease、代际、撤销和会话；写前在唯一 writer 处复核。 | 尚无生产控制源仲裁、操作配置及整车场景验收。 |
| Safety | **75%** | 原 TTL、时间域、定位、模式、Frame、围栏和速度检查保留；[P20](autonomy/phase-20.md) 为显式导航增加原 writer 处地图/文件/偏离/扫掠检查，地图失效仍允许原 Stop。 | 实车限值、传感器质量、下降率规则及失联处置仍须专门审核；仿真通过不构成真实飞行安全验收。 |
| ArduCopter Vehicle Plugin | **75%** | 命令、会话、状态及唯一 writer 已通过 Mode/Arm/Disarm/Takeoff/Hold/Goto/Velocity/Stop/RTL/Land/Cancel 的 SITL + Gazebo 正常和故障验收。 | 实际机架、执行器输出、真实飞行、停车与失联未验收；原 USB 台架结果仍仅为受限诊断。 |
| Rover Vehicle Plugin | **75%** | [翻译器](../vehicles/rover/ardupilot_commands.py)、[状态适配](../vehicles/rover/mavlink_state.py)复用公共运行时；目标两主动轮/两后万向轮 Gazebo 模型的前后、转弯/pivot、Goto、Stop、Cancel、deadman 和重启通过。 | 无真实汽车/执行器验收；禁止把仿真或历史 HOLD USB 诊断视作整车支持。 |
| 其他 Vehicle Plugin | **0%** | 固定翼、VTOL 等无实现。 | 仅在选择相应机型时开发；不应计作当前 ArduCopter 组合的阻塞项。 |
| MAVLink Protocol | **75%** | [MAVLink 2 codec](../protocols/mavlink/codec.py)覆盖两车基础命令/状态子集；运动、ACK/状态超时和旧队列隔离已验证。 | 不是 MAVLink 全量实现；生产连接仍需按设备与固件验收。 |
| Transport | **75%** | [TCP/串口字节传输](../infrastructure/transports/bytes.py)显式创建；localhost TCP 断连、重连、写出不确定性及代理注入已验收。 | 无根框架 UDP 或生产链路运维组合；真实链路需要独立验收。 |

## 4. 应用、部署与外部接口

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Application 用例 | **75%** | 正式长运行 App 的状态、注册任务启动/取消/关闭经过本机 IPC 与实际子进程验收。 | 无 Web API、生产控制源仲裁或远程服务。 |
| 具体 Applications / Missions | **75%** | 命名两车路线、cuadc_demo 和 object_inspection 有正式配置及完整仿真业务证据；旧模块依赖/安全只读审查后重写。 | 真实比赛/现场业务未验收；新根不导入历史代码。 |
| App 进程入口 | **75%** | `app.main run/ctl` 支持本机白名单任务、有限 IPC、默认只读、重连新 epoch；显式可替换对象源/仿真载荷。 | 无 onboard/server 入口或生产车辆连接。 |
| Deployment | **75%** | [SimulationRuntime](../deployment/simulation_runtime.py)负责共同车辆周期、状态、结果、授权/停止及会话生命周期；独立构建和自有进程清理已有完整回归。 | 真实设备同步、生产重连/部署和实车停车未验收；没有 onboard/server 入口。 |
| Gateway | **0%** | 仅有包占位。 | 无远程接入、链路监视和本地失联处置；只有远程部署需要。 |
| Web UI | **0%** | 仅有包占位。 | 无界面或 Web API；不是首个无 Web 组合的必需条件。 |
| 独立运行配置 | **100%（localhost 仿真范围）** | Copter/Rover 严格 TOML profile 显式指定机型、模式、周期、时钟和 Safety，SEND 默认关闭；每轮使用匹配的空闲端口与新状态目录。 | 不含生产车辆或可发送的 onboard profile。 |
| 自动化测试与验收 | **75%** | 历史完整回归 29 阶段/21 场景 PASS；P20 最新全量 **223 项单元测试**及 **5 项 Rover 路径跟踪正常/故障物理场景**通过，见 [P20](autonomy/phase-20.md)。未重跑整套历史套件或 Copter 物理任务。 | 实车物理停止、设备和生产部署未验收。 |

## 5. P6 完成后的工作范围

[P6 实施与验收](p6_runtime_integration_plan.md)已证明 localhost ArduCopter SITL 中状态、Mission、Effect、Execution、ACK 和新状态构成持续运行闭环。独立的[解锁/上锁 SITL 任务](sitl_arm_mission.md)进一步验证了受限的三步任务；这仍只是仿真能力。当前决定**暂缓真实飞控接入**：P5 的整车设备验收保持未完成，不建设可发送的 onboard profile，也不把 SITL 的接收时间代理视为真实采集时间。

下列 P6 后工作已由 P9–P15 完成；新增需求再独立立项：

1. **确定首个非比赛业务 Mission：** 明确输入、输出、所需车辆能力和完成判据；现有 `SitlRuntime` 的模式/解锁步骤仍是固定诊断任务，不是通用任务目录。
2. **将运行组合扩展为可装配任务：** 在 Application 合同下接收经过预检的 Typed Mission 和 Action 注册，不让业务模块持有车辆端口；保持双 SEND 默认关闭、唯一 writer、结果回流和单进程生命周期语义。
3. **按任务需要增加模块与 SITL 验收：** 只实现所选任务确实依赖的 Sensor、Environment、Planning、Guidance 或非车辆 Effect。本轮已完成两车基础 Effect 运动、取消、deadman、stop/zero 与断链未确认结果的 SITL/Gazebo 验收；P12/P13/P15 已有独立 Action/Mission 组合验收。

真实飞控重新纳入范围时，再单独制定设备时间同步、机架/传感器校准、日志、物理运动、停止和失联保护的验收计划。此前车辆基线只按仿真证据更新车辆链；本次增加 P9–P15/P17 的软件与业务证据，真实整车能力仍未完成。

## 验证边界

历史 `final-unit.json` 为 177 项；2026-10-19 P18 为 190 项，P19 为 206 项，P20 最新全量单元测试为 **223 项通过，0 失败/错误/跳过**；另有 **5 项导航物理场景 PASS**，准确范围见 [P20](autonomy/phase-20.md)，未重跑整套 29 阶段或 Copter 物理任务。`python -m app.main status` 仍返回 `mission_scheduler=unwired`、`vehicle_connection=unwired`、`send_commands=false`，表示默认入口不连接车辆。历史模式/解锁见[记录](sitl_arm_mission.md)，车辆基础真值验收见[仿真审计](simulation/completion-audit.md)；均不替代实机运动、物理停止或服务器部署验收。

更新本文时应同时更新基线提交、运行测试、模块证据和未完成项。若某模块只因新增文件而没有达到更高档位的验证要求，进度分档不应上调。

## P9 Application Runtime（2026-10-03）

**PASS**：两车正式 App 进程、受限模式任务、IPC、取消、SIGTERM、重连只读及完整车辆回归。证据见 [P9](autonomy/phase-9.md)。后续已验收状态见下文，真实硬件仍暂缓。

## P10 在线状态链

**PASS**：同源 Vehicle/Localization/Transform、拒绝外推、有界历史、新会话隔离，两车完整正常/故障回归。见 [P10](autonomy/phase-10.md)。

## P11 Environment

**PASS**：命名点/HOME/区域/围栏、显式来源、资源版本/会话绑定、配置变化和原点拒绝。两车正式 App、命名点物理验收及完整正常/故障回归通过，见 [P11](autonomy/phase-11.md)。

**P12 PASS**：有限基本 Action、物理结果及退出屏障已通过正式 App 和完整回归，见 [P12](autonomy/phase-12.md)。

## P13–P17 当前结果

**P13–P15 PASS（localhost 仿真）**：基础双车 Mission、标准对象输入、CUADC 非视觉业务链及专属受控仿真载荷均完成；来源、时间、Frame、授权、结果与物理 Oracle 证据见各阶段审计。**P17 PASS（记录图像/虚拟标定软件范围）**：实际 CPU YOLOX 替换相同 Observation 边界，业务正常、取消及图像损坏过期场景通过。**P16 暂缓**，真实相机/标定、比赛桶模型、物理载荷和 RKNN 未验收。

完整命令、阶段提交、测试计数及剩余范围见 [自主系统完成审计](autonomy/completion-audit.md)。P9–P17 覆盖的可执行软件范围已完成；P19 新增只读 Planning，P20 新增限定 Rover 路径消费与跟踪。动态重规划、LLM、Agent、Web、生产服务器和其他车辆仍按需求独立立项。

## P18 本机 ROS 2 Mapping（2026-10-19）

实现可选二维建图数据链，复用既有 Application/Mission/安全执行链；P18 当时地图位姿仅供诊断，后续 P20 显式绑定平面 map/odom 关系用于路径消费，仍不替换遥测 Localization。限定场景、最终回归和失败证据见 [P18](autonomy/phase-18.md)。轴对齐边界缺陷仍开放；不能将限定场景 PASS 推广为通用建图完成。P16 真实设备继续暂缓。

## P19 第一步：只读 Nav2 规划（2026-10-19）

**PASS（只读二维几何路径）**：记录地图与当前只读 App/SLAM 地图可通过独立入口生成路径，地图依赖、Frame/时间、整段车体检查、不可达拒绝和超时清理均有证据。P19 本身不执行运动，后续消费见 P20。[验收记录](autonomy/phase-19.md)。

## P20：正式 Mission 路径消费与跟踪（2026-10-19）

**PASS（限定前驱 Rover / 在线二维地图 / localhost SITL + Gazebo）**：路径准入、主动轮轴参考点、map/odom 有限绑定、Guidance、Typed Effect、原授权/Safety/唯一 writer 和地图失效停车构成运行闭环。**223 单元测试、5 项独立正常/故障物理场景全部通过**。正常路线 2.316 m，独立真值最大偏离 0.124 m、目标误差 0.075 m；取消、地图丢失、文件修改与超时均在原 8 s 内确认停车，进程/端口清理通过。运行与保留限制见 [说明](rover_path_following.md)，源码哈希、失败过程和证据见 [审计](autonomy/phase-20.md)。这不是整个系统或通用导航的 100% 完成。

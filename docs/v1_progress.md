# Vehicle Autonomy Framework V1：模块进度与未完成项

> 复核日期：2026-10-02。运行源码基线提交：`fcbbe46`（仿真最终审计另行提交）。本文审计新框架根目录；`legacy/cuadc_2026/` 中的历史实现不计入新框架进度。目标职责见 [V1 目标架构](framework_v1.md)，已经验证的阶段范围见 [迁移计划](migration_plan.md)。

## 进度口径

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

**本轮范围完成度：100%（仿真基础车辆控制，9/9 阶段）**。最终干净构建回归为 `artifacts/simulation/suite-015782bd/`：125 单元测试、5 场景、0 失败/跳过/未运行，清理通过。下面的通用模块成熟度不等于本轮范围完成度，仍保留真实设备和业务能力缺口。

## 1. 基础语义与状态链

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| P1 基础合同 | **100%** | 时间、Frame、Observation、VehicleState、WorldSnapshot、Typed Effect 和端口已有实现及测试；见 [时间合同](../contracts/core/time.py)、[世界合同](../contracts/world/models.py)、[合同测试](../tests/test_foundation_contracts.py)。 | 此 100% 仅指冻结的**基础合同范围**；未来可选模块的合同随具体组合增加。 |
| Transform 求解 | **50%** | [TransformTree](../core/transform.py)支持静态/动态关系与按时间求解，已有[离线测试](../tests/test_transform.py)。 | 未接入正式状态/任务组合；World Model 仍保留输入的原始 Frame。 |
| VehicleState 遥测适配 | **75%** | Copter 状态适配及 [Rover GPS 原点/ENU 适配](../vehicles/rover/mavlink_state.py)已在 SITL + Gazebo 验证；仿真源时钟按会话映射，延迟/重复样本保留年龄。 | 生产设备采集时间和硬件同步未验收；USB 接收时间代理不能直接用于真实运动 Safety。 |
| Sensor Adapter | **25%** | [假传感器](../sensors/fake.py)可构造标准观测并用于离线状态链。 | 无真实 Camera/LiDAR 等采集、源时间戳、健康和设备接入。按首个组合的实际传感器需求实现。 |
| Perception | **0%** | 仅有包占位；标准 Observation 合同在基础层。 | 无检测、跟踪、障碍物或其他模型的实现及接入。仅在选用感知能力时成为必需项。 |
| Localization | **25%** | [自报位姿投影](../localization/reported.py)可从 VehicleState 生成独立定位结果。 | 无真实定位或融合算法及其质量验证；当前投影不等于 GPS/VIO/SLAM。 |
| Mapping | **0%** | 仅有包占位。 | 无地图生产、版本管理和向 World Model 发布；按场景需要建设。 |
| Environment | **0%** | 仅有包占位。 | 无场景坐标基准、命名位置、静态地图或环境围栏适配；按首个任务需要建设。 |
| World Model | **75%** | [WorldModel](../world_model/service.py)可发布版本化只读快照，现已在 P6 SITL 进程中持续接收飞控状态并发布。 | 尚不接地图/Environment，不做跨 Frame 变换；真实设备采集时间未验收。 |
| 状态链组合 | **75%** | [SimulationRuntime](../deployment/simulation_runtime.py)共享两车遥测→World Model 链；正常、断连、重启和时钟故障验收通过。 | 无真实传感器或生产设备时间映射；当前仅覆盖 Copter/Rover 仿真组合。 |

## 2. 决策链

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Action | **75%** | P6 [模式 Action](../core/sitl_mode_action.py)只发一次 ModeEffect，并读结果确认 ACK 后的新未解锁目标模式；离线及 SITL 验收通过。 | 仍无实际业务 Action；运动仿真由受控 Effect 验收场景驱动，不等于通用业务任务目录。 |
| Mission | **75%** | [MissionRuntime](../core/mission_runtime.py)支持 Effect 结果回流；P6 在持续运行进程中完成最小 Typed Mission，拒绝、未知与取消不会变为成功。 | 条件/分支仍按实际任务需求加入；P6 仅为单步 SITL 模式任务。 |
| Intent / MissionProposal | **0%** | [目标架构](framework_v1.md#3-四类核心数据及其边界)定义了上层目标进入系统的边界，当前无对应的 V1 类型与校验用例。 | 仅在接入操作者提案或 Intelligence 时实现标准提案、校验和转 Mission/Action 的流程。 |
| Planning | **0%** | 仅有包占位。 | 无路径/轨迹/避障算法；仅在所选 Action 需要规划时实施。 |
| Guidance | **0%** | 仅有包占位。 | 无从计划/状态到运动目标的算法；仅在所选 Action 需要导引时实施。 |
| Intelligence | **0%** | 仅有包占位。 | 无 Intent/MissionProposal 的实际生成、校验或模型接入；不是首个无 AI 组合的必需条件。 |

## 3. 控制、车辆与设备链

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Execution | **75%** | [VehicleExecution](../core/vehicle_execution.py)经双 SEND、Lease、Safety 和唯一 writer 分派；两车运动、Stop、Cancel、deadman 与故障结果有 Gazebo 真值证据。 | 实车执行器、物理停止、长期部署和其他副作用尚未验收。 |
| 非车辆 Effect | **0%** | 当前 V1 [Effect 类型](../contracts/effects/vehicle.py)与新 Execution 仅覆盖车辆命令。 | 若首个组合需要拍照、保存文件或其他副作用，须定义各自合同和受控端口，并由 Execution 分派。 |
| Authorization | **75%** | [ControlAuthority](../core/control_authority.py)默认关闭双 SEND，管理 Lease、代际、撤销和会话；写前在唯一 writer 处复核。 | 尚无生产控制源仲裁、操作配置及整车场景验收。 |
| Safety | **75%** | 通用 [VehicleSafetyPolicy](../core/vehicle_safety.py)与[仿真专用策略](../deployment/simulation_safety.py)检查 TTL、时间域、新鲜定位、解锁/模式、Frame、围栏和速度；两车拒绝路径与物理停止已在仿真验证。 | 实车限值、传感器质量、下降率规则及失联处置仍须专门审核；仿真通过不构成真实飞行安全验收。 |
| ArduCopter Vehicle Plugin | **75%** | 命令、会话、状态及唯一 writer 已通过 Mode/Arm/Disarm/Takeoff/Hold/Goto/Velocity/Stop/RTL/Land/Cancel 的 SITL + Gazebo 正常和故障验收。 | 实际机架、执行器输出、真实飞行、停车与失联未验收；原 USB 台架结果仍仅为受限诊断。 |
| Rover Vehicle Plugin | **75%** | [翻译器](../vehicles/rover/ardupilot_commands.py)、[状态适配](../vehicles/rover/mavlink_state.py)复用公共运行时；目标两主动轮/两后万向轮 Gazebo 模型的前后、转弯/pivot、Goto、Stop、Cancel、deadman 和重启通过。 | 无真实汽车/执行器验收；禁止把仿真或历史 HOLD USB 诊断视作整车支持。 |
| 其他 Vehicle Plugin | **0%** | 固定翼、VTOL 等无实现。 | 仅在选择相应机型时开发；不应计作当前 ArduCopter 组合的阻塞项。 |
| MAVLink Protocol | **75%** | [MAVLink 2 codec](../protocols/mavlink/codec.py)覆盖两车基础命令/状态子集；运动、ACK/状态超时和旧队列隔离已验证。 | 不是 MAVLink 全量实现；生产连接仍需按设备与固件验收。 |
| Transport | **75%** | [TCP/串口字节传输](../infrastructure/transports/bytes.py)显式创建；localhost TCP 断连、重连、写出不确定性及代理注入已验收。 | 无根框架 UDP 或生产链路运维组合；真实链路需要独立验收。 |

## 4. 应用、部署与外部接口

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Application 用例 | **75%** | [MissionService](../application/mission_service.py)提供启动、取消、查询与关闭用例；P6 离线闭环已验证。 | 无外部 API、操作者控制源仲裁或其他业务 Mission。 |
| 具体 Applications / Missions | **25%** | 本机 SITL 有独立的模式任务及[解锁/上锁验收任务](sitl_arm_mission.md)，均为受限诊断 Mission。 | 无首个实际业务 Mission；旧比赛任务仍在 `legacy/`。 |
| App 进程入口 | **75%** | [CLI](../app/main.py)显式 `run-sitl` 和 `run-sitl-arm` 可启动 localhost SITL 单进程；解锁入口需要双重显式开关。 | 无 onboard/server 入口或生产车辆连接。 |
| Deployment | **75%** | [SimulationRuntime](../deployment/simulation_runtime.py)负责共同车辆周期、状态、结果、授权/停止及会话生命周期；独立构建和自有进程清理已有完整回归。 | 真实设备同步、生产重连/部署和实车停车未验收；没有 onboard/server 入口。 |
| Gateway | **0%** | 仅有包占位。 | 无远程接入、链路监视和本地失联处置；只有远程部署需要。 |
| Web UI | **0%** | 仅有包占位。 | 无界面或 Web API；不是首个无 Web 组合的必需条件。 |
| 独立运行配置 | **100%（localhost 仿真范围）** | Copter/Rover 严格 TOML profile 显式指定机型、模式、周期、时钟和 Safety，SEND 默认关闭；每轮使用匹配的空闲端口与新状态目录。 | 不含生产车辆或可发送的 onboard profile。 |
| 自动化测试与验收 | **75%** | 125 项根目录单元测试通过；[一键回归](simulation/README.md)包含干净构建、两车真值运动、故障和清理，四轮全套通过。 | 整车设备、真实物理停车与生产部署未验收；其余能力按各自范围验证。 |

## 5. P6 完成后的工作范围

[P6 实施与验收](p6_runtime_integration_plan.md)已证明 localhost ArduCopter SITL 中状态、Mission、Effect、Execution、ACK 和新状态构成持续运行闭环。独立的[解锁/上锁 SITL 任务](sitl_arm_mission.md)进一步验证了受限的三步任务；这仍只是仿真能力。当前决定**暂缓真实飞控接入**：P5 的整车设备验收保持未完成，不建设可发送的 onboard profile，也不把 SITL 的接收时间代理视为真实采集时间。

当前可继续的软件工作按实际业务需要推进：

1. **确定首个非比赛业务 Mission：** 明确输入、输出、所需车辆能力和完成判据；现有 `SitlRuntime` 的模式/解锁步骤仍是固定诊断任务，不是通用任务目录。
2. **将运行组合扩展为可装配任务：** 在 Application 合同下接收经过预检的 Typed Mission 和 Action 注册，不让业务模块持有车辆端口；保持双 SEND 默认关闭、唯一 writer、结果回流和单进程生命周期语义。
3. **按任务需要增加模块与 SITL 验收：** 只实现所选任务确实依赖的 Sensor、Environment、Planning、Guidance 或非车辆 Effect。本轮已完成两车基础 Effect 运动、取消、deadman、stop/zero 与断链未确认结果的 SITL/Gazebo 验收；新业务 Action/Mission 仍需自己的组合验收。

真实飞控重新纳入范围时，再单独制定设备时间同步、机架/传感器校准、日志、物理运动、停止和失联保护的验收计划。本轮只按仿真证据更新 Vehicle、Safety、Transport 的说明；真实整车能力仍未完成。

## 验证边界

本次复核执行 `python -m unittest discover -s tests -q`：**125 项通过，0 失败、0 跳过**；`python -m app.main status` 仍返回 `mission_scheduler=unwired`、`vehicle_connection=unwired`、`send_commands=false`，表示默认入口不连接车辆。历史模式/解锁验收见[记录](sitl_arm_mission.md)；本轮两车基础运动及故障真值证据见[仿真审计](simulation/completion-audit.md)。两者均不替代实机运动、物理停止或服务器部署验收。

更新本文时应同时更新基线提交、运行测试、模块证据和未完成项。若某模块只因新增文件而没有达到更高档位的验证要求，进度分档不应上调。

## P9 Application Runtime（2026-10-03）

**PASS**：两车正式 App 进程、受限模式任务、IPC、取消、SIGTERM、重连只读及完整车辆回归。证据见 [P9](autonomy/phase-9.md)。P10–P17 按基础自主计划逐阶段验收，真实硬件仍暂缓。

# Vehicle Autonomy Framework V1：模块进度与未完成项

> 复核日期：2026-10-01。复核基线提交：`bc7cbbf11565203de61deb8a6f8bfd0a9d163e76`。本文审计新框架根目录；`legacy/cuadc_2026/` 中的历史实现不计入新框架进度。目标职责见 [V1 目标架构](framework_v1.md)，已经验证的阶段范围见 [迁移计划](migration_plan.md)。

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

## 1. 基础语义与状态链

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| P1 基础合同 | **100%** | 时间、Frame、Observation、VehicleState、WorldSnapshot、Typed Effect 和端口已有实现及测试；见 [时间合同](../contracts/core/time.py)、[世界合同](../contracts/world/models.py)、[合同测试](../tests/test_foundation_contracts.py)。 | 此 100% 仅指冻结的**基础合同范围**；未来可选模块的合同随具体组合增加。 |
| Transform 求解 | **50%** | [TransformTree](../core/transform.py)支持静态/动态关系与按时间求解，已有[离线测试](../tests/test_transform.py)。 | 未接入正式状态/任务组合；World Model 仍保留输入的原始 Frame。 |
| VehicleState 遥测适配 | **75%** | [ArduPilot 状态适配](../vehicles/multirotor/mavlink_state.py)已实现消息到标准状态的映射，经过测试及 USB 遥测检查。 | 生产采集时间的可信来源和跨时钟域处理未验收；USB 检查使用接收时间代理，不能据此宣称可供真实运动 Safety 使用。 |
| Sensor Adapter | **25%** | [假传感器](../sensors/fake.py)可构造标准观测并用于离线状态链。 | 无真实 Camera/LiDAR 等采集、源时间戳、健康和设备接入。按首个组合的实际传感器需求实现。 |
| Perception | **0%** | 仅有包占位；标准 Observation 合同在基础层。 | 无检测、跟踪、障碍物或其他模型的实现及接入。仅在选用感知能力时成为必需项。 |
| Localization | **25%** | [自报位姿投影](../localization/reported.py)可从 VehicleState 生成独立定位结果。 | 无真实定位或融合算法及其质量验证；当前投影不等于 GPS/VIO/SLAM。 |
| Mapping | **0%** | 仅有包占位。 | 无地图生产、版本管理和向 World Model 发布；按场景需要建设。 |
| Environment | **0%** | 仅有包占位。 | 无场景坐标基准、命名位置、静态地图或环境围栏适配；按首个任务需要建设。 |
| World Model | **75%** | [WorldModel](../world_model/service.py)可发布版本化只读快照，现已在 P6 SITL 进程中持续接收飞控状态并发布。 | 尚不接地图/Environment，不做跨 Frame 变换；真实设备采集时间未验收。 |
| 状态链组合 | **75%** | [SitlRuntime](../deployment/sitl_runtime.py)持续接收 SITL 飞控状态并经 World Model 向 Mission 发布快照；离线及本机 SITL 验收通过。 | 无真实传感器、生产设备时间映射或其他车辆组合。 |

## 2. 决策链

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Action | **75%** | P6 [模式 Action](../core/sitl_mode_action.py)只发一次 ModeEffect，并读结果确认 ACK 后的新未解锁目标模式；离线及 SITL 验收通过。 | 仍无实际业务 Action 或运动任务验收。 |
| Mission | **75%** | [MissionRuntime](../core/mission_runtime.py)支持 Effect 结果回流；P6 在持续运行进程中完成最小 Typed Mission，拒绝、未知与取消不会变为成功。 | 条件/分支仍按实际任务需求加入；P6 仅为单步 SITL 模式任务。 |
| Intent / MissionProposal | **0%** | [目标架构](framework_v1.md#3-四类核心数据及其边界)定义了上层目标进入系统的边界，当前无对应的 V1 类型与校验用例。 | 仅在接入操作者提案或 Intelligence 时实现标准提案、校验和转 Mission/Action 的流程。 |
| Planning | **0%** | 仅有包占位。 | 无路径/轨迹/避障算法；仅在所选 Action 需要规划时实施。 |
| Guidance | **0%** | 仅有包占位。 | 无从计划/状态到运动目标的算法；仅在所选 Action 需要导引时实施。 |
| Intelligence | **0%** | 仅有包占位。 | 无 Intent/MissionProposal 的实际生成、校验或模型接入；不是首个无 AI 组合的必需条件。 |

## 3. 控制、车辆与设备链

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Execution | **75%** | [VehicleExecution](../core/vehicle_execution.py)已在 P6 周期中接收 Mission Effect 并经双 SEND/Safety/唯一 writer 分派；幂等、deadman 和 stop 有 P4/P5 测试。 | 物理停止与运动任务未验收；P6 模式任务没有活动运动流。 |
| 非车辆 Effect | **0%** | 当前 V1 [Effect 类型](../contracts/effects/vehicle.py)与新 Execution 仅覆盖车辆命令。 | 若首个组合需要拍照、保存文件或其他副作用，须定义各自合同和受控端口，并由 Execution 分派。 |
| Authorization | **75%** | [ControlAuthority](../core/control_authority.py)默认关闭双 SEND，管理 Lease、代际、撤销和会话；写前在唯一 writer 处复核。 | 尚无生产控制源仲裁、操作配置及整车场景验收。 |
| Safety | **75%** | [VehicleSafetyPolicy](../core/vehicle_safety.py)要求显式限值，检查 TTL、时钟/状态新鲜度、Mode/Frame、高度、矩形围栏与速度；受限设备命令经过此边界。 | 车辆专用限制、下降率/分轴规则、实际失联动作及物理 stop 仍需按首个车辆审核和验收；软件检查通过不等于飞行安全验收。 |
| ArduCopter Vehicle Plugin | **75%** | [命令翻译](../vehicles/multirotor/ardupilot_commands.py)、[唯一 writer](../vehicles/multirotor/mavlink_port.py)、[会话](../vehicles/multirotor/session.py)和只读状态适配已实现；本机 SITL 模式/解锁/上锁链及 USB 台架受限诊断有记录。 | 未完成实际机架的解锁、运动、执行器输出、物理停止及失联效果验收；台架记录显示测试后已把 `FRAME_CLASS` 恢复为原值 0。 |
| Rover Vehicle Plugin | **25%** | 有仅允许 HOLD 请求的[受限诊断](../vehicles/rover/diagnostic.py)，USB 未解锁 ACK/状态已验证。 | 无 Rover 运动能力、完整状态/命令插件或整车验收。 |
| 其他 Vehicle Plugin | **0%** | 固定翼、VTOL 等无实现。 | 仅在选择相应机型时开发；不应计作当前 ArduCopter 组合的阻塞项。 |
| MAVLink Protocol | **75%** | [MAVLink 2 codec](../protocols/mavlink/codec.py)与[遥测解码](../protocols/mavlink/telemetry.py)覆盖当前 ArduPilot 子集；SITL/USB 受限链已验证。 | 不是 MAVLink 全量实现；首个整车组合所需的运动与异常协议路径仍待验收。 |
| Transport | **75%** | [TCP 与串口字节传输](../infrastructure/transports/bytes.py)可显式连接，分别用于本机 SITL 和 USB 诊断。 | 无 UDP、生产重连/链路运维组合；这些应随选定部署和连接方式实现。 |

## 4. 应用、部署与外部接口

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Application 用例 | **75%** | [MissionService](../application/mission_service.py)提供启动、取消、查询与关闭用例；P6 离线闭环已验证。 | 无外部 API、操作者控制源仲裁或其他业务 Mission。 |
| 具体 Applications / Missions | **25%** | 本机 SITL 有独立的模式任务及[解锁/上锁验收任务](sitl_arm_mission.md)，均为受限诊断 Mission。 | 无首个实际业务 Mission；旧比赛任务仍在 `legacy/`。 |
| App 进程入口 | **75%** | [CLI](../app/main.py)显式 `run-sitl` 和 `run-sitl-arm` 可启动 localhost SITL 单进程；解锁入口需要双重显式开关。 | 无 onboard/server 入口或生产车辆连接。 |
| Deployment | **75%** | [SitlRuntime](../deployment/sitl_runtime.py)负责周期、状态发布、Mission 推进、结果汇集及故障撤权；本机 SITL 验收通过。 | 不支持真实设备时间同步、物理停止或生产重连。 |
| Gateway | **0%** | 仅有包占位。 | 无远程接入、链路监视和本地失联处置；只有远程部署需要。 |
| Web UI | **0%** | 仅有包占位。 | 无界面或 Web API；不是首个无 Web 组合的必需条件。 |
| 独立运行配置 | **100%（P6 SITL 范围）** | [严格 TOML profile](../runtime/sitl.toml)指定 loopback、机型、周期、时钟和显式 Safety；配置不含 SEND 开关。 | 仅覆盖本机 SITL；无可发送的 onboard profile。 |
| 自动化测试与验收 | **75%** | 81 项根目录测试覆盖合同、离线状态/决策/控制、MAVLink、P6 故障注入和 SITL 解锁任务清理；本机 SITL 两种端到端任务通过。 | 缺运动/失联 stop 的完整仿真及整车设备验收。 |

## 5. P6 完成后的工作范围

[P6 实施与验收](p6_runtime_integration_plan.md)已证明 localhost ArduCopter SITL 中状态、Mission、Effect、Execution、ACK 和新状态构成持续运行闭环。独立的[解锁/上锁 SITL 任务](sitl_arm_mission.md)进一步验证了受限的三步任务；这仍只是仿真能力。当前决定**暂缓真实飞控接入**：P5 的整车设备验收保持未完成，不建设可发送的 onboard profile，也不把 SITL 的接收时间代理视为真实采集时间。

当前可继续的软件工作按实际业务需要推进：

1. **确定首个非比赛业务 Mission：** 明确输入、输出、所需车辆能力和完成判据；现有 `SitlRuntime` 的模式/解锁步骤仍是固定诊断任务，不是通用任务目录。
2. **将运行组合扩展为可装配任务：** 在 Application 合同下接收经过预检的 Typed Mission 和 Action 注册，不让业务模块持有车辆端口；保持双 SEND 默认关闭、唯一 writer、结果回流和单进程生命周期语义。
3. **按任务需要增加模块与 SITL 验收：** 只实现所选任务确实依赖的 Sensor、Environment、Planning、Guidance 或非车辆 Effect。若任务包含运动流，先在假端口和 SITL 中验收取消、deadman、stop/zero 与断链后的未确认结果；模式/解锁任务的通过不能替代这些测试。

真实飞控重新纳入范围时，再单独制定设备时间同步、机架/传感器校准、日志、物理运动、停止和失联保护的验收计划。当前不据此提高表中 Vehicle、Safety 或 Transport 的成熟度。

## 验证边界

本次复核执行 `python -m unittest discover -s tests -q`：**81 项通过**；`python -m app.main status` 仍返回 `mission_scheduler=unwired`、`vehicle_connection=unwired`、`send_commands=false`，表示默认入口不连接车辆。本机 SITL 模式及解锁/上锁端到端验收见[记录](sitl_arm_mission.md)；这些结果不能替代整车实机运动、物理停止或服务器部署验收。

更新本文时应同时更新基线提交、运行测试、模块证据和未完成项。若某模块只因新增文件而没有达到更高档位的验证要求，进度分档不应上调。

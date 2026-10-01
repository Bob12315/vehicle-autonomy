# Vehicle Autonomy Framework V1：模块进度与未完成项

> 审计日期：2026-10-01。基线提交：`f0021a93668603f4a27b6931ca0c1e188d5d994f`。本文审计新框架根目录；`legacy/cuadc_2026/` 中的历史实现不计入新框架进度。目标职责见 [V1 目标架构](framework_v1.md)，已经验证的阶段范围见 [迁移计划](migration_plan.md)。

## 进度口径

下面的百分比是**按证据分档的模块成熟度估计**，不是代码量、工时或整个系统的加权完成率。同一模块只取当前达到的最高档；目录占位不算实现。

| 档位 | 判定依据 |
| --- | --- |
| 0% | 尚无该模块的具体能力实现。 |
| 25% | 有合同、假实现、示例或局部工具，但不能完成目标职责。 |
| 50% | 有可独立运行且经过离线测试的目标能力，尚未进入完整运行组合。 |
| 75% | 已进入仿真或受限设备链验证，仍缺所声称使用环境的完整验收。 |
| 100% | 已完成该行写明的明确范围及相应验收；不代表所有未来插件和场景都实现。 |

**阶段进度：** P0 是限定范围的基线审计；P1 基础合同、P2 离线状态链、P3 离线决策链、P4 离线控制边界均已完成各自阶段门槛。P5 已完成 ArduCopter 软件组合、本机 SITL 和受限 USB/裸飞控台架验证，**整车实机验收未完成**。[阶段表](migration_plan.md#阶段与验收)中的完成状态不应被换算成“整个系统完成五分之六”。

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
| World Model | **50%** | [WorldModel](../world_model/service.py)可合并车辆、定位和 DetectedObject，发布只读不可变快照，处理版本、新鲜度、缺失、未来时间和跨时钟域输入；已有[离线测试](../tests/test_p2_state_chain.py)。 | 尚不接地图/Environment，不做跨 Frame 变换；未在正式进程中持续运行。 |
| 状态链组合 | **50%** | [OfflineStateChain](../application/state_chain.py)把假输入/车辆状态、定位与 World Model 接成离线发布链。 | 尚无真实传感器和设备状态持续采集、调度及与 Mission/Execution 共用的运行组合。 |

## 2. 决策链

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Action | **50%** | [注册器](../core/action_registry.py)、[类型与参数规范](../contracts/decision.py)、Effect 白名单及[示例 Action](../core/actions.py)已通过离线测试。 | 无首个车辆/业务组合所需的具体 Action；输入/输出及 Safety 元数据和任务到设备的集成验收仍需按具体能力补齐。 |
| Mission | **50%** | [编译预检](../core/mission.py)与[MissionRuntime](../core/mission_runtime.py)支持线性步骤、重试、失败策略、取消、退出屏障及 Typed Effect 请求；见[测试](../tests/test_p3_decision.py)。 | 无正式调度入口、Effect 回执与运行状态闭环；目标文档中的条件/分支尚未实现，可在确有任务需求时加入。 |
| Intent / MissionProposal | **0%** | [目标架构](framework_v1.md#3-四类核心数据及其边界)定义了上层目标进入系统的边界，当前无对应的 V1 类型与校验用例。 | 仅在接入操作者提案或 Intelligence 时实现标准提案、校验和转 Mission/Action 的流程。 |
| Planning | **0%** | 仅有包占位。 | 无路径/轨迹/避障算法；仅在所选 Action 需要规划时实施。 |
| Guidance | **0%** | 仅有包占位。 | 无从计划/状态到运动目标的算法；仅在所选 Action 需要导引时实施。 |
| Intelligence | **0%** | 仅有包占位。 | 无 Intent/MissionProposal 的实际生成、校验或模型接入；不是首个无 AI 组合的必需条件。 |

## 3. 控制、车辆与设备链

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Execution | **75%** | [VehicleExecution](../core/vehicle_execution.py)接收 Typed Effect，提交标准命令，处理幂等、取消、deadman 和 stop 状态；经离线、SITL 和受限 USB 命令链测试。 | Mission 产出的 Effect 尚未由正式系统持续分派；`tick()` 依赖调用方周期调度，物理停止未验收。 |
| 非车辆 Effect | **0%** | 当前 V1 [Effect 类型](../contracts/effects/vehicle.py)与新 Execution 仅覆盖车辆命令。 | 若首个组合需要拍照、保存文件或其他副作用，须定义各自合同和受控端口，并由 Execution 分派。 |
| Authorization | **75%** | [ControlAuthority](../core/control_authority.py)默认关闭双 SEND，管理 Lease、代际、撤销和会话；写前在唯一 writer 处复核。 | 尚无生产控制源仲裁、操作配置及整车场景验收。 |
| Safety | **75%** | [VehicleSafetyPolicy](../core/vehicle_safety.py)要求显式限值，检查 TTL、时钟/状态新鲜度、Mode/Frame、高度、矩形围栏与速度；受限设备命令经过此边界。 | 车辆专用限制、下降率/分轴规则、实际失联动作及物理 stop 仍需按首个车辆审核和验收；软件检查通过不等于飞行安全验收。 |
| ArduCopter Vehicle Plugin | **75%** | [命令翻译](../vehicles/multirotor/ardupilot_commands.py)、[唯一 writer](../vehicles/multirotor/mavlink_port.py)、[会话](../vehicles/multirotor/session.py)和只读状态适配已实现；SITL 及 USB 台架记录见[迁移计划](migration_plan.md#阶段-5按需接入设备)。 | 未完成实际机架的解锁、运动、执行器输出、物理停止及失联效果验收；台架记录显示测试后已把 `FRAME_CLASS` 恢复为原值 0。 |
| Rover Vehicle Plugin | **25%** | 有仅允许 HOLD 请求的[受限诊断](../vehicles/rover/diagnostic.py)，USB 未解锁 ACK/状态已验证。 | 无 Rover 运动能力、完整状态/命令插件或整车验收。 |
| 其他 Vehicle Plugin | **0%** | 固定翼、VTOL 等无实现。 | 仅在选择相应机型时开发；不应计作当前 ArduCopter 组合的阻塞项。 |
| MAVLink Protocol | **75%** | [MAVLink 2 codec](../protocols/mavlink/codec.py)与[遥测解码](../protocols/mavlink/telemetry.py)覆盖当前 ArduPilot 子集；SITL/USB 受限链已验证。 | 不是 MAVLink 全量实现；首个整车组合所需的运动与异常协议路径仍待验收。 |
| Transport | **75%** | [TCP 与串口字节传输](../infrastructure/transports/bytes.py)可显式连接，分别用于本机 SITL 和 USB 诊断。 | 无 UDP、生产重连/链路运维组合；这些应随选定部署和连接方式实现。 |

## 4. 应用、部署与外部接口

| 部分 | 进度 | 已完成的证据 | 尚未完成 |
| --- | ---: | --- | --- |
| Application 用例 | **25%** | [FrameworkService](../application/service.py)提供有限的旧 Mission 定义校验；状态链有离线组合。 | 无 V1 Typed Mission 的启动、取消、查询、结果和授权用例接口。 |
| 具体 Applications / Missions | **0%** | 业务包仅占位；旧比赛任务仍在 `legacy/`。 | 尚未选择首个非比赛任务、配置、Action 和 Mission；需先定具体组合。 |
| App 进程入口 | **25%** | [CLI](../app/main.py)仅可查询状态，明确报告车辆连接与 Mission 调度未装配。 | 无连续运行的状态→决策→控制进程、启动/关闭生命周期及故障恢复。 |
| Deployment | **25%** | [CopterCycleDriver](../deployment/copter_cycle.py)可在调用方触发时组合接收、deadman 和写队列。 | 无实际周期调度、配置注入、onboard 进程和运行验收；server/hybrid 仅在选用时实现。 |
| Gateway | **0%** | 仅有包占位。 | 无远程接入、链路监视和本地失联处置；只有远程部署需要。 |
| Web UI | **0%** | 仅有包占位。 | 无界面或 Web API；不是首个无 Web 组合的必需条件。 |
| 独立运行配置 | **0%** | `runtime/` 仅有占位文件，没有可启动的组合配置。 | 首个组合需明确设备、时钟、Safety 限值、周期、权限和运行参数，且不得默认启用 SEND。 |
| 自动化测试与验收 | **75%** | 根目录已有合同、离线状态/决策/控制、MAVLink 的单元测试；另有本机 SITL 与受限 USB/台架手动记录。 | 缺正式运行组合的端到端测试、失联/stop 的完整仿真验收及整车设备验收。 |

## 5. 还差什么才能称为“完整系统”

先确定一个**首个支持组合**（车辆、传感器、任务和部署形态），再依据该组合验收；不需要先实现上表所有按需模块。目前最直接的路线是现有 ArduCopter/MAVLink 能力，但是否采用它由实际项目需求决定。

1. **接通正式运行闭环：** 在 `app`/`application`/`deployment` 中组合可信状态采集、World Model、Typed Mission、Effect 分派、Execution 与命令回执；实现周期调度、关闭、取消、失败和停止流程，并保持双 SEND 默认关闭。
2. **补齐首个组合的真实输入和能力：** 确定采集时间来源、时钟域/Frame、车辆状态质量；只实现任务所需的 Sensor、Action、Environment、Planning 等，不把空包当作支持。
3. **完成仿真端到端验收：** 用所选 Mission 验证状态→决策→命令→ACK/状态观察，覆盖取消、过期、断链、连续命令 stop/zero 与重连旧命令隔离。
4. **按声称的设备能力完成实机验收：** 若要声明整车可用，需在实际装配、校准及安全配置后验证运动、执行器、物理停止、失联处置和日志。当前 USB/裸板记录只证明受限模式请求、预解锁拒绝与 Disarm 回执。

## 验证边界

审计时根目录执行 `python -m unittest discover -s tests -q`：**64 项通过**；`python -m app.main status` 返回 `mission_scheduler=unwired`、`vehicle_connection=unwired`、`send_commands=false`。SITL 与 USB/台架结果采用[迁移计划](migration_plan.md#阶段-5按需接入设备)中已有的手动测试记录，本次没有重新连接设备。这些结果不能替代整车实机运动、物理停止或服务器部署验收。

更新本文时应同时更新基线提交、运行测试、模块证据和未完成项。若某模块只因新增文件而没有达到更高档位的验证要求，进度分档不应上调。

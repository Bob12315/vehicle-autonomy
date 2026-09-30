# 可复用框架迁移计划与记录

> **状态：P0 至 P4 已完成；P5 的 ArduCopter 软件组合已通过离线与本机 SITL 验证，USB Rover 飞控完成受限 HOLD 诊断；整车实机待验收。** 本文记录从 `legacy/cuadc_2026/` 提取可复用能力的顺序、验收门槛与阶段进度。目标职责以 [V1 目标架构](framework_v1.md) 为准；[当前实现边界](architecture.md)描述根目录已有能力。本文中的源文件只是候选素材，不表示已决定复制或已在新框架运行。

## 目标与策略

只迁移能服务多个车辆、设备或业务场景的能力，或作为明确插件所必需的实现。优先建立稳定合同与状态链，再接 Mission/Action，最后完成控制安全边界和设备接入。

这里的“从底层开始”指**先明确数据语义、端口和依赖边界**，并在假设备与离线测试中逐层组装；不指先连飞控。Transport、协议编解码可以独立验证，但在授权、Safety 和唯一 writer 完整之前不得接入根目录的生产车辆发送链。

```text
合同与时空语义
       ↓
状态链：采集 → 观测 → WorldSnapshot
       ↓
决策链：注册 Action → Mission 运行 → Typed Effect
       ↓
控制边界：授权 → Safety → 取消/停止 → 唯一 writer
       ↓
车辆插件、协议、传输及具体部署
```

### 长期不变量

1. 新根目录不导入 `legacy/`；旧源码先作为参考和测试基线，逐项适配到新归属。通用 Core 不依赖 CUADC、特定车辆、MAVLink、RKNN 或 Web。
2. Mission、Action、Web、感知、规划和 Intelligence 不持有车辆命令端口。车辆命令仅由 Execution 在系统 SEND、Action SEND、有效授权和显式 SafetyPolicy 检查后提交；两个 SEND 门控默认关闭。
3. 真实连接前证明连续命令 stop/zero、过期和旧代际命令取消、断链处置及唯一生产 writer。不能以当前简化的 `ExecutionGateway` 替代旧系统完整 Safety 行为。
4. CUADC 的场地、救援 Mission、投放规则、比赛参数留在应用或环境实现中。一个文件“没有硬件依赖”并不自动说明其语义通用。
5. 每个已完成阶段运行相关测试并提交 Git。仅在修改归档树时，从 `legacy/cuadc_2026/` 运行对应旧测试；不因迁移而直接删除仍被旧生产链使用的代码。

## 阶段与验收

阶段按依赖推进。每阶段可拆成多个小提交，但提交前需留下对应验收记录。后续阶段的设计可以提前讨论；其生产接线仍受前置门槛约束。

| 阶段 | 交付物 | 完成门槛 | 进度 |
| --- | --- | --- | --- |
| 0. 基线与候选清单 | 根目录与旧系统现状、候选模块的依赖和安全审计 | 每个候选有归属、调用方、外部依赖、配置、测试和“迁/改写/保留”判断；记录实际运行的基线测试 | **已完成：限定范围 P0 文档审计**，见[基线](migration/p0_baseline.md)与[候选清单](migration/p0_inventory.md) |
| 1. 基础合同 | 时间、坐标、来源、有效性、Observation、VehicleState、WorldSnapshot、Typed Effect 及必要端口 | 类型语义明确；序列化与不变量测试通过；Core 无具体设备或业务依赖 | **已完成：合同层**，见下方 P1 记录；未接运行链 |
| 2. 状态链 | 假 Sensor/Vehicle 输入、标准化观测、可选的纯感知或定位算法、World Model 发布 | 不接真实命令端口；时间戳、坐标、过期/缺失状态可测试；高级消费者只读统一快照 | **已完成：离线假输入链**，见下方 P2 记录 |
| 3. Mission/Action | Schema、能力预检、编译、运行生命周期、取消、结果、Typed Effect，以及按需接入 Planning/Guidance | 未注册或不支持的 Action 被拒；失败、重试、取消和退出行为有测试；Action、Planning、Guidance 均不直接发送车辆命令 | **已完成：离线决策链**，见下方 P3 记录 |
| 4. 控制安全边界 | 授权生命周期、Execution 分派、Safety、命令回执与取消/停止语义 | 默认 SEND 关闭；双门控、TTL、撤销、代际、deadman、stop/zero、断链及唯一 writer 在假端口测试中成立 | **已完成：离线假端口边界**，见下方 P4 记录 |
| 5. 插件与设备组合 | 所需 Vehicle Plugin、Protocol/Transport、Sensor Adapter、Deployment 组合 | 先离线与仿真验证；真实设备能力只在设备验收后声明；生产写入仍只有一个受控出口 | **部分完成：ArduCopter/TCP 软件组合与本机 SITL；USB Rover 飞控 HOLD 诊断；整车实机待验收**，见下方 P5 记录 |

### 阶段 0：建立可核对的迁移清单

P0 已按 `contracts/`、`telemetry_link` 的 state/frame/time、依赖这些合同的 `application/core/` 文件和相关测试完成限定范围审计；邻接的 Execution/writer 仅用于确认安全边界。见[基线与测试记录](migration/p0_baseline.md)、[候选归属及依赖表](migration/p0_inventory.md)。此完成状态不覆盖旧应用的全部模块，也不表示任何代码已经迁移。

从旧系统的实际生产入口、调用方、配置和测试出发，不以目录名推断复用性。每个候选至少记录：

- 当前输入输出、时间和坐标约定，以及默认值来自通用规则还是具体场景；
- 对旧合同、全局状态、设备、第三方库与旧运行时的依赖；
- 是否会影响车辆发送、停止、授权、Safety 或 payload；
- 新框架归属、需要先建立的合同、已有测试和需要新增的行为测试。

旧文档中的 `769 passed` 是归档时记录，不是本计划的当前测试结果；本次 P0 实际运行的限定范围测试及结果已记录在基线文档中。P1 开始时应重新记录其相关测试。

### 阶段 1：先统一合同

以 [V1 基础合同冻结规范](foundation_contracts_v1.md) 为阶段 1 的语义依据，对照根目录现有 `Effect(operation: str, parameters)`、最小 `WorldSnapshot` 和 `VehicleCommandPort.submit(effect)`，逐项记录并消除差异；不直接复制旧 `contracts/`。先落实单位、坐标系、时钟域、来源、质量和失效含义，再让适配器使用合同。车辆能力描述与运行时许可分开；合同不能暗含 SEND 授权。规范中的基础语义如需修改，应记录无法由 Adapter 或迁移层解决的具体问题。

**P1 实际实现（2026-09-30）：** 新根目录新增经过校验的 ID、`SchemaVersion`、`ResourceVersion`、`FrozenJson`、`TimePoint`/三类时间事实、`FrameId` 与 SI 几何、`Stamped`、质量/新鲜度、Typed `Observation`、车辆自报 `VehicleStateSnapshot`、独立 `LocalizationEstimate` 和独立 `LinkStateSnapshot`。`WorldSnapshot` 现在不可变、版本化，含车辆/定位、资源引用、固定新鲜度与输入版本依赖。新增请求型 Typed Vehicle Effect 与 `EffectEnvelope`，以及分离的 `VehicleCommandEnvelope`、命令状态/取消值和 `submit/cancel/status` 窄端口；车辆状态查询、定位查询、世界查询、Transform Resolver 均为只读/纯接口。合同仅依赖 Python 标准库和同层合同。

**兼容与边界：** 旧根目录 `Effect(operation, parameters)` 和演示用 `ExecutionGateway` 仍服务原有 Mission/Action 测试；其端口注解明确为旧 Effect 提交接口，并未把 Typed Effect 或 VehicleCommand 接入现有发送路径。该演示网关尚不能满足完整 Authorization、取消、deadman 等控制要求，不能视为 V1 命令执行实现。Transform 仅有值类型与 `TransformResolver` 端口，没有静态/动态求解器、NED/ENU 或 FRD/FLU 适配器；具体 Observation Data、世界对象及状态生产者需在后续状态链阶段增加。原旧系统的 `source=real/sitl/test`、动态 `age_s`、FIELD、协议坐标和 `control_allowed` 均未进入新基础状态合同。冻结规范无变更；旧数据差异保留给后续 Adapter。

**P1 验证：** `/usr/bin/time -p python -m unittest discover -s tests -v`：14 passed、0 failed、0 skipped，测试运行 0.018 s，墙钟 0.10 s。覆盖身份/版本、FrozenJson 与 JSON 序列化、时钟域和无效时间、几何/Frame、Typed Observation、状态/定位/世界的不可变性与版本依赖、Effect/Command 分离、端口方法集合及原有双 SEND 测试。`python -m compileall -q contracts core tests`：通过。使用 `rg` 检查根目录 Python import：未发现 `legacy`、`pymavlink`、`telemetry_link` 或协议层导入；根目录依赖测试也通过。P0 的 4 项根目录测试本次全部通过；没有新引入失败，也没有需归因的既有 baseline failure。未修改归档树，故未运行旧树测试。

### 阶段 2：构建状态链

先用文件、假相机或假车辆状态发布器验证 Sensor/Vehicle → Observation → World Model。可复用的纯投影、定位、融合算法逐个审核并适配新输入；相机视场角、场地朝向、类别集合等旧默认值不得偷偷成为通用默认。WorldSnapshot 对过期和未知数据作显式表达。

**P2 实际实现（2026-09-30）：** `FakeDetectionSensor` 产生带 `producer_id`、序号、采集/接收时间、Frame 与质量的 `Observation[DetectedObject]`；`FakeVehicleStateSource` 发布版本化的车辆自报状态并提供只读 `snapshot()`。纯 `ReportedPoseLocalization` 将飞控自报位姿显式投影为独立 `LocalizationEstimate`。`OfflineStateChain` 通过只读车辆端口、定位估计器和 Typed Observation 装配离线流程；消费者只取得 `WorldReader.snapshot()`。`WorldModel` 以锁保护一次发布切面，输出不可变、递增版本的 `WorldSnapshot`，并记录车辆、定位、观测输入的版本依赖。检测目标保留原始 `frame_id`，不暗中将 camera、odom 与 map 坐标混算。

**失效语义：** 发布时根据相同 `clock_domain_id` 的 monotonic 时间计算固定新鲜度；车辆/定位的发布及 Stamped 采集时间、观测的采集及接收时间均参与检查。超过注入的纳秒 TTL 为 `STALE`；缺失、未来时间或不同 clock domain 为 `UNKNOWN`。不可用、无效质量及非新鲜输入不会成为快照中的当前车辆、定位或对象，但仍保留已有输入版本依赖；质量与新鲜度各自判断。状态源明确变为缺失时下一版快照立即清除车辆及该投影定位。`WorldModel` 拒绝回退的状态版本/发布时间、复用版本但改变内容、倒退的观测序号及同域倒置的时间事实。

**旧实现判断与剩余边界：** 审核了归档 `world_model/service.py`、`projection.py` 和 `application/core/snapshot_collector.py`。其单次发布切面值得保留，但它们直接依赖旧 platform/perception DTO、NED 标量、比赛 Environment/Field 及混入 SEND 的运行快照，因此 P2 按新合同重写，未复制旧模块。当前检测由假源直接构造，不声称相机或感知模型接入；没有地图、Environment、Transform 求解器、跨 Frame 变换、真实车辆/传感器适配器或设备连接。旧系统基于接收时间和固定 2 秒的感知新鲜度规则没有带入 Core；P2 使用显式、注入的 TTL 与采集时间。状态链没有车辆命令端口，P3/P4 的 Mission/Action 与控制行为均未开始。

**P2 验证：** `/usr/bin/time -p python -m unittest discover -s tests -v`：21 passed、0 failed、0 skipped；测试运行 0.026 s，墙钟 0.10 s。新增 7 项覆盖端到端离线组合、时间/Frame/来源与序列化、缺失/过期/未来/跨域、质量独立、版本回退、只读查询、无控制字段及无命令端口依赖；P1 原有 14 项全部通过。`python -m compileall -q application contracts localization sensors vehicles world_model tests` 通过。根目录 Python import 搜索未发现 `legacy`、`pymavlink`、`telemetry_link` 或 `protocols` 导入；依赖测试通过。无失败需归因于既有 baseline 或新问题。未修改归档树，故未运行旧树测试。

### 阶段 3：构建决策链

在现有 Action 注册和 Mission 校验之上，逐步加入 Schema、编译、调度、结果、失败、取消及退出屏障。先迁不要求真实车辆的 Action 以验证生命周期；需要路径或运动目标的 Action 再通过合同接入 Planning/Guidance。车辆或业务 Action 留在各自插件/应用。旧候选 Core 和旧生产 Runtime 的职责需要核对后选取，避免同时维护两套 Mission owner。

**P3 实际实现：** 在现有 `ActionRegistry` 和 `MissionValidator` 上增加 typed 注册与编译，不引入第二套 Mission owner。冻结 dataclass 参数用显式类型检查和深度不可变校验；编译前拒绝未注册 Action、重复步骤、参数不匹配及缺少车辆能力。`MissionRuntime` 从 `WorldQueryPort` 每 tick 读取一版新鲜快照，管理 Action 尝试、结果、失败策略、重试、取消和退出屏障。Action 仅返回 `EffectEnvelope` 请求；未声明的 Effect 不会输出。退出失败时运行保持 `EXITING`，不得推进下一步。通用 `world.summary` Action 不使用设备或车辆命令。

**Transform 补充：** `TransformTree` 是与设备无关的统一 Frame 求解器。它支持静态链、动态时间样本和有界插值、反向/多边组合，以及点、自由向量、Pose、Twist 转换。动态查询拒绝时钟域不匹配、缺失区间、超限间隔与外推；注册拒绝多路径/环路。Vector3 默认作为自由向量，位置使用显式 `transform_point()`。未加入 MAVLink 的 NED/FRD 语义，协议轴转换留在设备适配边界。

**验证与边界：** `/usr/bin/time -p python -m unittest discover -s tests -v`：32 passed、0 failed、0 skipped，测试 0.044 s，墙钟 0.12 s。新增 8 项 P3 与 3 项 Transform 测试，覆盖编译拒绝、运行结果、重试、取消与 stop 请求、退出异常、效果白名单、静态/动态 Frame 和失败路径；原 21 项通过。`python -m compileall -q contracts core application world_model tests` 通过。P3 不分派 Effect、不持有 `VehicleCommandPort`，也不实现 P4 授权、Safety、队列、回执和连续命令物理停止；离线退出屏障完成不等于车辆已停止。真实设备适配与物理验证仍按设备阶段单独记录。

**附加只读设备状态适配（ArduPilot 假设）：** 用户要求继续处理真实设备适配，但未给出设备型号；根据旧仓库的 ArduPilot/MAVLink 遥测链，先实现 `protocols/mavlink/telemetry.py` 对真实 parsed message 形状的接收侧解码，及 `vehicles/multirotor/mavlink_state.py` 到 P1 `VehicleStateSnapshot` 的规范化。NED 位置/速度转换为 ENU，FRD/NED 姿态与角速度转换为 FLU/ENU；保留独立采集、接收、发布时间，并只在位置/姿态采样差处于显式上限内组合 Pose/Twist。GPS fix、协议缺失值、心跳时效、来源 system/component 与 LinkState 分开处理。调用方必须提供可信的 `captured_at` 与 `received_at`；飞控 boot time 未被冒充为本机单调时间。适配器可作为 P2 `VehicleStatePort` 输入，但没有打开物理连接、`pymavlink` writer 或命令提交方法。旧 `MavlinkClient` 含 `send_raw_message`，故未迁入。此项是**已验证的消息到状态适配**，不是实机连接或设备验收；具体设备若非 ArduPilot，需按实际协议调整。P4 安全边界及 P5 设备组合门槛仍未完成。`/usr/bin/time -p python -m unittest discover -s tests -v`：37 passed、0 failed、0 skipped，测试 0.143 s、墙钟 0.24 s，其中 5 项新适配测试覆盖实际 `pymavlink` 消息对象、坐标与缺失值；编译检查通过，生产包未导入 `legacy`、`telemetry_link` 或 `pymavlink`。

### 阶段 4：证明控制边界

先在假 `VehicleCommandPort` 上实现并测试授权、Safety、排队、回执、取消和停止。对照旧配置与行为审核数值限制和 payload 白名单，不能只比较接口名称。分别记录 accepted、transmitted、ACK 和 state-observed completion；断链时不得把 stop 请求写成 stop 已送达。此阶段完成前保持根目录无生产车辆连接。

**P4 实际实现（2026-09-30）：** `ControlAuthority` 管理单一有效 Run/Action Lease、失效时刻、双 SEND（默认 false）、授权与 SEND 代际及当前链路会话。授予新 Lease 默认关闭 Action SEND；撤销、切换门控或会话使排队旧命令在出队时失效。`VehicleExecution` 是根目录 V1 `VehicleCommandPort.submit/cancel/status` 的唯一 Core 调用方，接收 Typed `EffectEnvelope`，按作用域、时间、显式 `VehicleSafetyPolicy` 和链路会话分派到独立 `VehicleCommandEnvelope`。同一 Effect ID 不能复用不同内容，连续目标刷新会取消旧排队目标。无策略时无法构造执行组件。

**Safety 与停止：** `SafetyLimits` 必须显式注入，没有通用飞行数值默认值。策略拒绝无效/过期/超长 TTL、跨时钟域、旧 World/Vehicle 状态、无效质量、未允许的 Mode/Frame、越界高度/地理围栏和超速 Twist。Stop 可绕过旧状态阻止条件，但仍需有效授权、双 SEND 和链路。由调用方定期 `tick` 驱动 deadman；超时先取消旧目标，再提交 `StopMotionCommand`。假端口将其记为模拟的零运动写入。断链或授权关闭时只记未确认停止，不声称已发送；ACK 与状态观测完成分别推进，只有后者标记 `CONFIRMED`。立即关闭 SEND 可能导致 stop 无法送达，因此真实系统必须在设备接入前设计受控停止/撤销顺序与失联保护；此离线实现不宣称物理停车。

**旧配置判断与边界：** 审阅归档 `execution/safety_config.py` 的请求 TTL、分轴速度、上下高度、Frame/Mode allowlist、deadman 及 payload servo 白名单。旧值和 NED/FRD frame 常量属于特定多旋翼/比赛配置，未复制到通用 Core；P4 以显式 SI、FrameId、局部矩形围栏配置表达适用的通用规则。V1 尚无 payload Effect，因此不添加伪通用 servo/投放命令；具体 payload、分轴速度、下降率、动态围栏、设备能力和失联动作应由后续具体 Vehicle/Safety 配置审核。`FakeVehicleCommandPort` 只模拟唯一写入检查点，真实 Vehicle/Protocol/Transport writer、物理零速/停止、链路状态生产和设备验收仍属于 P5。旧演示 `ExecutionGateway` 保持兼容且未接 V1 命令链；根目录 CLI 没有装配车辆发送路径。

**P4 验证：** `/usr/bin/time -p python -m unittest discover -s tests -v`：49 passed、0 failed、0 skipped，测试运行 0.160 s，墙钟 0.26 s；其中 P4 新增 12 项，覆盖默认关闭、Lease/作用域、Safety、TTL/时钟、代际/会话出队检查、断线重连同会话 ID 仍禁止旧队列、回执阶段、取消、deadman、模拟 stop/zero、断链未确认和 V1 端口归属。开发中出现 1 项拒绝原因优先级失败及 1 项旧网关文案导致的静态测试误报，均已修正；P0-P3 的 37 项既有测试全部通过，没有 baseline failure。`python -m compileall -q contracts core application tests` 通过。`rg -n '^(from|import) (legacy|pymavlink|telemetry_link|protocols|vehicles|infrastructure)' contracts core application` 无匹配，退出码 1；根目录依赖测试通过。未修改归档树，故未运行旧树测试。

### 阶段 5：按需接入设备

只为实际需要的组合添加 Vehicle Plugin、协议编解码、Transport 和 Sensor Adapter。协议语义与字节传输分离；车辆状态映射及命令翻译属于插件/适配器。先做离线和仿真测试，再按设备环境验收真实连接。RKNN、Web、server/hybrid 和具体应用分别作为可选后续工作，不因目标架构列出目录就视为必须迁移。

**P5 实际实现（2026-09-30）：** 延续 P3 的 ArduPilot/Copter 假设，只实现此组合。`ArduPilotCommandTranslator` 将批准的 Arm、Disarm、Takeoff、Land、Mode、`odom` ENU Pose/Velocity、`base_link` FLU Velocity 与 StopMotion 映射为明确的 Copter/MAVLink 指令；不支持的 Mode、Frame、roll/pitch 目标和非 yaw 角速度均拒绝。`MavlinkCodec` 独立负责 MAVLink 2 字节编解码，`TcpByteTransport` 独立负责显式 TCP 连接与读写。`ArduPilotCommandPort` 是唯一字节 writer，在同一 `ControlAuthority` 锁内完成最终 Lease/SEND/代际/会话/期限检查与写入。`ArduPilotSession` 从目标 system/component 心跳建立新 LinkSession、处理 ACK/状态、超时断链并清空旧会话；它不会自行开启 TCP 连接或 SEND。`CopterCycleDriver` 在调用方的周期调度下依次接收、执行 P4 deadman 和写一个排队命令；调用方必须保证周期短于配置的 deadman。状态继续由既有 `ArduPilotTelemetryState` 适配，可信采集时间必须由调用方提供；缺省无采集时间时不发布车辆状态。

**回执与停止：** 队列接受、实际调用字节写入、`COMMAND_ACK` 与后续状态观测是独立阶段。TCP 写入结果不确定或 ACK 超时时为 `UNKNOWN`，阻止同类命令在该会话重发造成歧义；负面 ACK 为 `REJECTED`。StopMotion 变为活动流坐标系中的零速度/零 yaw rate；只有写入后的新鲜零运动采样才能成为 `COMPLETED`，断链或无采样保持未确认。该软件语义遵循 [MAVLink 命令 ACK 规范](https://mavlink.io/en/services/command.html)及 [ArduCopter Guided 指令说明](https://ardupilot.org/dev/docs/copter-commands-in-guided-mode.html)。飞控侧 stop/zero 的物理效果仍未实机证明。

**验证与能力边界：** 内存传输测试覆盖默认关闭、唯一 writer 与字节内容、ENU/NED 和 FLU/FRD 映射、拒绝路径、ACK 来源过滤、状态完成、deadman 零速、撤销、断链、未知写入及 ACK 超时。另在本机 ArduCopter SITL 的 `127.0.0.1:5760` 执行 `PYTHONPATH=. python tests/manual_p5_sitl.py --allow-send`：未解锁飞控收到唯一 `GUIDED` 模式请求并返回 `ACKNOWLEDGED`，脚本随后关闭连接和 SEND；没有起飞、移动或实机连接。模式 `GUIDED=4` 由显式插件映射提供，和 [ArduCopter 模式定义](https://ardupilot.org/dev/docs/apmcopter-adding-a-new-flight-mode.html)一致。根目录 CLI 没有组合发送链；真实串口/UDP、设备时间同步、物理 stop、失联行为、真实飞控/机型验收、其他 Vehicle/Sensor 插件及 Deployment 仍未实现，也不宣称实机飞行能力。旧系统的双后端、调试发送捷径和比赛 payload 未迁入。

**P5 测试记录：** `/usr/bin/time -p python -m unittest discover -s tests -v`：59 passed、0 failed、0 skipped，测试运行 0.205 s、墙钟 0.33 s；新增 10 项 P5 测试，P4 以前 49 项均通过。`python -m compileall -q app application contracts core deployment infrastructure protocols vehicles tests` 和 `git diff --check` 通过。`rg -n '^(from|import) (legacy|telemetry_link|pymavlink|protocols|vehicles|infrastructure)' contracts core application app` 无匹配，退出码 1；`pymavlink` 导入限于 `protocols/mavlink/`。`/usr/bin/time -p env PYTHONPATH=. python tests/manual_p5_sitl.py --allow-send`：1 次 `PASS`、0 failed、0 skipped，墙钟 1.02 s，结果为 `ACKNOWLEDGED, armed=False`；SITL 随后关闭。开发中因旧 P1 根目录测试禁止任何 `pymavlink` 导入而有 1 项新引入失败，已将规则收窄为只允许协议包导入；P5 测试初次运行还因测试夹具使用普通字符串 FrameId 导致 6 项错误，修正后通过。没有既有 baseline failure。未修改归档树，故未运行旧树测试。

**P5 USB 飞控补充验收（2026-10-01）：** 实际连接设备为 ArduPilot MicoAir743v2，USB 串口 `/dev/ttyACM0`（有稳定 `/dev/serial/by-id/...` 路径）。只读心跳识别为 `MAV_TYPE_GROUND_ROVER=10`，而原 P5 插件针对 Copter；飞控原本已未解锁且处于 Rover `HOLD=4`。按 [MAVLink 心跳枚举](https://mavlink.io/en/messages/common.html)和 [ArduPilot Rover 模式定义](https://github.com/ArduPilot/ardupilot/blob/master/Rover/mode.h)区分机型和模式，不将 Copter `GUIDED=4` 语义套到此设备。新增显式 `SerialByteTransport`、会话 ArduPilot/机型心跳检查和仅允许 Rover HOLD 请求的诊断翻译器。诊断脚本在确认未解锁且已处于 HOLD 后，显式配置 Safety、Lease 与双 SEND，经 `VehicleExecution`、唯一 `ArduPilotCommandPort` 向 USB 飞控发送一次 HOLD 请求；收到 ACK，并从后续心跳确认 `COMPLETED, armed=False`。脚本结束关闭 SEND 和串口。没有刷写固件、修改参数、解锁或请求运动；没有电机/执行器可供物理验收。USB 状态的采集时间使用接收时间作为**仅限诊断的代理**，飞控源端采集时间仍未知。

**USB 测试记录与剩余边界：** `/usr/bin/time -p python -m unittest discover -s tests -v`：61 passed、0 failed、0 skipped，测试运行 0.256 s、墙钟 0.41 s；相对已提交 P5 的 59 项新增 2 项测试，覆盖 Copter 会话拒绝 Rover 心跳及串口伪终端/诊断翻译器。`python -m compileall -q app application contracts core deployment infrastructure protocols vehicles tests` 和 `git diff --check` 通过。`rg -n '^(from|import) (legacy|telemetry_link|pymavlink|protocols|vehicles|infrastructure)' contracts core application app` 无匹配（退出码 1）。`/usr/bin/time -p env PYTHONPATH=. python tests/manual_p5_rover_usb.py --port /dev/ttyACM0 --allow-send`：1 次 `PASS`、0 failed、0 skipped，墙钟 1.33 s，结果为 `COMPLETED, armed=False`。没有既有 baseline failure 或未修复的新失败。未修改归档树，未运行旧树测试。Copter 实机、Rover 完整运动插件、设备时间同步、物理 stop/失联效果、整车部署和生产车辆连接均未验收；CLI 未接 USB 命令链。

## 候选代码的初步归属

下表是阶段 0 的**待审候选**，不是复制清单。最终决定要依据源代码依赖、行为和测试逐项确认。

| 旧代码候选 | 目标归属 | 主要审查点 |
| --- | --- | --- |
| `contracts/core/`、`contracts/platform/`、`contracts/sensors/` | `contracts/` | 与新类型的语义差异、时钟/坐标、是否引入旧平台 DTO |
| `sensors/camera/`、`perception/fusion/`、`guidance/` 的纯计算 | `sensors/`、`perception/`、`localization/` 或 `guidance/` | 设备依赖、相机标定、场地坐标及比赛默认值 |
| `world_model/` | `world_model/` | 快照来源、新鲜度、线程模型和旧合同依赖 |
| `missions/core/`、`application/core/` | `core/mission/`、`core/action/`、`core/runtime/` | 旧候选 Core 与旧生产运行时的双 owner、取消与退出语义 |
| `execution/`、`telemetry_link/command_broker.py` | `core/execution/`、`core/safety/` 及受控设备边界 | 双 SEND、Safety 配置、代际、stop/zero、回执和唯一 writer |
| `vehicles/multirotor/`、`protocols/mavlink/`、`infrastructure/transports/` | 对应插件、协议、传输包 | 车辆语义与协议/字节 I/O 分离，禁止提前生产接线 |
| `applications/cuadc_2026/`、`environments/cuadc_2026/` | 具体应用或环境示例，默认保留归档 | 比赛业务语义不得进入通用 Core |

## 单项迁移记录模板

每迁移一个独立能力，在本文件下追加记录或建立链接的阶段记录；状态只使用“待审 / 进行中 / 已验证 / 保留归档”。

```text
能力与状态：
旧位置与生产调用方：
新归属与依赖合同：
复用判断：迁移 / 改写 / 保留归档；理由：
行为约定：单位、坐标、时间、默认值、失败/取消：
安全影响：SEND、授权、Safety、停止、writer：
验证：命令、结果、测试范围：
提交：
剩余限制：
```

每个记录的“已验证”只表示所列测试和环境已验证；不能从离线测试推断实机、服务器或 RKNN 支持。

## 进度记录

| 日期 | 阶段 / 能力 | 状态 | 证据与提交 |
| --- | --- | --- | --- |
| 2026-09-30 | 迁移计划文档 | 已建立 | 本文；尚未开始代码迁移 |
| 2026-09-30 | P0 基线与候选清单（限定范围） | 已完成 | [基线与 173 项旧测试、4 项根目录测试](migration/p0_baseline.md)，[候选归属及 `application/core` 依赖表](migration/p0_inventory.md) |
| 2026-09-30 | P1 基础合同 | 已完成合同层 | 14 项根目录测试通过；实现、兼容范围和后续边界见上方 P1 记录；提交 SHA 见本阶段 Git 提交 |
| 2026-09-30 | P2 离线状态链 | 已验证 | 21 项根目录测试通过；实现、旧代码判断与未接入边界见上方 P2 记录；提交 SHA 见本阶段 Git 提交 |
| 2026-09-30 | P3 离线决策链与 Transform | 已验证 | 32 项根目录测试通过；实现与未接入边界见上方 P3 记录；提交 SHA 见本阶段 Git 提交 |
| 2026-09-30 | ArduPilot 只读消息状态适配 | 已验证离线映射；待设备验证 | 5 项新增适配测试含真实 `pymavlink` 消息对象；不接物理链路/命令链；结果和提交见本阶段记录 |
| 2026-09-30 | P4 控制安全边界 | 已验证离线假端口 | 49 项根目录测试通过；授权、Safety、出队 fence、回执和停止范围及 P5 限制见上方 P4 记录；提交 SHA 见本阶段 Git 提交 |
| 2026-09-30 | P5 ArduCopter/TCP 插件组合 | 已验证离线及本机 SITL；实机待验收 | 59 项根目录测试及本机 SITL `GUIDED` ACK 通过；范围和限制见上方 P5 记录；提交 SHA 见本阶段 Git 提交 |
| 2026-10-01 | P5 USB Rover 飞控补充验收 | HOLD 命令诊断通过；整车待验收 | 61 项根目录测试及未解锁 USB Rover HOLD ACK/心跳完成通过；Copter 机型 fence 和串口传输见上方记录；提交 SHA 见本阶段 Git 提交 |

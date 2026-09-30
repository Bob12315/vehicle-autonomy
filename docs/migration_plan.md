# 可复用框架迁移计划与记录

> **状态：P0 至 P3 已完成离线阶段；P4 尚未开始。** 本文记录从 `legacy/cuadc_2026/` 提取可复用能力的顺序、验收门槛与阶段进度。目标职责以 [V1 目标架构](framework_v1.md) 为准；[当前实现边界](architecture.md)描述根目录已有能力。本文中的源文件只是候选素材，不表示已决定复制或已在新框架运行。

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
| 4. 控制安全边界 | 授权生命周期、Execution 分派、Safety、命令回执与取消/停止语义 | 默认 SEND 关闭；双门控、TTL、撤销、代际、deadman、stop/zero、断链及唯一 writer 在假端口测试中成立 | 待开始 |
| 5. 插件与设备组合 | 所需 Vehicle Plugin、Protocol/Transport、Sensor Adapter、Deployment 组合 | 先离线与仿真验证；真实设备能力只在设备验收后声明；生产写入仍只有一个受控出口 | 待开始 |

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

### 阶段 4：证明控制边界

先在假 `VehicleCommandPort` 上实现并测试授权、Safety、排队、回执、取消和停止。对照旧配置与行为审核数值限制和 payload 白名单，不能只比较接口名称。分别记录 accepted、transmitted、ACK 和 state-observed completion；断链时不得把 stop 请求写成 stop 已送达。此阶段完成前保持根目录无生产车辆连接。

### 阶段 5：按需接入设备

只为实际需要的组合添加 Vehicle Plugin、协议编解码、Transport 和 Sensor Adapter。协议语义与字节传输分离；车辆状态映射及命令翻译属于插件/适配器。先做离线和仿真测试，再按设备环境验收真实连接。RKNN、Web、server/hybrid 和具体应用分别作为可选后续工作，不因目标架构列出目录就视为必须迁移。

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

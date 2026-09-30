# 可复用框架迁移计划与记录

> **状态：P0 限定范围的基线与候选清单已完成；P1 代码迁移未开始。** 本文记录从 `legacy/cuadc_2026/` 提取可复用能力的顺序、验收门槛与阶段进度。目标职责以 [V1 目标架构](framework_v1.md) 为准；[当前实现边界](architecture.md)描述根目录已有能力。本文中的源文件只是候选素材，不表示已决定复制或已在新框架运行。

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
| 1. 基础合同 | 时间、坐标、来源、有效性、Observation、VehicleState、WorldSnapshot、Typed Effect 及必要端口 | 类型语义明确；序列化与不变量测试通过；Core 无具体设备或业务依赖 | 待开始 |
| 2. 状态链 | 假 Sensor/Vehicle 输入、标准化观测、可选的纯感知或定位算法、World Model 发布 | 不接真实命令端口；时间戳、坐标、过期/缺失状态可测试；高级消费者只读统一快照 | 待开始 |
| 3. Mission/Action | Schema、能力预检、编译、运行生命周期、取消、结果、Typed Effect，以及按需接入 Planning/Guidance | 未注册或不支持的 Action 被拒；失败、重试、取消和退出行为有测试；Action、Planning、Guidance 均不直接发送车辆命令 | 待开始 |
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

### 阶段 2：构建状态链

先用文件、假相机或假车辆状态发布器验证 Sensor/Vehicle → Observation → World Model。可复用的纯投影、定位、融合算法逐个审核并适配新输入；相机视场角、场地朝向、类别集合等旧默认值不得偷偷成为通用默认。WorldSnapshot 对过期和未知数据作显式表达。

### 阶段 3：构建决策链

在现有 Action 注册和 Mission 校验之上，逐步加入 Schema、编译、调度、结果、失败、取消及退出屏障。先迁不要求真实车辆的 Action 以验证生命周期；需要路径或运动目标的 Action 再通过合同接入 Planning/Guidance。车辆或业务 Action 留在各自插件/应用。旧候选 Core 和旧生产 Runtime 的职责需要核对后选取，避免同时维护两套 Mission owner。

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
| 2026-09-30 | P0 基线与候选清单（限定范围） | 已完成 | [基线与 173 项旧测试、4 项根目录测试](migration/p0_baseline.md)，[候选归属及 `application/core` 依赖表](migration/p0_inventory.md)；P1 未开始 |

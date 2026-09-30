# Vehicle Autonomy Framework V1：目标架构

> **文档状态：V1 目标设计。** 本文定义可复用框架的职责、数据流和依赖边界，不代表所列组件已经实现。根目录当前能力及限制见 [README](../README.md) 和 [当前实现边界](architecture.md)。

基础类型与端口的冻结语义见 [V1 基础合同冻结规范](foundation_contracts_v1.md)。

## 1. 定位与设计目标

Vehicle Autonomy Framework 面向多旋翼、无人车、固定翼、VTOL 及未来自主移动平台。它提供组合车辆、设备、环境和自主能力的稳定边界，而不把某一种机型、飞控、计算板、感知模型或业务场景写进通用 Core。

一个系统由独立维度组合而成：

```text
Deployment × Vehicle × Protocol × Transport × Sensors
           × Perception × Environment × Mission × Intelligence
```

V1 的目标是：更换上述任一实现时，通用 Core 的规则和控制权限不随之改变。支持一种新设备或场景可以增加插件、适配器或应用，但不能因此给上层增加直接发送车辆命令的通道。**可组合**表示接口和责任允许这种接入；具体组合只有完成实现与验证后才算受到支持。

## 2. 两条主链

### 状态链：形成统一的世界认识

```text
Physical World / Vehicle Telemetry
                ↓
       Sensor / Vehicle Adapters
                ↓
Perception / Localization / Mapping
                ↓
            World Model ← Environment
                ↓
       WorldSnapshot
                ↓
Mission / Planning / Guidance / Intelligence
```

设备适配器负责采集和标准化；World Model 整合有来源、时间戳、坐标系和有效性的信息。高级模块通过稳定的状态合同读取世界，而不是各自读取原始设备流。

### 控制链：产生并受控地执行副作用

```text
Operator / External System / Intelligence
                    ↓
             Application Use Case
                    ↓
          Mission → registered Action
                         ↓
              Planning / Guidance（按需）
                         ↓
                    Typed Effect
                         ↓
                     Execution
                         ↓
             Authorization → Safety
                         ↓
                VehicleCommandPort
                         ↓
               Vehicle Plugin / Adapter
                         ↓
                 Protocol → Transport
                         ↓
                  Physical Vehicle
```

Planning 和 Guidance 是按需参与的能力，并非每个 Action 都必须经过它们。非车辆副作用也由 Execution 分派至各自受控的端口；车辆运动和执行机构命令必须经过系统 SEND、Action SEND、授权和 Safety 的完整判断。状态链中的任一生产者都不能直接成为车辆命令发送者。

## 3. 四类核心数据及其边界

| 数据 | 含义 | 约束 |
| --- | --- | --- |
| Observation | 传感器、感知或状态适配器提供的观测；原始帧与派生检测应有明确类型 | 携带来源、时间、坐标系和质量信息；不能授予控制权 |
| WorldSnapshot | World Model 在某一版本发布的车辆、对象、地图和环境状态 | 对消费者只读；标明新鲜度、有效性及所依赖的版本 |
| Intent | 操作者或 Intelligence 提出的目标、任务建议或策略选择 | 必须转成已定义的 Use Case、Mission 或 Action，并经过验证 |
| Effect | Action 请求产生的结构化副作用 | 使用已注册的类型和参数；不是 MAVLink 包，也不是已获准的车辆命令 |

`VehicleState` 是由车辆适配器发布的标准状态，供 World Model 消费；`VehicleCommand` 是 Execution 在授权和安全检查后提交给车辆端口的命令。两者不能用协议消息代替。可发送、已写入链路、收到协议 ACK、观察到动作完成，也是不同的运行事实。

## 4. 各层职责

### Transport、Protocol 与 Vehicle

- **Transport** 负责串口、UDP、TCP 等字节连接的打开、读写、关闭和链路健康；它不解释起飞、位置或 Mission。
- **Protocol** 负责消息编码、解析、关联和协议语义。MAVLink 是可选实现；同一协议应能通过不同 Transport 组合。
- **Vehicle Plugin** 声明车辆能力，映射标准状态，翻译受控命令，提供车辆专用 Action、Safety 规则和健康语义。多旋翼、Rover、固定翼及 VTOL 的差异留在插件中，通用 Core 不以 `vehicle_type` 分支实现这些差异。

车辆能力声明用于 Action 注册与 Mission 预检，但能力匹配不代表当前链路、定位和安全条件允许执行。

### Sensors、Perception、Localization、Mapping

- **Sensor Adapter** 负责设备连接、采集、时间戳、坐标系、原始数据标准化和健康状态。Camera 是 Sensor；USB、RTSP、WebRTC、文件与仿真是不同的 Camera 接入方式。Video 不另设为一级控制模块。
- **Perception** 将传感器数据变成检测、跟踪、分割、深度、障碍物或融合观测，不发送车辆命令。
- **Localization** 输出位姿、速度、朝向和定位质量，可以采用 GPS、VIO、SLAM 或融合实现。
- **Mapping** 构建或更新占据、点云、语义和地形等地图；地图的版本与坐标系应可追溯。

### Environment 与 World Model

**Environment** 提供任务场景中已知的坐标基准、地图、命名地点、区域、围栏、地标等静态或半静态信息。它不负责决定 Mission，也不发出车辆控制请求。

**World Model** 汇总车辆状态、感知、定位、地图和 Environment，并发布统一的 `WorldSnapshot`。合并时必须处理来源、时间、坐标变换、新鲜度与缺失数据；消费者不能把未知或过期状态当作确定事实。

### Planning 与 Guidance

**Planning** 根据世界状态和目标计算路线、轨迹、局部避障方案或任务方案。**Guidance** 把方案和当前状态转换成此刻的运动目标。两者输出计划或 Effect 所需的目标，不能取得 `VehicleCommandPort`、协议连接或设备 writer。

### Action、Mission 与 Intelligence

**Action** 是对外公开的、预先实现和注册的能力 API。每个 Action 定义名称、参数 Schema、输入、输出、所需车辆能力、Effect 类型、Safety 边界与退出行为。它读取 WorldSnapshot 和受约束的运行上下文，产生 Effect 或结果；不直接操作硬件。车辆专用 Action 由 Vehicle Plugin 提供，业务专用 Action 由相应 Application 提供。

**Mission** 只编排已注册 Action，负责顺序、条件、分支、重试、失败策略和取消。编译与启动前检查 Action 注册、参数和车辆能力；运行时状态及授权仍需单独判断。Mission 不解释 MAVLink、PWM 或串口。

**Intelligence** 可以生成 `MissionProposal`、Intent、语义 Observation 或已注册 Action 的参数建议。LLM 可协助目标理解与任务提案，VLM 可提供场景语义，策略模型可在允许范围内选择 Action 参数。诸如 Laya 的 Action Runtime Policy 也遵守同一边界：建议经校验后进入 Mission/Action，不能直接控制车辆或创建未经注册的底层能力。

### Execution、Authorization 与 Safety

**Execution** 是车辆命令的唯一提交边界。它接收 Typed Effect，选择受控的执行端口，记录提交和结果；不决定 Mission 目标。车辆相关 Effect 先经过系统 SEND 和 Action SEND 双门控、运行授权及 Safety，才可交给 `VehicleCommandPort`。两个 SEND 门控默认关闭。

**Authorization** 管理控制来源、Run、Lease、作用范围、代际与撤销。Mission、人工控制和紧急操作不能无限制争抢同一执行资源；授权失效后，旧请求不得在排队、重连或切换来源时再次写出。

**Safety** 是确定性的最终约束，覆盖通用规则和车辆专用规则，包括适用的速度、高度、下降率、地理围栏、请求 TTL、状态新鲜度、连续命令 deadman、失联处置及执行机构白名单。拒绝、限制或停止的结果应可观察。连续控制结束要显式 stop/zero 并清理旧命令；断链时必须区分“请求停止”与“确认车辆停止”。物理写入前仍需校验会话、代际和有效期，保证只有一个生产车辆命令 writer。

### Application、Web、Deployment 与 Gateway

`application/` 承载框架用例和组合接口；`applications/` 承载具体业务场景的 Action、Mission、配置与策略。业务场景不进入通用 Core。`app/` 是进程入口和装配位置。Web 或其他 Operator 界面只调用 Application API；状态展示、任务启动、手动请求和配置变更也遵守同一权限边界。

**Deployment** 决定组件运行在 onboard、server 或 hybrid，不改变数据与控制语义。**Gateway** 在远程部署时承接设备接入、遥测与媒体转发、链路健康、watchdog 和本地失联处置；它不负责 Mission 或模型决策。远端失联时，本地安全约束与撤销机制仍必须有效，服务器不能通过网络路径绕过唯一车辆出口。

三种部署形态的职责示意：

| 形态 | 组件位置 | 必须保留的约束 |
| --- | --- | --- |
| Onboard | 状态处理、Mission、Execution 和设备连接位于车载计算节点 | 同一节点上的上层模块仍经 Execution 与 Safety |
| Server | 高级决策与计算位于服务器，设备由车辆侧 Gateway 接入 | 远程请求仍需本地授权有效性检查、链路监视和安全处置 |
| Hybrid | 本地保留 Safety、基础感知与必要控制，服务器承担重计算 | 断网后本地安全机制独立工作，旧远程请求失效 |

## 5. 目标包归属

以下是目标责任图，**不是当前已实现目录清单**。只有出现真实需求和实现时才创建具体子包。

```text
app/                       进程入口与装配
application/               框架用例与对外服务接口
applications/              具体业务场景
core/
  runtime/ mission/ action/ execution/ safety/ lifecycle/
contracts/
  core/ vehicle/ sensor/ perception/ world/
  planning/ environment/ intelligence/
vehicles/                  车辆插件与车辆专用能力
sensors/                   设备采集适配器（camera 等）
perception/ localization/ mapping/ world_model/
planning/ guidance/ intelligence/
environments/              场景数据与环境适配器
missions/                  可装配的任务定义与目录
protocols/                 协议实现（如 MAVLink）
infrastructure/transports/ 字节传输实现
gateway/ deployment/ web_ui/
config/ runtime/ tests/
```

共享语义和端口放在 `contracts/`；通用生命周期、校验和执行规则放在 `core/`。业务、车辆、协议及设备实现通过装配进入系统，不反向成为 Core 的依赖。

## 6. 不可跨越的依赖规则

| 模块 | 可以依赖 | 不得直接依赖或执行 |
| --- | --- | --- |
| Core / Mission | 通用 Contracts、已注册 Action | 具体车辆、业务场景、Web、协议、Transport、设备 writer |
| Action / Planning / Guidance | World 与能力合同、受控 Effect | 原始车辆端口、协议连接、硬件驱动 |
| Intelligence | World、Intent、Mission/Action 提案合同 | `VehicleCommandPort`、协议、Transport |
| Perception / Localization / Mapping | Sensor 与 World 发布合同 | Mission 决策和车辆命令端口 |
| World Model / Environment | 标准状态、观测、地图和环境合同 | 原始设备控制和车辆命令 |
| Application / Web | Use Case 与状态接口 | MAVLink、串口、原始 Servo 或旁路 writer |
| Vehicle Plugin / Protocol / Transport | 各自向下的合同与适配端口 | 上层业务决策或第二条命令出口 |

无论单机还是分布式部署，车辆控制都沿 `Action → Effect → Execution → Authorization → Safety → VehicleCommandPort → Vehicle/Protocol/Transport` 前进。这里的箭头表示职责和数据流，代码依赖通过合同与注入保持向内；上层不得持有下层硬件发送对象。

## 7. 可复用性的验收标准

一个新增组合只有同时满足以下条件，才能写入“当前支持”：

1. 新 Vehicle、Sensor、Protocol 或 Environment 通过对应合同和装配接入，通用 Core 不增加针对具体实现的分支。
2. Mission 仅引用已注册且通过 Schema、能力与运行前置条件检查的 Action。
3. 车辆 Effect 经过默认关闭的双 SEND 门控、有效授权、Safety 和唯一 writer；撤销、过期、连续命令停止及断链结果有测试覆盖。
4. 状态经统一合同进入 World Model，时间戳、坐标系、来源和质量可核对。
5. 用该组合的测试或设备验证记录证明所声称的能力；接口占位、离线模拟和真实设备支持分别标注。

当前根目录尚未完成上述整体组合。本文用于约束后续实现，不改变现有运行能力。

## 8. 组合示例

以下仅说明目标架构如何组合模块，**不是当前支持清单**：

```text
Onboard + Multirotor + MAVLink/Serial + USB Camera
        + Detection + Inspection Environment + Inspection Mission

Hybrid + Rover + MAVLink/UDP + Remote Camera + LiDAR
       + Obstacle Perception + Campus Environment + Patrol Mission + VLM
```

两个组合使用同一套 Mission/Action 注册、状态合同、授权和 Execution 规则；各自增加车辆插件、设备适配器、场景配置与业务 Action。具体 Action 能否复用由其 Schema、车辆能力及 Safety 约束决定，不能只因名称相同就跨车辆启用。

# Vehicle Autonomy 系统总体架构规范 V1.0

> **状态：架构共识已确认（Baseline）**  
> **版本：V1.0 · 2026-10-23**  
> **适用仓库：** [Bob12315/vehicle-autonomy](https://github.com/Bob12315/vehicle-autonomy)  
> **当前车型范围：** ArduRover（无人车）、ArduCopter（多旋翼）、ArduPlane（固定翼）  
> **文档性质：** 总体架构与模块边界规范，不是开发任务书，也不表示所有目标能力已经实现。

## 0. 执行摘要

Vehicle Autonomy 是一个以 **ArduPilot 为车辆底层运动控制核心**、以 **Action 为统一能力接口**、以 **Mission Graph 为任务编排机制**、以 **ROS 2 与现有机器人算法生态为可替换能力来源**，并支持 **人工编排和 AI 自主编排** 的通用自主系统。

系统遵循四项基本分离：

1. **任务决策与运动执行分离**：Mission 决定做什么、何时做；ArduPilot 负责车辆实际底层运动控制。
2. **能力接口与算法实现分离**：Mission 调用 Action；Action 可使用本地程序、ROS 2、远程 API 或组合 Action 实现。
3. **状态链与控制链分离**：传感器和算法发布只读状态；车辆运动命令只经统一、受控的执行通路下发。
4. **并行执行与资源所有权分离**：多个 Action 可以并行，但共享执行器的写入必须由明确的资源仲裁机制管理。

> **一句话定义**：人工或 AI 将受支持的能力编排为 Mission；系统在统一的状态、资源、安全和执行机制下，通过 ArduPilot 驱动车辆完成任务。

## 1. 系统边界与架构原则

### 1.1 明确纳入范围

- **车辆**：Rover、Copter、Plane 三类，第一阶段均以 ArduPilot SITL + Gazebo 作为控制验证环境。
- **通信与控制**：MAVLink 状态接收、命令发送、ACK 和执行结果、连接管理、失联与会话管理。
- **能力接入**：本地 Python/C++、ROS 2 Topic/Service/Action、SLAM、Nav2、VLM/LLM API，以及由其他 Action 组合出的高阶能力。
- **任务编排**：Sequence、Parallel、Condition、Fallback/Recovery、Event/Reactive 五类基本关系；允许有限 Action 与持续 Action 同时运行。
- **使用入口**：人工编辑器与 AI 生成器共享同一种 Mission 定义、能力目录、校验器和运行时。

### 1.2 非目标与禁止的捷径

- 不用独立的 Nav2 或 AI 运动控制器直接取代 ArduPilot 的底层执行角色。
- 不让 ROS 2、Web、VLM、LLM 或普通 Action 绕过 Execution / Safety，直接向车辆运动端口写入 MAVLink。
- 不把传感器采集、滤波、TF 发布器等所有常驻组件都强行包装为由 Mission 逐个启动的 Action。
- 不强制 Rover、Copter、Plane 支持完全相同的底层运动指令。
- 不以 SITL/Gazebo 测试通过推定真实车辆已具备相同安全性；实机部署须另行验收。
- 不从历史 `legacy/` 工程直接导入未审计的控制逻辑。

## 2. 逻辑系统结构

以下是**逻辑层次**，不是要求每层对应独立进程或目录。

```text
人工 Web 节点编辑器                  LLM / AI 自主决策
         │                                 │
         └──────────────┬──────────────────┘
                        ▼
              Mission Graph / Validator
                        ▼
                  Mission Runtime
          ┌─────────────┼───────────────┐
          ▼             ▼               ▼
      有限 Action     持续 Action     Condition / Event
          └─────────────┼───────────────┘
                        ▼
             Capability / Action Adapter
        ┌───────────────┼──────────────────┐
        ▼               ▼                  ▼
    Native 实现       ROS 2 生态         Remote API
        │          Nav2 / SLAM 等        VLM / LLM 等
        └───────────────┼──────────────────┘
                        │
             World Model / 状态与反馈
                        │
             Resource / Control Authority
                        ▼
                 Execution + Safety
                        ▼
              Vehicle Plugin + MAVLink
                        ▼
              ArduRover / Copter / Plane
                        ▼
                 实际车辆执行机构
```

**必须正确理解上图**：并非所有能力都进入车辆命令链。VLM 推理、地图读取和只读监测可以返回数据而不写入飞控；**只有需要产生车辆运动效果的能力**才经受控车辆 Execution → MAVLink → ArduPilot。独立云台或其他外设使用各自的受控执行端口。

### 2.1 状态链（State Plane）

```text
飞控 MAVLink Telemetry / Camera / LiDAR / 其他传感器
                     ↓
          Vehicle / Sensor Adapters
                     ↓
      Perception / Localization / SLAM / Mapping
                     ↓
           统一 World Model / Snapshot
                     ↓
       Mission / Action / AI 只读查询
```

WorldSnapshot 应保留 **采样时间、坐标系、来源、版本、有效期、健康和质量状态**；未知或过期的观测不能被静默当作可信的控制依据。ROS 2 内部尽量使用标准消息与 TF2 约定，通过 Adapter 映射到框架合同。

### 2.2 控制链（Control Plane）

```text
Human / AI → Mission Graph → Action Runtime
                   ↓
       Planning / Guidance（根据能力选择）
                   ↓
       Resource Arbitration + Authorization
                   ↓
          Execution → Safety → 唯一写入者
                   ↓
        Vehicle Adapter → MAVLink → ArduPilot
```

标准控制结果至少区分：**请求被接收、消息已发送、飞控 ACK、观测到目标效果、已确认停止**；取消 ACK 不能冒充物理停止。运行时保留来源和任务身份，使过期任务或旧会话指令不能重新写入。

### 2.3 服务与进程层（Service Plane）

驱动、基础数据采集、SLAM/定位、必要的健康监测和 ROS 2 节点可能长期运行。Mission 调用它们提供的能力，不负责无条件销毁被其他任务依赖的系统级服务。

## 3. 底层车辆控制：ArduPilot 不可替代的角色

### 3.1 三车型统一与差异

统一内容为 **VehicleState、能力声明、受控命令合同、执行结果与安全准入**；不同车型通过插件实现不同的 AP 控制语义。

| 能力 | Rover | Copter | Plane |
| --- | --- | --- | --- |
| Arm / Disarm、模式切换 | 支持 | 支持 | 支持 |
| 前进、后退、原地转弯 | 依车辆运动学 | 不适用此语义 | 不支持 |
| 位置目标 | 支持 | 支持 | 支持，但导航语义不同 |
| 水平速度/方向控制 | 按 Rover 控制能力 | 按 Copter 控制能力 | 不能直接套用 Copter 的速度接口 |
| 起飞/悬停/着陆 | 不适用 | 支持 | 起飞/着陆支持，不能悬停 |
| 返航 / 盘旋 / 停止 | 安全停车/保持 | 刹停/悬停/RTL | 安全续飞、盘旋/RTL 等机型专属策略 |

**固定翼特别规则**：不能将 `Stop` 解释为“速度设为零”；Plane 的取消、失联和交接必须使用合适的飞行模式与安全续飞机制。

### 3.2 AP 原生导航与外部导航指导

- **AP 原生导航**：Action 向 AP 提供可支持的目标点、航点或模式，由 AP 完成自身的导航与低层控制。
- **外部导航指导**：例如 Rover 由 Nav2 计算局部路径/控制建议，Adapter 将合格结果转换为 AP 可接受的运动目标，经统一 Execution 下发。Nav2 不能另外开一条直达飞控的运动写入路径。
- **定位链**：SLAM 或其他外部定位可以向 World Model 提供观测；若要成为飞控或上层运动控制的可信定位来源，必须完成坐标、时间、质量和来源切换验证。

### 3.3 第一阶段不依赖外部感知业务

第一阶段不开发摄像头、激光雷达、VLM、SLAM 等外部感知业务。**但 SITL / ArduPilot 的内部姿态、惯导、GPS、空速等模拟或飞控状态仍是基本飞行与导航所必需的输入。** 这与“不接入外部感知系统”不矛盾。

## 4. Action：统一能力接口

### 4.1 Action 不等于完整程序

Action 是被 Mission 识别、调用、监视和取消的**能力契约**，实际实现可以为：

1. **Native Adapter**：本地 Python/C++、框架内已有 Action。
2. **ROS 2 Adapter**：调用 ROS 2 Action Server、Service，或消费 Topic 发布的数据。
3. **Remote Adapter**：调用服务器 VLM/LLM 等远端 API。
4. **Composite Adapter**：内部再调用多个 Action 或子 Mission。
5. **Test Adapter**：Fake/Mock/Replay，用于脱离实物验证合同。

同一种对外能力（例如 `NavigateTo`）可以根据车型与配置绑定不同实现，但实现选择必须依据能力声明、部署配置和准入策略，不由 LLM 任意改动底层指令。

### 4.2 Action 分类是相互独立的维度

| 维度 | 类别 | 示例 |
| --- | --- | --- |
| 功能粒度 | 基础 / 高级 / 组合 | `SetMode`、`NavigateTo`、`ExploreArea` |
| 生命周期 | 有限 / 持续 / 查询 | `Land`、`CameraStabilize`、`AnalyzeScene` |
| 实现来源 | Native / ROS 2 / Remote / Composite | MAVLink、Nav2、VLM API |
| 资源类型 | 只读共享 / 独占写入 / 协同组合 | 相机帧、车辆运动、云台目标+增稳 |
| 适用条件 | 通用 / 车型限定 / 传感器依赖 | `ReturnHome`、`PlaneLoiter`、`MonitorObject` |

Condition、Event、Sequence 等是 **Mission 控制节点**，在编辑器里与 Action 一样可见，但内部并非所有节点都代表实际设备行为。

### 4.3 标准 Action 合同

```text
ActionSpec
├── identity: name / version / description
├── parameter_schema / output_schema
├── supported_vehicle_capabilities
├── required_observations / required_services
├── required_frames / data_freshness / quality
├── resources: read / write / compose
├── execution_kind: finite / continuous / query
├── timeout / feedback / success / failure
├── cancellation / cleanup / preemption_policy
├── authority_and_safety_requirements
└── implementation_binding: adapter + version
```

原则上 **Action 不应自行打开另一个未授权的车辆 MAVLink 命令通道**。纯感知和只读查询能力无须取得车辆运动控制权。

### 4.4 ROS 2 接口适配规则

| ROS 2 模式 | 原生用途 | 在框架中的包装方式 |
| --- | --- | --- |
| Topic | 连续发布、订阅数据 | 数据管线/状态缓存；Mission 可调用查询或监测能力 |
| Service | 短时请求-响应 | 查询或管理型 Action |
| Action | 长任务、反馈、结果、取消 | Goal Action Adapter，例如 Nav2 `NavigateToPose` |
| Lifecycle / 节点管理 | 系统长期服务状态 | System Service 管理；通过 Action 暴露受控管理能力 |

ROS 2 算法继续使用标准消息和工具链，优先兼容 RViz2、rosbag、TF2、Nav2 和 SLAM Toolbox。框架 Action 不是 ROS 2 `Action` 的同义词。

## 5. Mission Graph：统一的人工与 AI 编排

### 5.1 同一任务定义，两个创建入口

- **人工模式**：在 Web 节点编辑器中配置节点、连接、参数、条件和权限。
- **AI 模式**：LLM 查询 Capability Registry、World Model 和必要的感知能力，输出同一 Mission Graph 定义。
- **协作模式**：人工固定关键流程，AI 对限定子图提出增删和参数变更；变更必须再次校验。

无论来源，Mission 都经统一 Validator、Runtime、Resource Manager、Execution 和 Safety。**AI 编排已有能力，不以任意生成并执行 Python 代码作为默认任务运行方式。**

### 5.2 五种基本编排关系及其语义

| 关系 | 基本行为 | 必须确定的边界 |
| --- | --- | --- |
| **Sequence** | 前一节点完成再执行后一节点 | 失败传播、是否允许继续 |
| **Parallel** | 多个节点并行运行 | All / Any(Race) / Main+Background 完成策略及清理 |
| **Condition** | 根据状态选择分支 | True / False / Unknown；数据质量和时效检查 |
| **Fallback / Recovery** | 当前节点失败后进入备选、恢复或重试 | 重试次数、时间预算、资源释放 |
| **Event / Reactive** | 执行过程中响应状态变化并触发行为 | 去重、冷却、触发有效期、优先级、抢占 |

`Main + Background` 是典型机器人任务：`NavigateTo` 作为主任务，`CameraStabilize` 与 `MonitorTarget` 作为后台持续行为，主任务完成或 Mission 取消时清理同一作用域内的后台节点。

### 5.3 作用域与生命周期

| Scope | 生命周期管理者 | 常见能力 |
| --- | --- | --- |
| System | 系统服务管理器 | MAVLink 通信、基础传感器订阅、必要的安全监测、长期定位 |
| Mission | Mission Runtime | 巡逻期间的目标监测、按需启用的相机增稳 |
| Action | 当前 Action / 子 Mission | 单次导航中的规划、局部路径跟踪 |

持续能力可以通过 Action 请求启停；但 Action 结束并不必然终止被多个使用者依赖的 System 服务。必须有所有权和引用关系或明确的服务状态管理。

### 5.4 复合 Action 和嵌套 Mission

高阶能力（例如 `ExploreArea`、`AutoInspect`）可由下层 Action 与控制节点组合。外层 Mission 看到的是一个具有明确参数、反馈、资源需求和退出策略的节点。嵌套必须有深度限制、总时限和循环终止条件，避免无界任务递归。

## 6. 资源互斥、优先级和抢占

### 6.1 资源模型

| 资源 | 典型占用方式 | 并行规则 |
| --- | --- | --- |
| `vehicle.motion` | Exclusive Write | 同时只允许一个被授权的运动控制主体 |
| `gimbal.control` | Exclusive / Managed Composition | 跟踪目标与增稳由同一个云台控制器融合输出 |
| `camera.stream` | Shared Read | 多个检测/监测 Action 可共享数据 |
| `lidar.scan` | Shared Read | 地图、避障、记录可并行消费 |
| `ai.inference` | 有限并发/配额 | 调度并发、超时与算力预算 |
| `payload.*` | 按执行器独占或组合 | 独立授权与副作用审计 |

同一时刻可以有多个 RUNNING Action，但同一辆车不能有两个互相独立的运动写入主体。资源权限不等于执行结果；写前仍需检查 Safety 和命令有效性。

### 6.2 两级优先级

**系统级优先级（普通 Mission 不可覆盖）：**

`强制安全保护 > 已授权人工紧急干预 > 已授权人工直接操控 > 自主 Mission > 普通后台任务`

**Mission 内部优先级：** 用于同一授权域内争用有限资源或决定事件响应顺序；不能让普通 AI Action 通过提高数值绕过系统级规则。

### 6.3 资源冲突处理策略

| 策略 | 含义 |
| --- | --- |
| `REJECT` | 资源已被占用，新请求被拒绝 |
| `WAIT` | 进入有界等待队列，超时后失败 |
| `PREEMPT` | 经授权提出抢占，取消旧控制主体并安全交接后再运行 |
| `COOPERATE` | 不竞争设备写入权，改为向共享协调控制器提交目标或约束 |

**重要：**抢占是一个有状态过程：

```text
新 Action 请求 → 权限与优先级检查 → 旧 Action 进入取消
→ 撤销旧写入权 / 隔离旧会话指令 → 验证安全交接条件
→ 新 Action 获授权并启动
```

取消请求的 ACK 不等于车辆已经停止。Rover、Copter、Plane 的安全交接条件不相同；对于不能停车的 Plane，应采用经过验证的持续飞行交接或保护模式。超时、状态未知时拒绝直接接管并触发对应故障保护。

### 6.4 避障的特殊位置

- **可选自主避障**：属于导航能力、局部规划器或 Mission 可启用的增强能力，例如 Nav2 的障碍代价地图与局部控制。
- **不可绕过的基础安全保护**：属于执行层或飞控保护，不依赖 AI 是否编排避障 Action。
- **Nav2 + AP**：Nav2 可提供规划与局部指导，但实际车辆运动请求必须经过唯一 Execution → MAVLink → AP 链路；不能与另一个直接向 AP 发速度的 Action 并列争抢。

## 7. AI、自主决策与动态 Mission 修改

### 7.1 AI 的边界

LLM 负责理解自然语言、查询能力目录、读取 World Model、按需调用 VLM/SLAM/Nav2 暴露的能力、形成 Mission，以及在任务级事件出现时提出调整。

VLM 负责图像与场景语义；SLAM/Localization 负责地图和位姿；Nav2/Guidance 负责适用车辆的路径及运动指导。高频低层控制由确定性的控制器和 AP 完成，而不是由 LLM 逐周期生成 MAVLink 指令。

### 7.2 优先读取 World Model

AI 查询环境时优先读取带时间戳、来源和质量的 WorldSnapshot；必要时再调用 `AnalyzeScene`、`GetLocalization`、`SaveMap` 等能力。不能把旧地图、失效 TF、过期图像或未经校验的语言描述默认为可信状态。

### 7.3 修改正在运行的 Mission

动态修改是**受控任务版本变更**，而非直接替换一个正在持有运动控制权的节点。变更至少需要：

- 能力、参数、车辆适配与传感器依赖检查；
- 资源冲突、权限、安全与时限预检；
- 当前任务版本与会话身份校验；
- 对需要切换控制权的节点执行取消、隔离、交接和重新准入；
- 记录修改来源、原因、输入状态、审核决策及最终执行结果。

仿真与实机可以采用不同的 AI 授权策略；仿真自动编排的通过记录不能自动转移为实机执行权限。

## 8. 端到端示例：巡逻、增稳、视觉事件

**自然语言目标：**“去 A 点巡逻，摄像头始终增稳，发现足球就停下来观察，完成后继续巡逻。”

```text
Mission: PatrolAndInspect
├── Preconditions
│   ├── VehicleReady?
│   ├── LocalizationValid?
│   └── NavigationAvailable?
└── Parallel [Main + Background]
    ├── Background
    │   ├── CameraStabilize [持续 / gimbal.control]
    │   └── MonitorObject("football") [持续 / camera.stream 只读]
    └── Main
        └── ReactiveSequence
            ├── NavigateTo(A) [有限 / vehicle.motion]
            ├── NavigateTo(B) [有限 / vehicle.motion]
            └── ReturnHome [有限 / vehicle.motion]

事件处理（与 Main 同时监听）
FootballDetected
    → 去重与状态验证
    → 请求暂停/取消当前导航
    → 安全交接并确认状态
    → AnalyzeScene(VLM)
    → InspectObject
    → 根据条件恢复导航或结束任务

退出时：清理 Mission Scope 的持续行为、释放资源与权限；
保留应长期运行的 System Scope 服务。
```

上述示例展示编排语义，不代表第二阶段已具备所有实现。普通障碍优先由导航系统内部处理；任务级事件才触发 Mission 分支或 AI 重新编排。

## 9. 分三个开发阶段演进

这三项是**实施阶段**，不要与运行时的逻辑系统层混淆。

| 阶段 | 目标范围 | 独立验收边界 |
| --- | --- | --- |
| **阶段 I：三车型基础控制** | Rover / Copter / Plane 的 MAVLink 收发、状态、能力插件、基础控制及 SITL/Gazebo | 三车型各自通过基础运动、连接/失联、取消/保护、会话与结果验证；不依赖外部感知或 AI |
| **阶段 II：传感器与 Action 能力** | 统一 Sensor Adapter、原子/高级/持续 Action、ROS 2 适配、Mission Graph、资源管理 | 传感器接口独立可测；人工可编排受支持的 Action；不要求所有传感器真实参与控制 |
| **阶段 III：AI 自主闭环** | LLM/VLM、SLAM、World Model、事件响应、动态 Mission、外部导航协调 | 在仿真中完成有变化、有失败恢复且可审计的端到端自主任务；实机单独验收 |

### 9.1 第一阶段的特别说明

该阶段必须完成三种**车辆类型**的仿真控制，而不是在 Rover 上完成之后把 Copter / Plane 视作同一实现。三车型通过统一控制合同、不同的 Vehicle Plugin 适配 ArduPilot。基础控制层不应因为后期引入 Nav2、VLM 或摄像头而发生结构性重写。

### 9.2 第二阶段的特别说明

传感器合同与能力接入先做正确，即使尚未启用实际导航作用也可以单独验收。Action 可以将 ROS 2 原生功能包装为当前框架的能力接口。**不以重写成熟 ROS 2 算法作为阶段目标。**

### 9.3 第三阶段的特别说明

AI 不取代 Mission Runtime，也不直接取代 Guidance/AP；它负责**基于环境和能力动态编排、监督及调整任务**。第三阶段重点是闭环能力和可靠性，不是仅让模型输出文本计划。

## 10. 当前仓库与目标架构的关系

以下仅是依据截至 **2026-10-21** 的仓库审计记录形成的背景说明，与本文件所冻结的目标架构分开。

| 领域 | 当前基础与差距 |
| --- | --- |
| `contracts/`、`core/` | 已有合同、MissionRuntime、ActionRegistry、Execution、Safety、ControlAuthority，应优先复用而非推翻。 |
| `vehicles/rover/`、`vehicles/multirotor/` | 既有 Copter/Rover 基础 SITL + Gazebo 控制验收；Plane 尚需正式插件与物理验证。 |
| `protocols/mavlink/` | 已有 MAVLink 基础子集收发及命令链，非全量 MAVLink 协议支持。 |
| `application/`、`deployment/` | 现有运行时主要执行有限顺序任务；通用 Mission Graph、并行节点和资源仲裁仍属于目标能力。 |
| `integrations/ros2/` | 已有 Nav2 规划与 RS16 扫描适配基础；尚非任意 ROS 2 能力均可注册执行的通用 Action Adapter。 |
| 真实车辆 | 硬件读状态与受限传感器证据不等于真实运动准入；本文件不授权实机控制。 |

因此，**“架构确认”只确认设计方向与边界，不代表声明各模块已经完成。**

## 11. 本版本已确认的架构决策

| 编号 | 已确认决策 |
| --- | --- |
| D01 | 当前支持 Rover、Copter、Plane 三种车辆类型；第一阶段全部要求仿真控制验证。 |
| D02 | ArduPilot 是车辆底层运动控制系统，所有车辆运动输出统一经受控 MAVLink/Vehicle 边界。 |
| D03 | Action 是标准能力接口，可以封装程序，也可以适配 ROS 2、VLM、SLAM、Nav2 和远端 API。 |
| D04 | 人工与 AI 使用同一 Mission Graph、校验与执行机制。 |
| D05 | Mission 支持顺序、并行、条件、失败恢复、事件响应五种基本编排关系。 |
| D06 | Action 支持有限、持续、查询及复合能力；并且可以具有 System/Mission/Action 不同生命周期。 |
| D07 | Mission 可嵌套并复用已有的高阶组合 Action。 |
| D08 | Action 并行须声明资源；同一车辆运动端口不允许多个未仲裁控制主体同时写入。 |
| D09 | 采用系统级安全/人工优先级与 Mission 内部资源调度优先级两级机制。 |
| D10 | 抢占需要取消、撤销旧写权限、验证安全交接、再授予新控制权。 |
| D11 | 基础安全机制独立于 Mission；选用或停用 AI/避障能力不能绕过必要安全约束。 |
| D12 | 状态链和控制链分开；World Model 提供带来源、时间、版本和有效性的只读状态。 |
| D13 | ROS 2 生态优先复用原生 Topic/Service/Action 与消息标准，但车辆运动不绕过执行边界。 |
| D14 | 三阶段依次构建控制底座、传感器/Action 能力、AI 自主任务闭环；阶段验收分别独立。 |

## 12. 保留为后续细化的实现细节

这些不是架构分歧，也不在本次文档中提前冻结具体实现：

- Mission Graph 的持久化格式、节点版本兼容、图编辑协议和可视化 UI 细节。
- Resource Manager 的具体数据结构、调度算法、队列公平性以及优先级数值分配。
- 各 ROS 2 Adapter 的进程边界、DDS 域、桥接协议与运行部署方式。
- 三车型专属 Capability 清单、AP 模式映射和全部 Action 参数及阈值。
- AI 在线变更权限策略、模型选择、VLM/SLAM 具体实现及相应实机审核规则。
- 真实车辆安全等级、紧急停车/持续飞行交接与设备校准等专门的验收合同。

这些细节今后可以迭代，但**不得违背第 11 节的架构决策**。

## 13. 参考仓库文档

- [README：现有实现概述](https://github.com/Bob12315/vehicle-autonomy/blob/main/README.md)
- [framework_v1.md：历史目标架构](https://github.com/Bob12315/vehicle-autonomy/blob/main/docs/framework_v1.md)
- [architecture.md：现有实现边界](https://github.com/Bob12315/vehicle-autonomy/blob/main/docs/architecture.md)
- [v1_progress.md：现有模块进度](https://github.com/Bob12315/vehicle-autonomy/blob/main/docs/v1_progress.md)
- [simulation/completion-audit.md：基础仿真审计](https://github.com/Bob12315/vehicle-autonomy/blob/main/docs/simulation/completion-audit.md)
- [HARDWARE_READY_AUDIT.md：实机只读与集成审计](https://github.com/Bob12315/vehicle-autonomy/blob/main/docs/HARDWARE_READY_AUDIT.md)

---

**版本结论：** 本文将本轮讨论的系统定位、AP 控制底座、Action 接口化、Mission Graph、ROS 2 适配、并发资源仲裁、安全边界与三阶段演进方案确定为 **V1.0 已确认架构基线**。后续可以基于该基线讨论模块和实现，但不应把“基础控制”“自主行为”“AI 决策”重新耦合成单一大程序。

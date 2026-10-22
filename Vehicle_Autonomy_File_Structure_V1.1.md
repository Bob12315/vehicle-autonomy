# Vehicle Autonomy 文件结构规范 V1.1

> **状态：架构共识已确认；文件迁移目标规范（不是已实施声明）**  
> **适用目录：** `/home/level6/vehicle-autonomy-framework/`  
> **关联总架构：** `/home/level6/vehicle-autonomy-framework/Vehicle_Autonomy_V1.0.md`  
> **日期：** 2026-10-23  
> **范围：** 仅定义代码组织、模块职责、依赖与迁移验收原则；不要求新增任何尚未实现的功能。

## 1. 核心约定

Vehicle Autonomy 是一个以 **ArduPilot 为车辆底层运动控制核心**、以 **Action 为统一可编排能力接口**、以 **Mission Graph 为任务编排机制**，同时支持 **人工与 AI 使用同一套任务机制**的通用自主系统。

本规范确定：

1. 只设置七个顶层 Python 业务包：`contracts`、`engine`、`actions`、`vehicles`、`world`、`autonomy`、`app`。
2. **不建立独立 `capabilities/`、`adapters/` 或 `integrations/` 顶层业务包。** 外部系统调用按职责放入对应 Action 或数据/设备模块；复杂实现可以在本模块内拥有私有客户端和辅助文件。
3. `Action` 不等于独立进程或完整算法。Action 可以封装本地函数、ROS 2 Action/Service、远程 VLM API、持续服务管理操作或其他 Action 的组合。
4. `engine` 提供 Action/Mission 的注册、调度、生命周期、资源仲裁与安全执行机制，**不实现具体业务 Action**。
5. `vehicles` 实现 ArduPilot/MAVLink 状态收发与三车型差异；**所有车辆运动写入最终经统一 Execution/Safety 与唯一 writer 交给 AP**。
6. `world` 负责持续的数据源、观测、定位、建图、世界状态；Mission 可调用相应 Action 查询或管理能力，但不必逐一启动常驻驱动。
7. `autonomy` 容纳可复用的规划、Guidance、AI 决策算法；其对 Mission 可见的具体能力由 `actions` 暴露。
8. `app` 仅负责用户入口、应用用例、业务场景及依赖装配，不能成为第二个控制引擎。
9. 坚持状态链与控制链分离；只读推理不经过车辆运动 Execution，有副作用的输出必须经过相应授权边界。
10. 本次**仅进行代码目录迁移与必要的导入/资源路径/入口/配置/测试修复**。不补做 Mission Graph 并行、优先级、Plane 支持、Nav2 适配、实车控制等新功能。

## 2. 推荐目录树

`src/vehicle_autonomy/` 为唯一正式 Python 包根。下面的子目录表示**目标归属**，若当前没有实际代码，不必创建空文件或占位实现。

```text
vehicle-autonomy-framework/
├── Vehicle_Autonomy_V1.0.md             # 已确认的系统总体架构；保留原文
├── Vehicle_Autonomy_File_Structure_V1.1.md  # 本文件；目录及依赖规范
├── README.md
├── AGENTS.md
├── pyproject.toml                      # 统一包发现、测试及 CLI 安装配置
│
├── src/
│   └── vehicle_autonomy/
│       ├── __init__.py
│       │
│       ├── contracts/                  # 数据、接口、类型契约
│       │   ├── common/                 # 时间、坐标、标识、质量、序列化
│       │   ├── vehicle/                # VehicleState / Command / Ports
│       │   ├── world/                  # Observation / WorldSnapshot 类型
│       │   ├── action/                 # Action / Mission 数据类型和接口
│       │   └── effects/                # Typed Effect 与执行请求
│       │
│       ├── engine/                     # 与车型和算法无关的运行内核
│       │   ├── mission/                # Mission 编译、运行、调度
│       │   ├── action/                 # 注册表、实例和生命周期
│       │   └── control/                # Execution / Safety / Authority / Resources
│       │
│       ├── actions/                    # 唯一的可编排 Action 实现集合
│       │   ├── common/                 # 通用车辆行为
│       │   ├── rover/                  # Rover 专用行为
│       │   ├── copter/                 # Copter 专用行为
│       │   ├── plane/                  # Plane 专用行为（未来）
│       │   ├── navigation/             # 导航及 Nav2 能力 Action
│       │   ├── perception/             # 视觉/VLM 查询及监测 Action
│       │   ├── mapping/                # SLAM 管理、地图保存、重定位 Action
│       │   ├── devices/                # 云台、载荷等独立设备 Action
│       │   └── composite/              # 可复用的组合 Action
│       │
│       ├── vehicles/                   # AP、MAVLink、三车型适配
│       │   ├── ardupilot/              # MAVLink、会话、传输、遥测、共享逻辑
│       │   ├── rover/                  # ArduRover 状态与命令翻译
│       │   ├── copter/                 # ArduCopter 状态与命令翻译
│       │   └── plane/                  # ArduPlane 插件（未来）
│       │
│       ├── world/                      # 观测与世界状态生产/管理
│       │   ├── model/                  # WorldModel 的实际实现与状态发布
│       │   ├── sensors/                # Camera/LiDAR 等持续采集、缓存
│       │   ├── perception/             # 视觉/障碍物数据处理
│       │   ├── localization/           # 状态估计、位置来源、校验
│       │   ├── mapping/                # 栅格、地图来源、锚点
│       │   ├── environment/            # 环境资源、围栏、命名位置
│       │   └── transform/              # 坐标系和变换服务
│       │
│       ├── autonomy/                   # 可复用的上层算法与决策
│       │   ├── planning/               # 路径规划、碰撞几何、计划验证
│       │   ├── guidance/               # 跟踪与运动指导算法
│       │   └── intelligence/           # LLM/任务提案等模型侧逻辑
│       │
│       └── app/                        # 应用服务、入口、组合与 Web
│           ├── api/                    # 外部应用接口、IPC
│           ├── operator/               # 人工操作及审批用例
│           ├── mission_designer/       # 人工/AI 任务编辑与准入用例
│           ├── scenarios/              # 具体业务任务目录、配方
│           ├── web/                    # HTTP 服务与 static 前端
│           ├── bootstrap/              # SITL / readonly 硬件装配、进程管理
│           └── cli.py                  # 统一命令行入口
│
├── configs/                             # 车辆、设备、模型、部署配置
├── simulation/                          # SITL/Gazebo 模型、world、profile、数据
├── tests/                               # 单元/集成/SITL/Gazebo 测试
├── scripts/                             # 构建、部署、测试、运维脚本
├── docs/                                # 过程证据与其他技术文档
└── .github/                             # CI
```

**说明：** `contracts/action/` 仅存 Action/Mission 的类型合同，`engine/action/` 仅存运行机制，`actions/` 存具体可编排能力；这不是三套 Action 实现。另需将源码中现存的 `contracts/core`、`contracts/decision.py` 等按实际耦合程度审慎归位，不强制为了形状整齐把稳定模块拆碎。

## 3. 七个模块的职责边界

| 模块 | 应该包含 | 不应该包含 |
| --- | --- | --- |
| `contracts` | 数据类型、Protocol/Port、枚举、不可变合同 | ROS 2/PyMAVLink 依赖或业务执行逻辑 |
| `engine` | Action 注册/生命周期、Mission、Effect、资源互斥、权限、安全 | Nav2、VLM、ArduPilot 具体实现、Web |
| `actions` | Mission 可见的业务能力及内部 ROS 2/API 调用 | 绕过授权直写车辆，基础传感器持续驱动的主循环 |
| `vehicles` | MAVLink 收发、三车型适配、连接会话、飞控遥测 | 任务编排、AI 决策、业务 Action |
| `world` | 数据源、传感器、感知、定位、地图、WorldModel、环境 | 决定 Mission 执行顺序、未经授权写车辆 |
| `autonomy` | 规划、引导、AI 任务分析、复用算法 | MAVLink 唯一 writer、Web 页面、车辆插件 |
| `app` | UI/API/CLI、任务编辑服务、具体场景、运行时装配 | 重写第二套 Mission 引擎或 Safety |

### 3.1 外部系统归属规则——不设置全局 `adapters/`

- **Nav2 的 NavigateToPose 等 Action Client**：放入 `actions/navigation/` 的 Action 实现或其内部私有辅助模块；纯路径规划的可复用算法/数据转换可归入 `autonomy/planning/`。
- **SLAM Toolbox 的持续数据/定位/地图服务**：生产与订阅放入 `world/localization/`、`world/mapping/`；由 Mission 主动调用的 SaveMap、StartMapping 等能力放入 `actions/mapping/`。
- **Camera/LiDAR ROS Topic 订阅及驱动**：放入 `world/sensors/`；由 Mission 调用的 AnalyzeScene、MonitorTarget 放入 `actions/perception/`。
- **VLM/LLM 请求**：若提供独立可编排能力（AnalyzeScene），放入 `actions/perception/`；任务自动生成或修订逻辑放入 `autonomy/intelligence/`，人工审核/启动放入 `app/mission_designer/`。
- **机器人原生设备协议和 SDK**：按数据/设备所有者存于 `world/sensors/` 或 `vehicles/`；需要复用时拆分为该模块的私有实现，不为“适配”新建根包。
- **ROS 2 Topic 只是连续数据源，不必强制做成 Action**；ROS 2 Action、Service 只有在需要被 Mission 显式编排时才封装为本框架 Action。

### 3.2 状态链与控制链

```text
状态链：
AP Telemetry / Camera / LiDAR → vehicles / world.sensors
    → world.perception / localization / mapping → WorldModel
    → Mission / Action / AI 只读查询

车辆控制链：
Human / LLM → Mission → Action → Engine Control
    → Authorization / Safety / 唯一 writer
    → Vehicles / MAVLink → ArduPilot → 运动执行器

独立设备副作用：
Action → 相应设备的受控执行接口 → 独立设备
```

`Nav2` 可以产生路线或运动建议，但不可新建绕过 Engine Control 的直接飞控写入通道；AP 始终是车辆最终的底层运动控制系统。Copter、Rover、Plane 具备不同的导航、制动、悬停、返航语义，不应使用不正确的公共命令模拟其能力。

## 4. Mission 与 Action 的长期目标（本次不实现）

- **五种编排关系**：Sequence、Parallel、Condition、Fallback/Recovery、Event/Reactive。
- **两类运行行为**：有限 Goal Action 与持续 Continuous Action；Condition/Event 是流程节点，非必须输出运动命令。
- **作用域**：System、Mission、Action。系统级通信/必要安全服务不随 Mission 结束而被关闭。
- **资源仲裁**：Shared Read、Exclusive Write、Managed Composition；资源包括 `vehicle.motion`、`gimbal.control`、`camera.stream` 等。
- **抢占语义**：只有经过授权和资源交接的新任务可获得写入权；Cancel ACK 不等于物理停止。
- **优先级**：强制安全 > 授权人工干预 > 正常人工控制 > 自主 Mission > 后台任务；普通 AI 不可改写强制级别。
- **AI 与人工共用同一 Mission 定义和 Validator/Runtime**；AI 选择注册 Action，不通过任意代码执行获得控制权。
- **高级 Action** 可以使用本地算法、ROS 2、远程 API 或其他 Action 构成。

上述是**已确认的未来逻辑架构**，不是本次文件迁移时可以顺便实现的任务。应完整保留现有已验证行为，待后续独立阶段开发。

## 5. 现有文件归属映射

以下是**按职责的迁移指引**，不是将旧目录整个无差别移动到单一目标。具体文件需要先分析 imports、调用方、测试和运行入口。

| 现有位置 | 新位置/处置原则 |
| --- | --- |
| `contracts/` | `src/vehicle_autonomy/contracts/`，保留稳定合同，必要时整理少量内部层次 |
| `core/action_registry.py`、`core/actions.py`、`core/mission*.py` | `engine/action/`、`engine/mission/` |
| `core/control_authority.py`、`core/*execution.py`、`core/vehicle_safety.py` | `engine/control/`；针对独立载荷执行的代码可与对应设备执行领域共同封装 |
| `core/sitl_mode_action.py` | `actions/common/` 或 `actions/simulation/`，不留在通用 Engine |
| `core/transform.py` | `world/transform/`，保留原变换语义 |
| `actions/` | `actions/` 对应行为目录 |
| `vehicles/` | `vehicles/{rover,copter,ardupilot}/`；新增 Plane 目录本次不创建空实现 |
| `protocols/mavlink/` | `vehicles/ardupilot/mavlink/` |
| `infrastructure/transports/` | 车辆相关放 `vehicles/ardupilot/`，非车辆通道归对应所有者 |
| `infrastructure/simulation/payload.py` | `actions/devices/` 或其同域执行支持，不改设备 Effect 语义 |
| `sensors/` | `world/sensors/`；传感器数据源、健康等保留 |
| `perception/` | `world/perception/`；对 Mission 可编排的能力才迁 `actions/perception/` |
| `localization/`、`mapping/` | `world/localization/`、`world/mapping/` |
| `world_model/` | `world/model/` |
| `environments/` | `world/environment/` |
| `planning/`、`guidance/`、`intelligence/` | `autonomy/planning/`、`autonomy/guidance/`、`autonomy/intelligence/` |
| `integrations/ros2/nav2_*` | 按实现用途归 `actions/navigation/` 与 `autonomy/planning/`，不创建顶层 Integration |
| `integrations/ros2/mapping_node.py`、`rs16_scan.py` | `world/mapping/`、`world/sensors/lidar/` 等数据所有者内部 |
| `integrations/ros2/native/` | 同归属功能目录的 `native/`，保留全部许可证和上游说明 |
| `integrations/robosense/` | `world/sensors/lidar/robosense/`，保留 vendor notices |
| `application/` | 按实际职责拆为 `app/api`、`app/operator`、`app/mission_designer`、`autonomy`、`world`；不能整体照搬 |
| `applications/` | 具体任务入 `app/scenarios/`，可重用组合行为入 `actions/composite/` |
| `deployment/` | 启动和进程装配入 `app/bootstrap/`；导航业务/安全规则按职责迁到 `autonomy/`、`actions/`、`engine/` 等 |
| `app/`（原） | `app/cli.py`、`app/api/`、`app/bootstrap/` 等 |
| `web_ui/` | `app/web/` 与 `app/web/static/` |
| `runtime/*.py` | 配置解析和运行装配代码归 `app/bootstrap/`；`.toml` 配置归 `configs/` 或 `simulation/profiles/` |
| `config/` | `configs/`；保持环境/密钥文件引用和忽略策略 |
| `gateway/` | 当前只有占位，删除占位包，不为未来功能先建空目录 |
| `simulation/` | 根目录保持，数据和模型不强制包化 |
| `tests/`、`scripts/`、`docs/`、`.github/` | 根目录保持，更新导入、调用路径、资源路径及工作流 |
| `legacy/` | **明确要求删除**；仅在核实范围、确认无运行时依赖、记录 Git 状态和移除影响后删除 |

### 5.1 已知容易遗漏的兼容点

1. 项目当前使用大量顶层绝对导入（例如 `from core...`、`from application...`），进入 `src/vehicle_autonomy` 后需统一改为 `from vehicle_autonomy...`，并改动测试、脚本、入口；禁止永久保留一整套旧包镜像或通配桥接模块。
2. 原运行方式 `python -m app.main`、`python -m app.hardware`、`python -m app.web`、`python -m app.plan` 等需要在安装后的新包入口中提供对应使用途径，并同步更新 Shell/Python 脚本、systemd 示例、文档及 CI。迁移造成的命令行入口名称变化必须在报告中列出。
3. Gazebo/SITL world、SDF、TOML、地图、录像、许可证与测试资源可能按 `__file__` 的父目录找路径；统一建立受控的项目资源定位方式，不依赖偶然的当前工作目录。
4. ROS 2 与真实硬件相关可选依赖应延迟/按需加载；基础 Core 和普通单元测试不应要求 ROS 2 已安装。
5. 保持既有硬件 `hardware_readonly` 限制、`hardware_controlled` 拒绝、SEND 默认关闭、旧会话隔离、TTL/时间域校验、Lease、唯一 writer 和已记录的 `UNCONFIRMED` 停止语义。
6. 删除 Legacy 后，文档/测试/脚本中不得再引用不存在的 Legacy 文件；历史记录可作为过去事件描述保留，但不可作为现行运行路径。
7. 原始 License/Notice、二进制构建接口、真实雷达插件及 ROS 文件应完整保留，不得为了减少目录无意丢弃源码和声明。

## 6. 迁移验收标准（本次范围）

迁移成功表示**同一份现有功能被搬进新目录，行为和原安全策略未变化**，而不是新架构未来愿景已经实现。最低要求：

- [ ] 迁移前记录 Git branch、HEAD、工作区状态、Python/ROS/Gazebo 可用性，以及现有测试基线。
- [ ] 在独立分支迁移；所有现有正常代码归入七个包，旧业务包不再残留在根目录。
- [ ] `src/vehicle_autonomy/` 可在受控虚拟环境内安装/导入；无旧包路径泄漏、循环导入、包外隐式依赖。
- [ ] 确认默认入口与硬件只读入口仍不发送运动命令；实际 `hardware_controlled` 配置仍被拒绝。
- [ ] 不改变 Action、Mission、Effect、Safety、MAVLink 的外部语义；不删除必要测试以获取 PASS。
- [ ] 原有单元测试按新包导入继续运行；ROS/ARM64 专用或外部 Gazebo 测试分别记录执行/未执行原因。
- [ ] 若本地具备 SITL/Gazebo，运行迁移前可复现的 Copter/Rover 仿真回归；不能用此前仓库的历史 PASS 替代迁移后验证。
- [ ] 新 CLI、部署脚本、Web 静态资源、配置、ROS 入口、测试与 CI 文件路径全部调整。
- [ ] 所有现有第三方声明和许可证迁移完整。
- [ ] 验证 Legacy 不再作为运行或测试依赖，再删除 `/home/level6/vehicle-autonomy-framework/legacy/`；检查 Git 删除记录及残留。
- [ ] 输出 `docs/ARCHITECTURE_MIGRATION_REPORT.md`：文件迁移清单、测试命令与结果、未执行测试和原因、兼容变化、风险与剩余事项。
- [ ] 不新增 Plane 控制、Mission 并行/优先级、VLM/SLAM/Nav2 功能、真实车辆写入或其他业务扩展。

## 7. 与已有总体架构文档的关系

- `Vehicle_Autonomy_V1.0.md` 仍是**系统行为、Action/Mission/ArduPilot 角色、安全边界**的权威描述。
- 本文件是**文件组织、包名称和模块归属**的权威描述，以当前确认的七个模块为准。
- 总体架构文档中的 “Adapter” 可以理解为 Action 或所属模块的**内部实现模式**，**并不意味着必须有独立 `adapters/` 顶层文件夹**。
- 任何尚未实现的目标设计不得借本次文件搬迁偷偷变为默认开启的生产行为。

**最终结构原则：** `contracts` 定义接口，`engine` 管理执行，`actions` 暴露可编排能力，`vehicles` 控制 AP，`world` 管理状态，`autonomy` 提供规划与智能，`app` 负责入口和装配。

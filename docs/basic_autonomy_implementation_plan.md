# Vehicle Autonomy Framework：从仿真车辆底座到基础自主系统

**状态：P9–P11 已验收；P12–P17 继续按本文实施，证据见 [P9](autonomy/phase-9.md)。** 制定日期：2026-10-03。本文覆盖完整后续主线，供另一会话按阶段实施。P9 的接口设计和更细执行步骤见 [P9 专项计划](p9_application_runtime_plan.md)。当前已通过的仅是 [ArduCopter + Rover 基础控制 Simulation Complete](simulation/completion-audit.md)：审计记录 125 项单元测试、11 个回归阶段、5 个物理场景、零失败及零核心跳过。本计划不重新打开已验收的 Vehicle 功能范围。

## 1. 目标、阶段和完成口径

```text
已完成：Copter/Rover + SITL/Gazebo 基础车辆控制
       ↓
P9  Application Runtime
       ↓
P10 Localization + Transform + WorldModel 正式状态链
       ↓
P11 Environment（origin/home/geofence/命名位置/区域）
       ↓
P12 基础 Action
       ↓
P13 基础 Mission                 ← 基础自主系统闭环门槛
       ↓
P14 Sim Sensor / Sim Object
       ↓
P15 CUADC 非视觉 Mission 迁移    ← 仿真业务链门槛
       ↓
P16 真实硬件验收（当前暂缓）
       ↓
P17 Camera/YOLO 感知替换
       ↓
以后按需求：Planning / LLM / Agent
```

P9–P15 以 localhost SITL/Gazebo 为主要验收环境。P16 是**单独解冻的硬件阶段**，当前只列计划，不授权连接真实飞控或车辆。P17 的视觉接入不应阻塞 P13/P15。固定翼/VTOL、Web UI、云端 Gateway、SLAM/VIO、RTAB-Map、深度估计、LLM 和 AI Planner 不进入这些阶段的默认工作清单。

“基础自主系统完成”是 **P9–P13 全部通过**，表现为 Application 发起命名地点任务，经 WorldSnapshot、Action、Typed Effect、Execution 和 Vehicle，在 Gazebo 运动后回到更新的 WorldSnapshot。P14/P15 再把对象观测和比赛业务迁移进来；P16/P17 各有独立验收。不能因目录存在或单元测试绿色就提高阶段状态。

## 2. 当前基线、全程约束与交付方式

当前仓库为 `/home/level6/vehicle-autonomy-framework`。现有可复用接口：`deployment/simulation_runtime.py::SimulationRuntime`、`runtime/simulation_profile.py::SimulationProfile`、`localization/reported.py::ReportedPoseLocalization`、`core/transform.py::TransformTree`、`world_model/service.py::WorldModel`、`core/mission_runtime.py::MissionRuntime`、`core/action_registry.py`、`core/vehicle_execution.py`、`application/mission_service.py`。当前缺口：正式 App 长运行入口、Localization/Transform 在线组合、Environment、通用运动 Action 和业务 Mission。`WorldSnapshot` 已有 `vehicle`、`localization`、`objects`、`map`、`environment` 字段；字段存在不等于在线生产者已接入。现有 `WorldModel.publish()` 会选用 vehicle/localization/objects，尚未发布 Environment 引用。当前 `SimulationRuntime.cycle()` 只更新车辆状态后发布 WorldSnapshot。

所有阶段必须保持：

1. 上层 Action/Mission 只读取只读 Snapshot 并产生 Typed Effect；车辆命令始终通过 `VehicleExecution → VehicleSafetyPolicy → ControlAuthority → Vehicle Plugin → MAVLink 唯一 writer → Transport`。系统 SEND、Action SEND 默认关闭，Lease/Session/期限在写入前复核。禁止 Application、Environment、Sensor、Perception 直接持有车辆端口。
2. `contracts/` 视为冻结。确有语义缺口时先记录理由、最小变更和兼容性，增加合同测试，独立提交。不同时间域/Frame/来源的数据不能默认为可互换；缺失、过期、未来时间、会话切换都要显式处理。
3. `/home/level6/uav_ws/cuadc2026/` 是**绝对只读参考**；新根目录不导入 `legacy/`。迁移时审依赖和安全行为，重写到相应新边界，不复制整个旧运行时。当前真实设备接入继续冻结；不打开 `/dev/tty*`，不把 SITL PASS 宣称为实机安全。
4. 每阶段先看 `git status`、保留已有未提交工作；检查相关测试和 SITL/Gazebo 场景后提交一个稳定里程碑，不自动 push。新增验收保留原数值门槛，不能 `skip`/`xfail` 核心场景、删失败测试或降低容差求绿。
5. 每阶段在 `docs/autonomy/phase-<编号>.md` 留下命令、提交 SHA、场景/配置版本、单元和 E2E 结果、日志/真值报告、失败诊断、限制。大型日志留在忽略的 `artifacts/`。只停止本阶段自己创建的进程，并验证端口和进程组已清理。

后续执行者按 `读现状 → 冻结阶段合同/场景 → 实现 → 单元测试 → 进程/SITL/Gazebo 集成 → 故障注入 → 回归 → 审计 → commit` 工作。普通构建、依赖、启动、端口、配置和测试失败自行诊断修复。每阶段明确宣布 PASS 后再进入下一阶段；P16 的硬件解冻是例外，不得从计划文字推断已获授权。

## 3. 阶段总览

| 阶段 | 目标产物 | 先决条件 | 阶段退出证据 |
| --- | --- | --- | --- |
| P9 | 长运行 Application Runtime 与本机用例控制 | Vehicle Simulation Complete | Copter/Rover 进程持续状态、受限 Typed Mission、取消/关闭/重连及原回归 |
| P10 | 在线定位投影、TransformTree、WorldSnapshot | P9 状态循环 | 两车动态 Frame 与 Localization 同版快照；断链/时钟故障 fail closed |
| P11 | 版本化 Environment | P10 坐标基准 | 命名地点、home、区域/围栏可解析且与快照版本一致 |
| P12 | 注册的基础 Action | P9–P11 | 只读世界→Effect→结果；两车动作、取消/失败通过 Gazebo |
| P13 | Copter/Rover 基础 Mission | P12 | 从 Application 启动完整命名地点路线，状态与物理真值闭环 |
| P14 | Sim Object/Sensor Adapter | P13 | 对象 Observation 的来源/时间/失效进入 WorldModel，任务不读取 Oracle |
| P15 | CUADC 非视觉业务迁移 | P14 | 仿真对象驱动的新 Action/Mission 业务链，无旧运行时依赖 |
| P16 | 真实硬件验收 | 单独用户决定解冻 | 设备专属安全、时间、停止/失联和实际运动证据 |
| P17 | Camera/YOLO 替换 Sim Sensor | P14/P15 稳定 | 相同 Observation 边界下真实视觉输入与业务回归 |

## 4. P9 — Application Runtime

**目标。** 将目前主要由 `tests/simulation/*` 驱动的 `SimulationRuntime` 装配成 `python -m app.main run --profile copter_sim|rover_sim` 可持续运行的本机仿真进程，提供状态、已注册任务启动/取消及安全 shutdown。详细规格、候选文件、CLI 协议和 P9.0–P9.5 顺序见 [P9 专项计划](p9_application_runtime_plan.md)。

**实现。** 复用现有车辆 Runtime；解决 `MissionRuntime` 的 `EffectEnvelope` 与 `SimulationRuntime.submit_effect()` 自建 Envelope/固定 Action ID 的身份不一致，保留 Run/Action/Effect ID 和期限，经 Execution 分派并回流结果。应用进程持续 `cycle()`，无 SITL 时保持可查询的连接中状态并有界重试；失联撤销授权、终止旧任务、重连只读。首个任务仅为现有受限 `disarmed_mode` Typed Mission：Copter GUIDED、Rover HOLD，不在 CLI 暴露任意 Effect 或运动命令。默认双 SEND 关闭，显式 `--allow-send` 也仅允许注册任务的分步授权。

**测试与门槛。** 单元测试身份链、门控、幂等、期限、失联和关闭；真实应用进程分别连接两车 SITL/Gazebo，连续查询新鲜快照，验证模式 ACK 加后续状态、取消/SIGTERM/重连/旧命令隔离。保留 `app.main status` 默认断连语义；完整 `./scripts/test_simulation_v1.sh` 无退化，新增进程场景不得只由测试脚本私有 Runtime 代替。P9 PASS 后才能把 App 入口写成已支持；仍不宣称 onboard 或真实车辆。

## 5. P10 — Localization + Transform + WorldModel 在线链

**目标。** 在 P9 的长运行进程内形成 `VehicleState → ReportedPoseLocalization → TransformTree → WorldModel → WorldSnapshot`。第一版使用 ArduPilot EKF/SITL 自报位置，不做 GPS/VIO/SLAM 融合，不把 reported pose 称为独立真值。

**现有证据与落点。** `localization/reported.py::ReportedPoseLocalization.estimate()` 已能离线产出 `LocalizationEstimate`；`core/transform.py::TransformTree` 有按时间查询、插值和无外推规则；`world_model/service.py::WorldModel.update_localization()` 已存在。改动主要在 `deployment/simulation_runtime.py` 或 P9 组合器、`localization/`、`core/transform.py` 的接线与测试；尽量不动冻结合同。

**实施顺序。** 先写 Frame 图：`odom` 是局部 ENU，`base_link` 是车体 FLU，`odom → base_link` 来自同一 VehicleState 的位姿并按采样时间更新；`map`/Gazebo world 到 `odom` 不能凭名字假设单位变换，只有测得/配置并附版本后才加入。每次有效车辆状态更新时产出独立 LocalizationEstimate，再将**同一源版本**的 vehicle/localization 和动态 transform 纳入发布周期。记录 source capture、receive、publish 时间和 clock domain；按原 WorldModel 规则拒绝未来、过期、异域或逆序样本。定位不可用时 WorldSnapshot 的 localization 为空或状态明确降级，不能沿用上次有效 pose 冒充当前。重连须新 generation/Transform epoch，不能跨 SITL 重启外推旧姿态。

**测试/验收。** Copter/Rover 静止、+X/+Y 运动、旋转和重连，断言 `vehicle` 与 `localization` 的源版本依赖、Frame、位置/朝向/速度一致，`odom↔base_link` 在有效采样时可查，过期/未来/跨域/无路径时拒绝。Gazebo truth 只作独立 Oracle 验证坐标方向与误差；生产状态链只接遥测。运行中 `ctl status` 能显示定位质量、来源和年龄。旧 Vehicle 回归全绿。**退出**：在线快照持续带有效定位及可追溯 Transform，故障时 fail closed；P10 记录并提交。

## 6. P11 — Environment

**目标。** 为任务提供静态/半静态的 `origin`、`home`、`geofence`、命名地点、区域和任务点，让上层引用名称与版本，不在 Mission 内散落裸坐标。Environment 是数据源，不做路径规划或发送命令。

**现状与落点。** 根仓库还没有 `environment/` 包；`WorldSnapshot.environment` 已有 `ResourceReference` 类型，但 `WorldModel.publish()` 尚不填该字段。建议 `environment/` 定义不可变资源和只读解析接口，`simulation/environments/{copter,rover}.toml` 或 YAML 存仿真场景，`world_model/service.py` 接入环境引用；`runtime/` 校验配置。配置格式、版本/加载错误必须在实施前冻结。与现有 `core/vehicle_safety.py` 的围栏边界要校验一致；Environment 的围栏信息不能替代 SafetyPolicy 的强制检查。

**实施顺序。** 明确每个位置的 Frame、坐标单位、原点来源和版本。`home` 不应无证据地写死为 `(0,0)`：可来自明确配置或飞控上报，来源变化时生成新版本。命名点解析输出带 Environment 版本的目标；任务启动时锁定使用版本，运行中配置变化应拒绝/重新预检，不能把旧任务静默指向新坐标。区域/围栏多边形或矩形按当前任务需求最小实现；安全配置与场景地图不一致时启动失败或显式阻止任务。WorldSnapshot 引用实际发布的环境版本，并记录依赖。

**测试/验收。** 配置错误、重复名称、越界点、缺失/不同 Frame、home 未知、版本热切换、重连后 origin 变化均有拒绝测试；Copter/Rover 在 Gazebo 中按命名点解析的实际坐标到达，独立 truth 确认不是测试脚本直接发裸坐标。状态查询可看到环境版本与 home 来源。**退出**：命名点和围栏在真实 P9 进程可用，版本可追溯且 Safety 保持强制，完整回归通过；P11 记录并提交。

## 7. P12 — 基础 Action

**目标。** 将已验收的车辆原语包装成可注册、可预检、可取消、可观察结果的 Action，而不让 Action 调 MAVLink。Action 读取 WorldSnapshot、显式参数和环境解析结果，只发 Typed Effect 并处理结果/退出屏障。

**建议最小目录。** Copter：`ArmAction`、`TakeoffAction`、`GotoAction`、`HoldAction`、`ReturnHomeAction`、`LandAction`、`DisarmAction`。Rover：`ArmAction`、`GotoAction`、`Hold/StopAction`、`ReturnHomeAction`、`DisarmAction`；前进/转向/速度如通用 Mission 需要，可另建带 deadman 的有限动作，不能把原始无限速度流暴露为无退出条件 Action。两车同名 Action 是否共享实现，由能力、参数和安全语义决定，不因名称相同就强行合并。

**落点与实现。** 基于 `contracts/decision.py`、`core/action_registry.py`、`core/mission_runtime.py`、现有 `core/sitl_mode_action.py` 的结果模式，在 `actions/` 或具体车辆插件中注册 `ActionSpec`、参数 Schema、能力与 Effect allowlist。Goto 参数应是 P11 的命名地点/已解析且带版本的目标；ReturnHome 必须验证 home 来源、新鲜定位及模式语义。每个动作有 deadline、成功判据、失败原因和 `exit()`；起飞/落地不能因 ACK 就完成，要看后续新鲜车辆状态，Gazebo E2E 再验证高度和接地。Hold/Stop、取消、异常退出优先走受控 Stop；失联时标 `UNKNOWN/UNCONFIRMED`，不谎称物理停车。

**测试/验收。** 离线用伪 WorldSnapshot/EffectResult 验证每个 Action 的请求、等待、成功、拒绝、超时、取消、退出；集成测试证明 Action 没有 `VehicleCommandPort`/MAVLink/Transport 依赖，所有 Effect 经 P9 桥接与双 SEND/Lease/Safety。Copter/Rover 分别执行单 Action 的 SITL/Gazebo 验收，复用原物理 Oracle 和固定门槛，不只看 ACK。**退出**：最小动作集可注册、可由 Application 调用、失败与取消安全收束，旧车辆与 P9/P10/P11 测试全绿；P12 记录并提交。

## 8. P13 — 基础 Mission：首次完整自主闭环

**目标。** 使用 P11 的命名地点和 P12 的注册 Action，在 P9 入口启动两条简单、可重复的 Mission。Mission 只编排 Action，不含 MAVLink、裸坐标、Gazebo truth 或私有端口。

**首次场景。** Copter：`Arm → Takeoff → Goto A → Hold → Goto B → ReturnHome/RTL → Land → Disarm`；Rover：`Arm → Goto A → Goto B → ReturnHome → Stop → Disarm`。具体点位须在安全围栏内并留物理余量。Mission 配置位于 `applications/`/`simulation/missions/`，经 `MissionValidator` 检查 Action 注册、参数、车辆能力、环境版本、Home/Localization 新鲜度后才运行。失败策略、取消顺序和退出屏障写入编译结果；不默认重试非幂等 Arm/Takeoff/Release。

**实现。** 复用 `core/mission.py` 和 `core/mission_runtime.py`，在 Application 任务目录中注册两条 Mission。P9 控制协议只接受这些目录名与校验过的参数；多任务并发先拒绝，避免控制权争用。每一步产出的 EffectResult 与 WorldSnapshot 反馈推动下一步；若定位/环境版本丢失、链路断开或 Safety 拒绝，任务失败/取消并安全退出，不能跳到下一步或自动恢复旧动作。

**测试/验收。** 单元测编译、能力/参数/环境版本、分支/失败/取消、幂等结果；进程级两车 E2E 必须从 `app.main ctl start --mission ...` 发起，记录完整 `Environment → WorldModel → Mission → Action → Effect → Vehicle → Gazebo → WorldModel` 时序。每个物理动作由车辆状态、独立 Gazebo truth、原固定误差/Stop 超时共同验收；任一步失败要返回非零场景结果且清理自己的进程。**退出**：两条 Mission 连续两次正常通过，至少覆盖中途取消和状态过期失败；P9–P12 回归全绿，形成“基础自主系统完成”审计与提交。

## 9. P14 — Sim Sensor / Sim Object

**目标。** 建立一个**显式仿真适配器**，从 Gazebo 中的已知对象实体生成标准 `Observation[DetectedObject]`，让 WorldModel 处理目标出现、移动、消失和过期；暂不接 Camera/YOLO。

**现状与实现。** `contracts/sensor/observation.py`、`contracts/sensor/data.py`、`world_model/service.py::ingest_observation()` 已有类型与对象新鲜度处理；`sensors/fake.py` 是离线输入。新建 `sensors/simulation/` 的只读 Gazebo 对象源，给定白名单模型名、Frame、capture/receive 时间、producer ID、sequence、quality 和仿真来源标识；转换为 Observation 后经正常 WorldModel 输入。**测试 Oracle 的 truth 订阅与 Sim Sensor 的输入必须是两个隔离角色**：Oracle 独立判定物理结果；Sim Sensor 在仿真环境中扮演可替换传感器，Mission 只能看 Observation/WorldSnapshot，不直接订阅 Gazebo。生产/硬件 profile 不能加载 Sim Sensor。

**场景与故障。** 在 Gazebo 场景放置 `target_1`、`target_2`、`target_3`，测试搜索/选择/接近所需的对象状态表达；注入漏检、延迟、重复、坐标不匹配、目标离场、同 ID 新旧版本、时钟回退和过期。对象消失时 WorldModel 不得继续把旧位置列为当前目标；多目标选择必须基于版本化观察而非硬编码模型真值。不得让 Sim Sensor 的“完美真值”掩盖质量/时间判断。

**验收。** `WorldSnapshot.objects` 记录对象、来源、Frame、时间和依赖版本；缺失/过期目标不会触发新的接近动作；Mission 层无 Gazebo API 依赖；P13 基础路线回归不退化，新增对象场景通过。P14 记录/提交后仍不声称支持真实感知。

## 10. P15 — CUADC 非视觉 Mission 迁移

**目标。** 在 P9–P14 的边界上重建可复用的 CUADC 行为链，先使用 Sim Sensor 的标准目标 Observation 跑通业务，不复制旧比赛运行时，也不接真实载荷/视觉。

**调查顺序。** 只读审查 `/home/level6/uav_ws/cuadc2026/` 和仓库归档 `legacy/cuadc_2026/` 中的 takeoff、航点、搜索、目标选择、对准、投放、返航逻辑；为每个旧模块记录输入/输出、时间/Frame、隐藏硬件调用、比赛专属规则和可复用核心。形成 `docs/autonomy/cuadc_candidate_inventory.md`，逐项决定：复用概念、重写 Action、重写 Mission、暂缓或不迁。不能改旧目录，也不从新包 import 旧代码。

**实现。** 以“起飞 → 搜索区域 → 获得目标 Observation → 选择目标 → 接近/对准 → 仿真投放 → 返航”为首条非视觉链；Rover 只复用适合其能力的搜索/目标/导航 Action。比赛坐标和任务顺序作为 `applications/cuadc/` 配置，不进入通用 Core。若要实现投放，先定义**非车辆 Typed Effect、专属受控执行端口、授权/Safety/幂等/结果合同**，只连接仿真载荷，绝不从 Mission 直接写 Servo/PWM；需改变冻结合同时按独立变更政策执行。目标选择输入只取 P14 的 Observation/WorldSnapshot，视觉缺失不能变成读 Gazebo truth 的捷径。

**测试/验收。** 旧项目仅做只读参考，不在旧树运行会生成文件的命令。离线验证任务编译、目标消失、重复目标、错误目标、对准超时、投放拒绝/重复/取消、返航失败；SITL/Gazebo 中自动执行非视觉业务链，车辆运动用独立物理 Oracle，仿真载荷用独立动作结果与世界对象状态验证。没有目标或目标过期时必须安全停止/返航或明确失败；不能把“有 ACK”当投放成功。**退出**：一条可重复业务 Mission 从正式 App 入口完整运行并留下状态/真值/Effect/载荷结果；旧源码未被修改或运行时引用，P13 回归全绿，P15 审计并提交。

## 11. P16 — 真实硬件接入与验收（当前暂缓）

**启动前置。** 这是未来独立阶段，**当前不实施、不打开物理链路**。只有用户另行明确恢复硬件工作、提供具体机型/接口与现场条件后，才编写设备专属验收表并执行。仿真里的安全策略和 `UNCONFIRMED` 语义保留，不能因 P15 通过而推断真实停车或飞行安全。

**届时计划。** 固定固件/机架/执行器/传感器/电源和链路清单；校验源时间同步、Frame 与方向、ArduPilot 参数、预解锁检查、围栏、速度/高度、操作者急停和本地失联策略。按“无执行器台架 → 限制动力/轮离地 → 场地低风险运动 → 完整任务”的独立许可和验收逐级推进；每级记录真实状态、物理运动/制动、日志、失败处置，失联物理 Stop 只有独立测量确认后才能标 CONFIRMED。真实车辆 profile 与仿真 profile 分开，默认 SEND 关闭，禁止让仿真测试参数自动进入实车。

**退出**：依具体设备的检查清单、现场日志和物理安全证据判定，不沿用 P9–P15 的仿真 PASS。真实硬件阶段未获单独启动时，进度始终写“暂缓”。

## 12. P17 — Camera / YOLO 感知替换

**目标。** 用真实图像采集和检测适配器输出与 P14 相同标准 Observation，使 P15 的 Mission/Action 无需因传感器实现改变。可以先在记录数据/仿真相机上验收；RKNN 或具体板卡只在实际设备验证后声称支持。

**实施。** 定义 Camera 帧来源、曝光/采集/接收时间、标定、Frame、目标类别、置信度、丢帧和健康；检测器插件仅产出 Observation，不执行 Mission 或车辆命令。将目标位置从图像坐标映射到任务所需空间 Frame 必须有可验证的几何/标定与质量；无法定位的目标只能作为未定位检测，不能凭标签让 Goto 发生。保留 Sim Sensor 作为可重复基线，做同一 Mission 输入边界下的替换测试。

**验收。** 离线数据与现场/仿真图像测精度、延迟、丢帧、误检、过期目标和坐标误差；业务 Mission 在视觉输入下满足相同失败/取消安全语义，并与 P14 输入实现做回归比较。无受支持设备证据时不宣称 RKNN/实机视觉完成。Planning、LLM、Agent 仍另立阶段，不能把感知完成当作自动规划完成。

## 13. 跨阶段验收矩阵与优先风险

| 证据 | P9 | P10 | P11 | P12 | P13 | P14 | P15 | P16 | P17 |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 单元/合同与错误路径 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 设备专属 | ✓ |
| 正式 App 进程与状态 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 设备专属 | ✓ |
| Copter/Rover SITL + Gazebo 物理回归 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 不替代实机 | ✓ |
| 新阶段端到端场景 | 模式任务 | 在线定位 | 命名点 | 单 Action | 双车 Mission | 对象变化 | 非视觉业务链 | 真实运动/停车 | 视觉替换 |
| 故障/取消/过期/重连 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 现场专属 | ✓ |
| 独立真实硬件证据 | — | — | — | — | — | — | — | 必需 | 按设备范围 |

主要风险及先后处理：

1. **Mission 与 Vehicle Runtime 身份不一致**：P9 必须保留 Envelope 的 Run/Action/Effect ID、TTL 与 Lease scope，不能把 Action 的 Effect 作为裸值重新提交。
2. **坐标系与版本漂移**：P10/P11 必须明确 `odom`、`base_link`、origin、home 的来源和版本；重连后不能沿用旧 Frame/目标。
3. **完成语义不足**：P12/P13 不能只凭 ACK 判动作成功；状态、真值、时间界限和退出屏障均须成立。
4. **仿真目标真值泄漏**：P14 的 Sim Sensor 是显式可替换仿真输入，测试 Oracle 是独立裁判；P15 Mission 只见 Observation。
5. **旧任务的载荷副作用**：P15 投放需要新的非车辆 Effect 和执行边界，不能继承旧代码中的直接硬件写入。
6. **硬件失联物理停车**：P16 前始终按 `UNCONFIRMED` 报告无证据停车；真实制动、失联和校准必须另验。

完成每一阶段后只更新已证实的模块进度。若 P9–P13 全部通过，可单独发布“基础自主系统仿真闭环 PASS”；这**不等于** P15 的 CUADC 业务、P16 的实机或 P17 的视觉已完成。

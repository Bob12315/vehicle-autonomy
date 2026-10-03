# P9：正式 Application Runtime 实施计划

**状态：P9 PASS，验收见 [阶段记录](autonomy/phase-9.md)。** 制定日期：2026-10-03。本文件是 P9 专项规格；P9–P17 的完整阶段计划见[基础自主系统实施计划](basic_autonomy_implementation_plan.md)。本文的创建不代表 P9 已完成。此前 [Simulation Complete 审计](simulation/completion-audit.md) 已通过，车辆基础控制层按现有仿真范围冻结。P9 只把已有能力装配成可持续运行的**本机仿真应用进程**，不增加车辆命令或真机连接。

## 1. 目标和边界

目标是让一个独立进程通过正式入口启动、连接已运行的 localhost SITL、持续读取和发布 `WorldSnapshot`、接受已注册的 Typed Mission、查询运行状态、取消任务，并安全关闭。期望使用方式：

```bash
python -m app.main run --profile copter_sim
python -m app.main ctl --profile copter_sim status
python -m app.main ctl --profile copter_sim start --mission disarmed_mode
python -m app.main ctl --profile copter_sim cancel
python -m app.main ctl --profile copter_sim shutdown
```

`rover_sim` 使用同一组命令。`run` 默认只读，双 SEND 关闭；需要发送**已注册的受限 Mission**时，进程启动者须显式传入 `--allow-send`。控制客户端不能自行开启 SEND、创建租约、提交任意 Effect、传入任意 MAVLink 指令或更改 Safety。P9 最小 Mission 只复用现有 `sitl.unarmed_mode` Action：Copter 在未解锁时请求 GUIDED，Rover 在未解锁时请求 HOLD，并以 ACK **加后续新状态**确认。两车起飞、行驶及业务 Action 属于 P12/P13，不通过 P9 CLI 暴露。

“正式”指应用生命周期、配置和用例接口成为仓库受支持的入口；**不指生产 onboard/实车验收**。本阶段只支持数值 loopback TCP、ArduPilot SITL 与本地进程控制。Gazebo 真值继续只用于测试 Oracle，不进入运行时。默认 `python -m app.main status` 的断连语义保留；运行中状态通过 `ctl status` 查询。

## 2. 当前代码事实与需解决的接口缺口

| 现有能力 | 位置 | P9 需要做的事 |
| --- | --- | --- |
| 两车周期、遥测→WorldModel、授权/Safety、唯一 writer、断链和 Stop | `deployment/simulation_runtime.py::SimulationRuntime` | 由长期运行 Application 调度；不复制控制循环 |
| 严格 Copter/Rover 仿真配置 | `runtime/simulation_profile.py`、`simulation/profiles/{copter,rover}.toml` | 增加白名单 profile 名与应用配置；保留原 Safety、时限和车辆模式映射 |
| Typed Action/Mission 与结果回流 | `core/sitl_mode_action.py`、`core/mission_runtime.py`、`core/mission.py`、`core/action_registry.py` | 为已注册 Mission 建编排器和结果桥接，避免 Application 直接发送命令 |
| Application 用例外壳 | `application/mission_service.py`、`application/service.py` | 定义运行进程的状态/启动/取消/关闭用例，避免向接口泄漏 Port/Transport |
| CLI 入口 | `app/main.py` | 新增 `run`/`ctl`，保留 `status`、`run-sitl`、`run-sitl-arm` 行为和参数 |
| 仿真验收系统 | `tests/simulation/`、`scripts/test_simulation_v1.sh` | 新增真实进程 E2E，且原 125 项及完整回归不退化 |

关键接口差异：`MissionRuntime.tick()` 产生带 Run/Action/Effect ID、期限的 `EffectEnvelope`；当前 `SimulationRuntime.submit_effect()` 会自行创建另一份 Envelope，并把整个 run 固定在 `:control:1` Action 上。后续实现**不能**直接把 Action 的 `effect` 值转交 `submit_effect()`，否则会丢失 Mission 的身份/期限/作用域。应在车辆 Runtime 增加受控的 `dispatch_envelope(envelope)` 或等价注入式适配方法：验证 envelope 属于当前 Run 和当前获授权的 Action、期限/时钟/重复 ID，再调用已有 `VehicleExecution.dispatch`；唯一写入点、Safety 和 ControlAuthority 保持不变。每个 Mission step 的 Lease 随 Action ID 显式切换；授权未开启时仍可看到拒绝结果，不能因为任务 API 存在就自动开门。

`SimulationRuntime.begin_run()` 目前可建立固定 `simulation:<uuid>:control:1` run，且 90 秒 Lease 与单 Action 作用域适合测试驱动场景，不适合假装已经支持多步骤长期 Mission。P9 需让 Mission 与车辆 Runtime 共用同一个 Run ID，并通过只读 `WorldQueryPort`/reader 向 Mission 提供快照，不能访问私有 `_world`。P9 最小 Mission 为单步受限模式任务；接口设计应允许未来 P12/P13 注册更多 Action 和逐步 Lease，但本阶段不实现通用业务任务目录。长运行进程本身不得长期持有可发送 Lease；**没有活跃任务时双 SEND 必须关闭**。

## 3. 推荐装配与职责

```text
app.main run / app.main ctl
         │ 本机控制协议（仅用例请求）
         ▼
ApplicationRuntime / ApplicationService
    ├── profile 解析、生命周期、单任务仲裁、状态查询
    ├── MissionValidator + MissionRuntime + 已注册 sitl.unarmed_mode
    └── SimulationRuntime（周期、WorldModel、Execution、Authority）
          └── Copter/Rover translator → MAVLink writer → localhost SITL
```

建议文件：`application/runtime_service.py`（用例与任务状态）、`deployment/application_runtime.py`（进程装配/调度/重连）、`runtime/application_profile.py` 或 `runtime/profiles.py`（仅两个允许的 profile 名）、`app/control.py`（本机请求协议）、`app/main.py`（CLI）。实际文件名可按现有风格调整，但要保持 Application 不导入 MAVLink/Transport/VehicleCommandPort；具体装配只能在 `deployment/` 或 `app/`，控制链不进入 `application/`。

### 生命周期状态

应用状态至少区分 `STARTING`、`CONNECTING`、`READY`、`RUNNING_TASK`、`DEGRADED`、`STOPPING`、`STOPPED`、`FAILED`。`READY` 要求有效会话和新鲜 VehicleState/WorldSnapshot，而非仅 TCP 已建立。可读状态至少包含 profile/车辆类型、进程启动时间、session ID、连接状态、WorldSnapshot 版本及年龄、车辆质量/armed/native mode、任务 ID/阶段/结果、双 SEND 当前值、最近错误。位姿/速度可作为有限的只读摘要，保留 Frame、来源和时间，不显示为比原合同更准确的“真值”。不得将 Gazebo ground truth 写入状态 API。

启动流程：验证 profile→创建 IPC 端点→构造 Runtime（不打开设备）→显式连接 loopback→以 profile 周期调用 `cycle()`→达到新鲜状态后 `READY`。SITL 未启动时保持 `CONNECTING`，按有界退避重试，状态可查询，不能 busy loop 或因瞬时连接失败自动开启 SEND。周期调度使用单一执行线程/事件循环；本机 IPC 的读写必须有消息长度和处理时限，不能阻塞 10 Hz 控制周期。启动/结束/连接/任务/错误事件输出结构化日志。

断链时让当前任务 `FAILED` 或 `UNKNOWN`（按结果语义），撤销双 SEND 和 Lease；重连必须创建新会话、新 WorldModel epoch、新任务 Run ID，不能重放旧 Effect/命令。重连恢复 `READY` 只读；任务必须由新的 `start` 请求重新提交。若 `cycle()` 超期或源时钟异常，沿用 `SimulationRuntime` 的 fail closed 路径，不在 Application 层绕过。关闭时先阻止新任务，取消现有任务/触发退出屏障，调用 `SimulationRuntime.end_run()`/`shutdown()`；超时或失联时准确报告 `UNCONFIRMED`，然后清理本进程的 IPC 端点和连接。SIGINT/SIGTERM 与 `ctl shutdown` 同一收尾路径，返回码区分正常停止与异常失败。

### 本机控制协议

优先 Unix domain socket（仅当前用户可访问，文件权限 `0600`），每请求一行有限长度 JSON，单次请求/响应包含 `request_id`、`command`、`payload`、`ok`、`error`。`ctl` 只是该协议的 CLI 客户端，不是 Web/Gateway。Socket 路径从当前用户运行目录和 profile 生成，允许显式 `--control-socket` 覆盖；已存在或归属不明的 socket 必须拒绝启动，不盲删；只清理由本进程创建、inode 相符的端点。控制消息白名单：`status`、`start`（仅已注册 Mission 名和规定参数）、`cancel`（当前任务）、`shutdown`。未知命令/额外字段/过长请求/重复启动任务均明确拒绝。没有原始 `effect`、`arm`、`takeoff`、`velocity`、`mavlink` 等通用执行入口。

进程运行状态不应只存在内存日志里：`ctl status` 在 Runtime 存活时返回机器可读 JSON；Runtime 不存在时客户端快速返回明确错误和非零 exit code。`start` 返回任务 ID 与初始阶段，最终结果通过 `status` 查看；`cancel` 返回取消是否请求成功以及尚待确认的清理状态。重复 request ID 不得启动两次任务。

### 任务状态与反馈

P9 仅注册一个**有限、可审计**的 `disarmed_mode` Mission。Copter 参数为 GUIDED/4，Rover 为 HOLD/4；参数必须从受审计 profile/注册表生成，客户端不能自报 mode ID。启动前检查新鲜 WorldSnapshot、未解锁、车辆类型、模式许可、无其他运行任务；进程未以 `--allow-send` 启动时，`start` 必须明确拒绝且不创建可发送 Run。`MissionRuntime` 发 Effect，桥接层记录 `REQUESTED`、`ACCEPTED`、`TRANSMITTED`、`ACKNOWLEDGED`、`COMPLETED` 或拒绝/未知/取消，并把 `EffectResult` 回流。任务成功要求新状态中的目标模式；ACK alone 不够。任务结束或取消后撤销 Lease 和双 SEND，但主应用继续发布状态。

明确区分应用任务状态、Mission 状态和 VehicleCommand 状态。若 Mission 在发送后被取消，不声称飞控已撤销写出的请求；若链路断开，不声称物理停止。P9 不把诊断模式任务称作一般业务 Mission。未来 P12/P13 可替换注册表和任务目录，而不改变控制协议及安全边界。

## 4. 具体执行顺序与验收门槛

后续会话按以下稳定里程碑实现并逐阶段提交；每次提交前跑相关测试，最后跑全量仿真回归。不改 `legacy/` 或 `/home/level6/uav_ws/cuadc2026/`，不连接真实串口，不自动 push。

| 顺序 | 实施内容 | 必须通过的证据 |
| --- | --- | --- |
| P9.0 基线 | 检查 `git status`、HEAD、配置与 `SimulationRuntime` 接口；复跑现有单元测试 | 记录基线与工作区状态；用户未提交内容原样保留 |
| P9.1 Runtime 桥接 | 添加保留原 ID/期限/Action scope 的 Envelope dispatch、EffectResult 回流、单步 Lease 和任务结束撤销 | 单元测试证明 Action→Envelope→Execution→唯一 writer 的 ID 一致；错误 Action、过期、重复、未授权、断链后旧 Envelope 均零写出；旧 P6/P7 测试不变 |
| P9.2 应用进程 | 装配两车 profile、调度、状态、连接重试、失联、SIGTERM/shutdown | 假时钟/假 transport 测试启动、READY、超期、断链、新会话、旧任务隔离和清理；周期不会被控制请求阻塞 |
| P9.3 CLI/本机协议 | `run`、`ctl status/start/cancel/shutdown`；安全 socket 生命周期、严谨请求校验 | CLI/IPC 测试证实默认只读、无进程错误、重复 request 不重复执行、错误/超长请求拒绝、只删自有 socket |
| P9.4 真实 SITL 验收 | Copter/Rover 各运行一次 app 进程；先只读查询，再显式 `--allow-send` 跑受限模式任务，取消/关闭/重连 | App 的 `WorldSnapshot` 连续递增且新鲜；任务 ACK+后续状态成功；取消和关闭结果如实；真实 SITL/Gazebo 与框架现有正常/故障回归无退化 |
| P9.5 文档与审计 | 更新 `README.md`、`docs/architecture.md`、`docs/v1_progress.md`，新增 P9 验收记录 | 写明命令、配置、Git SHA、日志/报告、未完成项；全量测试通过且工作区干净 |

建议的新测试：`tests/test_application_runtime.py`、`tests/test_application_control.py`、`tests/simulation/test_application_process.py`。不要写只复述实现的低价值测试；重点验证进程生命周期、结果身份链、零旁路发送、重连隔离和真实 SITL 状态。进程级测试应使用现有 `tests/simulation/launch.py` 的自有进程/端口惯例，仅杀自己的进程，保留日志与退出码。可扩充 `scripts/test_simulation_v1.sh` 纳入 P9 场景；不能因新增场景不稳定而从完整回归中静默跳过。

建议验证命令（后续实现后）：

```bash
python -m unittest discover -s tests -q
python -m app.main status
python -m app.main run --profile copter_sim          # 另一个终端，需先启动自己的 SITL/Gazebo
python -m app.main ctl --profile copter_sim status
python -m app.main ctl --profile copter_sim shutdown
./scripts/test_simulation_v1.sh
```

发送场景需要重新启动 `run --profile copter_sim --allow-send`，并以本机 SITL 的受限模式任务验证。Rover 同理。准确的 SITL/Gazebo 启动、端口分配、日志保存和清理复用 [仿真回归说明](simulation/README.md)；测试不得对同机其他进程使用宽匹配 `pkill`。

## 5. P9 完成定义

只有以下条件全部满足才能在进度文档标记 **P9 PASS**：

1. `app.main run --profile copter_sim|rover_sim` 是可持续运行、可状态查询和安全关闭的正式仿真入口；不依赖 `tests/simulation/*` 进程作为应用主进程。
2. 进程默认只读、双 SEND 关闭；无活跃任务也关闭发送；控制客户端无法绕过注册表、Action、Execution、Safety、Authority、唯一 writer。
3. 两车均能通过 Application 用例运行已注册的受限 `disarmed_mode` Typed Mission，看到完整结果链；无 ACK、旧状态、取消或断链不能报告成功。
4. 新鲜遥测与 WorldSnapshot 持续可查询；断线自动退回只读状态，新会话不得恢复旧任务或旧授权；连接未建立时状态可查询且明确错误。
5. SIGINT/SIGTERM、用户 `shutdown`、任务取消均有有界清理与准确最终结果；失联物理停止仍 `UNCONFIRMED`。
6. P9 新测试及既有全部单元测试通过，完整 Copter/Rover 仿真回归通过；日志、进程、socket、端口清理可证；完成记录包含实际命令和报告路径。

不得因为实现了 `run` 命令就宣称 P10 的 Localization/Transform 正式链、P11 Environment、P12 基础运动 Action、P13 Mission、P14 Sim Sensor、P15 CUADC 迁移或真实硬件已完成。

## 6. 后续主线（仅确定顺序，不在 P9 实施）

| 阶段 | 下一步的明确入口门槛 |
| --- | --- |
| P10 Localization + Transform + WorldModel | P9 进程内把飞控自报位姿经独立 Localization 投影与 TransformTree，发布带 Frame/时间/质量/依赖版本的 WorldSnapshot；不使用视觉，不改变原始遥测事实 |
| P11 Environment | 引入 origin、home、geofence、命名位置、静态区域/任务点的版本化资源；位置必须有 Frame 与坐标基准，WorldSnapshot 引用具体版本 |
| P12 基础 Action | 注册 Takeoff/Goto/Hold/ReturnHome/Land 等 Action；只读 Snapshot，产出 Typed Effect，不访问 MAVLink/Port；加入失败/取消/退出屏障 |
| P13 基础 Mission | Copter/Rover 各一条由 P11 命名位置组成的 Mission，在 SITL/Gazebo 形成 Environment→World→Action→Effect→Vehicle→World 的完整闭环 |
| P14 Sim Sensor | Gazebo truth 只作为明确标识的仿真 Sensor Adapter 输入，生成带来源/时间/质量的标准 Observation；与车辆控制 Oracle 分开；生产控制不能偷读 truth |
| P15 CUADC 非视觉迁移 | 只读审查旧任务，把可复用行为重写为新 Action/Mission；先用 Sim Sensor，不直接复制旧依赖或业务捷径 |
| P16 真实硬件 | 单独制定设备时间、机架/执行器、传感器质量、物理停车/失联、生产链路验收；仿真 PASS 不作实机许可 |
| P17 视觉感知 | 在标准 Observation 边界替换 Sim Sensor，实现 Camera/YOLO 后独立验收；高级 Planning/LLM/Agent 更后置 |

Fixed-wing、VTOL、Web UI、Gateway、SLAM/VIO、YOLO、LLM 和 AI Planner 在 P9–P13 仍不进入本轮实施范围。

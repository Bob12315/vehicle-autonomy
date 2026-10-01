# P6：首个持续运行组合实施计划

> **状态：P6 限定范围已实施并通过本机 SITL 验收。** 制定及验收日期：2026-10-01；原计划依据提交 `739e9f5` 的[模块进度审计](v1_progress.md)。本阶段将现有 P1–P5 能力装配为**本机 ArduCopter SITL 单进程组合**。它不关闭 P5 的整车实机验收缺口，也不声明 onboard、服务器或真实飞行支持。

## 1. 分析与范围决定

现有 [OfflineStateChain](../application/state_chain.py)能发布 WorldSnapshot，[MissionRuntime](../core/mission_runtime.py)能产生 Typed Effect，[VehicleExecution](../core/vehicle_execution.py)和 [ArduPilotSession](../vehicles/multirotor/session.py)能受控提交并观察命令；但 [CLI](../app/main.py)只提供 `status`，没有进程把这些部分持续接起来。[CopterCycleDriver](../deployment/copter_cycle.py)也须由调用方定期触发。因此，当前先做纵向运行组合，比增加新的 Perception、Planning 或 Web 模块更直接。

本计划暂定的首个组合为：**ArduCopter + MAVLink/TCP + 飞控自身状态 + World Model + 一个 Typed Mission + localhost SITL + 单进程**。实施前在 P6.0 核对实际需求并固定此范围；变更目标组合时同步调整验收项。没有外部 Sensor、地图、AI、Web 或比赛任务。验收 Mission 仅在**未解锁**状态请求一个明确允许的模式，并等待 ACK 与后续状态确认；不包含 Arm、Takeoff、Land 或运动目标。仅用 ModeEffect 测试时没有活动运动流，不能把“发送 StopMotion”写作必经步骤。

与所附建议相比，需要先解决两项实际合同问题：

1. [ActionInstance](../contracts/decision.py)目前只读取 WorldSnapshot；[MissionRuntime](../core/mission_runtime.py)产生 Effect 后没有命令回执反馈入口。只把 Effect 送入 Execution，并不能证明 Mission 在命令 ACK 或状态确认后才成功。P6 必须定义只读结果反馈和 `effect_id → command_id` 关联，禁止将 `ACCEPTED` 或 `TRANSMITTED` 算作任务成功。
2. 断链后软件无法确认车辆已停止。[当前停止语义](architecture.md)要求记录 `UNCONFIRMED`。P6 要阻断新命令、撤销旧会话并报告未确认结果；物理失联保护属于设备配置与后续整车验收。

## 2. 实施顺序与交付物

每一项在前一项的验收门槛达到后再接入下一项；可分别提交，但 P6 只有第 5 项验收通过才标记完成。

| 顺序 | 交付物 | 需要做的工作 | 完成门槛 |
| --- | --- | --- | --- |
| **P6.0 结果合同** | 只读 Effect/Command 结果视图及状态映射 | 明确 Action、Mission 或 Application 如何读取 `effect_id`、`command_id`、提交拒绝、ACK、状态完成、`UNKNOWN` 和超时；定义一次性 Effect 与重试规则，不给 Action 车辆端口。 | 测试证明拒绝/未知/未确认不会令 Mission 成功；同一 Effect 不因重试或重连重复写出。 |
| **P6.1 配置与离线装配** | 严格校验的 SITL 配置、显式组件工厂 | 配置目标机型/地址、时钟域、发布与驱动周期、TTL、deadman、SafetyLimits、允许的 Effect/Mode；组合 World Model、MissionRuntime、Execution、Session；启动时两个 SEND 均关闭。 | 缺失 Safety、错误机型、非 loopback SITL 地址、不合理周期或权限配置均在连接前拒绝；假端口可完成离线闭环。 |
| **P6.2 Application 与 Coordinator** | `start_mission`、`cancel_mission`、`get_status`、`shutdown` 用例和薄的运行协调器 | 统一接收遥测、发布快照、推进 Mission、分派 Effect、收集命令结果与处理取消；复用或拆分现有周期驱动器，不产生第二个 writer。 | 一个进程内可重复启动/查询/取消最小 Mission；应用层不持有或直接调用 VehicleCommandPort。 |
| **P6.3 周期与生命周期** | 单进程调度、状态机和结构化事件 | 处理启动、运行、停止、异常、Ctrl+C；强制周期短于 deadman，监测调度超时；按下节规则处理停止与撤权。 | 离线故障注入覆盖 stale state、Effect 过期、取消、异常、断链、重连和关闭；所有结果可追踪。 |
| **P6.4 本机 SITL 端到端** | 一条显式命令启动运行进程及可重复的 SITL 验收脚本 | 连接明确配置的 `127.0.0.1` SITL；用飞控遥测持续生成 WorldSnapshot；运行未解锁模式 Mission，经双 SEND/Lease/Safety/唯一 writer 发出命令，关联 ACK 与新状态。 | 记录 SITL 版本、命令、环境和结果；Mission 仅在观察到要求的完成事实后成功；默认关闭 SEND 的启动路径仍不写车辆命令。 |

配置的文件格式（例如 TOML 或 YAML）可在 P6.1 选定；不要把示例数字当成通用飞行限值。当前只建立 SITL profile，**不提前创建可发送的 onboard profile**。配置本身不能永久开启 SEND；每次启动由显式操作、有效 Lease、Action SEND 和 Safety 检查共同决定。首个 SITL 组合还需要在最终车辆翻译/写入边界限制为未解锁模式请求，不能只靠 Mission 名称或界面隐藏 Arm/运动命令。

**责任归属：** `runtime/` 放配置 schema 与 SITL profile；`contracts/`、`core/` 只补必要的结果语义，不引入 MAVLink；`application/` 提供 Mission 用例和只读状态接口，不持有 VehicleCommandPort；`deployment/` 的外层协调器负责实例装配、周期和设备会话；`app/` 只解析启动参数并调用装配入口；`tests/` 留下离线与 SITL 验收。外层协调器可以持有 Execution 和 Session，但所有车辆字节写入仍只经过现有 ArduPilotCommandPort。

## 3. 运行顺序与结果语义

一个周期的目标顺序为：**接收/解码 → 更新 VehicleState → 发布 WorldSnapshot → 推进 Mission → 分派新 Effect → 运行 deadman/停止检查 → 唯一 writer 出队 → 汇集 ACK/状态结果**。下一周期可继续处理前一周期的回执。若复用现有 `CopterCycleDriver`，须调整其接收、watchdog 和写入的调用边界，确保不会另开并行 RX/TX 路径。配置要约束最坏周期、读取超时与 deadman 的关系；周期延误应进入故障处理。

结果至少区分 `REQUESTED`、被 Safety/Authorization 拒绝、`ACCEPTED`、`TRANSMITTED`、`ACKNOWLEDGED`、状态观察完成、`REJECTED`、`UNKNOWN` 和取消。`ACKNOWLEDGED` 只证明飞控接受请求；模式 Action 的成功还要看到请求后新鲜的未解锁心跳/VehicleState 报告目标模式。`UNKNOWN` 不自动重试同一命令。日志应能关联 `run_id`、`action_instance_id`、`effect_id`、`command_id` 和 `link_session_id`，并记录采集/接收/发布时刻及拒绝原因。

P6 SITL 可明确使用**仅限 loopback 仿真**的接收时间代理来验证模式链路；它不能被标成飞控源端采集时间。若缺少可接受的状态时间事实，状态保持未知，Safety 拒绝依赖新鲜状态的命令。真实设备的 boot time/host monotonic 映射、时钟重启与误差上限必须单独实现和验证后，才能供真实运动 Safety 使用。

## 4. 停止、断链与退出顺序

| 触发 | 必须执行与记录的行为 |
| --- | --- |
| Mission 正常结束、取消、失败或 Ctrl+C，且链路健康 | 停止产生新 Effect，取消待执行目标；若存在活动运动流，在原 Lease、双 SEND 与链路仍有效时请求 stop/zero，并在有界期限内等待确认。然后撤销授权、关闭 SEND 和连接。未确认则如实记录，不把进程退出等同于物理停止。P6 的模式专用 Mission 无运动流，故不凭空发送 StopMotion。 |
| Transport 断开、心跳超时或写入结果未知 | 立即阻断新提交、取消/隔离旧代际及旧会话命令；活动流停止结果为 `UNCONFIRMED`。不得声称已向断开的车辆发出 stop；后续新会话需要重新授权，旧 Effect 不得重放。 |
| 状态过期、时钟域不匹配或周期超时 | 拒绝新的依赖状态命令并进入故障处理；有链路和有效授权时按活动流停止流程执行，无法确认时记录未确认。 |

真正的失联自保依赖飞控端 failsafe 与实际车辆配置；P6 的软件断链测试只能验收**阻断、隔离和准确报告**，不能替代物理停车或飞行验收。`stop_vehicle` 这类对外用例应在支持运动流时按授权与 Safety 合同设计；模式专用 P6 先提供 Mission 取消和统一关闭，不增加旁路发送接口。

## 5. 验收清单与后续边界

P6 完成时，至少留下以下可复现证据：

- [x] SITL profile 经严格 TOML 校验；SEND 默认关闭，缺少显式 Safety/Lease 时无法写入。
- [x] 一条命令启动单进程并连接**明确配置的本机 SITL**；状态持续发布且版本、时间、Frame、质量可核对。仅有心跳时 Frame 可为 `null`，不会伪造 Pose。
- [x] Typed Mission 的 Action 只发一次受限 ModeEffect；Effect 经 Execution、Authorization、Safety 和唯一 writer；Mission 等待 ACK 加目标模式状态后才成功。
- [x] Application 可启动、取消、查询并关闭任务；拒绝、超时和 `UNKNOWN` 作为不同结果呈现。
- [x] 断链、重连、旧命令隔离、状态过期、Effect 过期、周期延误及取消/关闭有离线故障测试；Ctrl+C 走同一取消/关闭路径。P4/P5 已有的活动流 stop/zero 测试持续通过。模式任务不作为运动停止测试。
- [x] 结构化日志可关联 Run、Action、Effect、Command、Session；记录配置摘要、操作者报告的 SITL 版本、测试命令及测试结果。
- [x] 根目录单元测试、离线端到端测试与本机 SITL 端到端测试通过；更新[实现边界](architecture.md)、[进度审计](v1_progress.md)和[迁移记录](migration_plan.md)。

## 6. P6 实施与验收记录（2026-10-01）

`runtime/sitl.toml` 只允许数值 loopback TCP、ArduCopter 四旋翼、单个目标模式及显式 Safety 限值；周期小于 deadman，读超时小于周期。配置不含可永久开启 SEND 的字段。`app.main run-sitl` 是显式入口，`--allow-send` 才为此 Run/Action 授予新 Lease 并开启双 SEND。`SitlModeTranslator` 在最终车辆翻译边界只接受 ModeCommand；唯一 writer 的额外写前 guard 再检查目标模式、未解锁和心跳新鲜度。Action 不持有车辆端口，只读 Effect 结果；`COMPLETED` 与同一轮新鲜未解锁目标模式 WorldSnapshot 同时成立才成功。失联、状态过期和周期延误撤权并阻止重放。取消已传输的模式命令后，同一会话不允许启动第二个模式任务，以免旧 ACK 混同；重连后需重新授权。

可复现命令：先启动本机 ArduCopter SITL TCP 5760，再执行 `tests/manual_p6_sitl.sh runtime/sitl.toml 'ArduCopter V4.8.0-dev (b5fbe265)'`。本次本机二进制内含版本字符串 `ArduCopter V4.8.0-dev (b5fbe265)`；操作者报告的版本在日志中标记为 `version_source=operator`，不是飞控遥测证明。实际运行得到单个 Effect 的 `REQUESTED → ACCEPTED → TRANSMITTED → ACKNOWLEDGED → COMPLETED`，最终 `SUCCEEDED`，WorldSnapshot 修订号 14，车辆质量 `VALID`、新鲜度 `FRESH`，未解锁。相同 SITL 上运行 `python -m app.main run-sitl`（无 `--allow-send`）得到 `system_send_disabled`、最终 `FAILED`，没有命令写入。`python -m unittest discover -s tests -q`：75 项通过；`python -m compileall -q app application contracts core deployment runtime vehicles tests` 和 `git diff --check` 通过。离线测试覆盖取消后新 Run、在途取消隔离、拒绝、未知写入、断链重连、状态过期、Effect 过期、周期延误、最终模式写入限制。没有修改归档树。

P6 **不包含**真实机体解锁/起飞、物理 stop、真实设备时间同步、onboard/server/hybrid 部署、Camera/LiDAR、Perception、复杂 Localization、Mapping、Planning、Guidance、Intelligence、Gateway、Web、固定翼或 VTOL。P6 之后先评审首个实际业务 Mission，再按它所需的输入和算法扩展。若要声明整车生产支持，仍须完成 P5 所列机架、校准、真实时间、运动、失联保护、日志和物理停止的独立设备验收。

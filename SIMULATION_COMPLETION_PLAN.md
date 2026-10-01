# Vehicle Autonomy Framework V1 — Simulation Complete 实施计划

状态：待执行。审计日期：2026-10-01。本文只规划仿真基础车辆控制；本轮未实现以下阶段，也未进行 Gazebo 运动验收。

## 0. 执行边界与完成定义

目标车辆为 ArduCopter 和 ArduPilot Rover。Rover 的最终仿真底盘必须是**左右两个主动轮、后部两个万向轮**；官方 6WD skid-steer 示例只能作为控制/插件参考，不能冒充目标底盘。控制链保持 `请求 → Typed Effect → VehicleExecution → VehicleSafetyPolicy + ControlAuthority → Vehicle plugin → MAVLink 唯一 writer → TCP transport → ArduPilot SITL → Gazebo`。反馈链保持 `Gazebo → SITL → MAVLink → state adapter → VehicleState → WorldModel`。Gazebo 真值只进入测试 Oracle，绝不进入生产控制输入。

本计划不做固定翼、VTOL、相机/YOLO、LiDAR、SLAM/VIO、RTAB-Map、深度估计、LLM/Agent、智能规划、CUADC 任务迁移、Web/Gateway、真实飞控/真实车辆/STM32/MCP4725。不得连接 `/dev/tty*` 或改变真实设备参数。本轮以及后续阶段均不得修改 `/home/level6/uav_ws/cuadc2026/`；该目录仅供只读参考，且当前存在用户未提交修改。

**Simulation Complete 的硬门槛**：

1. 一个命令从干净构建状态启动自身的 Gazebo、SITL、框架，跑两车正常场景及故障回归，清理自身进程，保留日志并给出可信退出码；连续两次全套通过。
2. 系统 SEND 和 Action SEND 默认为 false；发送必须同时具备显式授权、有效 Action Lease、匹配链路会话、未过期 Effect/Command、显式 SafetyPolicy；唯一 writer 在实际写出前再检查。未授权、过期、重复和旧会话命令均不得发出。
3. 持续采集并发布新鲜 VehicleState；状态过期、断链、时钟异常时禁止新的运动发送。断链后关闭授权、终止/隔离旧运行；重连必须建立新会话，不能重放旧命令。停止、取消、deadman、运行时关闭的结果须区分“请求/发送/确认/未知”，不能把失联时的物理停止标成已确认。
4. Copter 在 Gazebo 中实际完成连接、遥测、Arm、Disarm、Mode、Takeoff、Hold、Goto、Velocity、Stop、RTL、Land、Cancel 和结果处理；Rover 实际完成连接、状态、Arm、Disarm、Mode、前进、倒退、左右转、原地转、Stop、Cancel、持续命令 deadman。Rover Goto 是否纳入最终硬门槛按 Phase 1 的协议试验决定；若可用即必须验收，若不可用须有协议/模式证据和显式不支持测试。
5. 关键动作同时由命令结果、最新 VehicleState、独立 Gazebo 真值及超时共同判定；ACK 本身不算动作成功。全部故障矩阵自动通过，没有核心验收 `skip`/`xfail`。

## 1. 已核实基线与差异

唯一新仓库：`/home/level6/vehicle-autonomy-framework`。审计时 HEAD 为 `2dc2cd0cd995ac65d9981c1f9c413a7b97ce26f2`，工作区干净；附件所述 `f0021a93668603f4a27b6931ca0c1e188d5d994f` 为较早基线，后续从当前 HEAD 继续。`python -m unittest discover -s tests -q`：**81 tests，0 failures，0 skips**，约 0.48 秒。`python -m app.main status` 报告 `mission_scheduler=unwired`、`vehicle_connection=unwired`、`send_commands=false`。这是默认入口的安全状态；显式 P6 入口已可组成 localhost SITL 小任务，不能把默认状态解释为 P6 完全不存在。

| 能力 | 实际源码/证据 | Simulation Complete 缺口 |
| --- | --- | --- |
| 合同、状态、决策 | `contracts/`、`application/state_chain.py`、`world_model/service.py`、`core/mission_runtime.py`、`core/transform.py`；现有单元测试 | 在长期运行与真实仿真时钟下验证完整性和新鲜度；不随意改冻结合同 |
| 控制边界 | `core/vehicle_execution.py`、`core/vehicle_safety.py`、`core/control_authority.py`；`tests/test_p4_control.py` | Deadman 须由调度器持续 tick；当前 Stop 在授权失效后可能无法写出，只能报告未确认，须设计安全降级和运动停止验收 |
| P5 Copter | `vehicles/multirotor/ardupilot_commands.py`、`mavlink_port.py`、`session.py`、`mavlink_state.py`、`protocols/mavlink/codec.py` | 翻译器覆盖更多命令的存在不等于 Gazebo 飞行验证；检查模式、frame、ACK 与状态完成语义 |
| P6 入口 | `deployment/sitl_runtime.py`、`runtime/sitl.py`、`runtime/sitl.toml`、`runtime/sitl_arm.toml`、`app/main.py`；`tests/test_p6_sitl_runtime.py`、`tests/test_sitl_arm_mission.py` | 当前 `SitlRuntime.start_mission()` 固定模式或 Arm/Disarm，小范围 profile 硬编码 Copter、GUIDED 与 mode ID 4；没有可复用双车持续运行任务/重连/运动场景 |
| Rover | `vehicles/rover/diagnostic.py` 仅受限 HOLD 诊断 | 完整 translator、状态/会话装配、模式映射、运动 Safety、仿真控制均缺 |
| 验收 | P6/SITL 手工脚本和 81 个单元/局部测试 | 没有 Gazebo 独立真值 Oracle、无人值守启动器、两车物理运动与系统故障矩阵 |

环境已核实：Python 3.12.3、`pymavlink 2.4.49`、`pyserial 3.5`；`/home/level6/ardupilot` 为官方仓库本地 HEAD `b5fbe26515`，`Tools/autotest/sim_vehicle.py` 可用，`build/sitl/bin/arducopter` 已有，**`build/sitl/bin/ardurover` 尚无**。`gz sim --version` 为 **Gazebo Sim 8.15.0**；`/home/level6/gz_ws/src/ardupilot_gazebo` 本地 HEAD `3ec5142`，来源为本地 fork，`build/libArduPilotPlugin.so` 存在。已配置 `GZ_SIM_RESOURCE_PATH` 和 `GZ_SIM_SYSTEM_PLUGIN_PATH`。现有 `worlds/iris_runway.sdf` 的 world 名称是 `iris_runway`，包含 `model://iris_with_gimbal`，模型插件 `fdm_port_in=9002`；目录中没有符合目标的 Rover model/world。本次未启动 Gazebo 或做运动验收，也未验证插件加载时的 ABI/资源解析；这些是 Phase 0 的实测门槛。审计时 5760、5762、14550、14551、9002、9003 无本任务进程监听。

本机插件 README 给出 Copter 参考启动：`gz sim -v4 -r iris_runway.sdf` 和 `sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --map --console`；自动化应去掉交互 `--map/--console` 并验证版本行为。官方 [ArduPilot Gazebo 插件](https://github.com/ArduPilot/ardupilot_gazebo) 与 [SITL_Models WildThumper 指南](https://github.com/ArduPilot/SITL_Models/blob/master/Gazebo/docs/WildThumper.md) 可作为 Rover 参考；WildThumper 是 6WD，不符合目标轮组。依赖和代码版本固定到运行报告，不能只记录“已安装”。

## 2. 后续执行 Agent 的通用循环与记录格式

在仓库根目录依次执行 Phase 0→8，每阶段 `Inspect → 实现 → 单元测试 → 集成测试 → 自己启动 SITL/Gazebo → 场景 → 读取遥测和真值 → 诊断修复 → 回归 → 提交 → 下一阶段`。阶段中的文件名是建议落点，先审现有实现再新增，勿复制一份平行 Runtime。正常 build、依赖、模型、端口、启动、测试问题自行诊断修复；只在存在无法安全自主决定的外部阻断时停下。每阶段结束在 `docs/simulation/phase-N.md` 记录命令、Git SHA、依赖版本、场景配置、测试数量/结果、日志路径、剩余问题，并提交当前阶段。禁止自动 push。

每次启动前 `git status --short`，保留用户未提交内容。自有进程单独 process group 与唯一 PID/端口清单，只停止自己启动的进程，不 `pkill` 宽匹配，不重启/关机。仿真运行产物写入项目忽略的 `artifacts/simulation/<时间戳>/`，记录 `manifest.json`（Git SHA、ArduPilot/Gazebo/plugin SHA/版本、world/model、参数、端口、命令、进程、开始/结束时间和 exit codes）、stdout/stderr、事件 JSONL、MAVLink/VehicleState 摘要、Gazebo truth CSV/JSONL、断言报告。日志大小设上限并保留失败片段；不将大日志提交 Git。失败后先保存证据，再清理进程。

冻结合同（`contracts/`）原则上不动；确实无法表达必要语义时，先在阶段记录中写明阻塞、最小变更、兼容性与替代方案，补对应合同测试，**独立 commit**，再继续阶段实现。禁止因为方便改大范围合同。既有失败测试不得删除/弱化，核心验收不得 `skip`/`xfail`，不许通过放宽阈值掩盖失败。

## 3. 统一测试 Oracle 与数值门槛

新建测试侧 `tests/simulation/oracle.py`（建议）收集三路带时间戳证据：`COMMAND_ACK/CommandStatus/EffectResult`、框架发布的 `VehicleState/WorldSnapshot`、Gazebo `/world/<world>/pose/info` 或等价只读 pose/velocity topic。先用 `gz topic -l`、`gz topic -i -t ...` 确认实际 topic 和模型实体名，再固定解析规则。Gazebo SceneBroadcaster 已在 `iris_runway.sdf`，但 pose topic 的实际发布及刷新率仍需 Phase 0 验证。测试侧可用 `gz topic -e`、Gazebo transport Python/C++ 只读订阅，**不能用 Gazebo 服务移动模型或把 truth 回灌到运行时**。

启动时记录 Gazebo 初始位姿/朝向及 SITL `LOCAL_POSITION_NED` 原点，建立一次明确的 ENU↔NED、FLU↔FRD、世界↔odom 对齐；用静止与小运动校验轴向和单位。若两者偏差不能由坐标/原点解释，判失败而不改断言掩盖。采样必须是目标命令之后的新样本；时间戳用宿主单调时钟判新鲜度，另存 Gazebo sim time，暂停/加速时不得把旧 pose 当新 pose。Oracle 缺失真值或时钟逆行时失败。每个动作同时检查批准/发送/ACK（适用时）、VehicleState、新鲜真值、最大用时、最终稳态；本身无 ACK 的流式 setpoint 应按传输状态和物理响应判定，不能伪造 ACK。

Phase 1 应将阈值写入只读的场景配置并附实测基线；初始建议：Copter 起飞目标 1.5 m、稳态高度误差 ≤0.35 m、Goto 水平误差 ≤0.75 m、Stop 水平速度 ≤0.15 m/s 持续 2 s；Rover 前/后各 ≥1.0 m 且方向正确、左/右及 pivot 累积偏航 ≥45° 且方向正确、Stop 速度 ≤0.10 m/s 持续 2 s。目标场景和 Safety 允许区域须一致；单动作超时（如起飞 30 s、Goto 45 s、Stop 8 s）在 Phase 1 通过物理基线冻结，不能在失败后直接放宽。RTL/Land 检查回到 home 周围、接地高度、模式及解除武装/安全最终态（按 ArduPilot 实际行为明确），不把已接收模式请求视为完成。遥测与真值误差、超时、最终速度均进入机器可读断言报告。

## 4. Phase 0 — Repository / Environment Audit

- **Goal**：固化可复现基线并实际验证 Gazebo/SITL 最小连通性；本阶段不做框架功能改造。
- **Existing evidence**：上述 81 tests、Copter SITL 二进制、Gazebo 8.15.0 和 Iris world/plugin；Rover SITL binary/model 缺失。当前工作区干净。
- **Files/modules likely involved**：`README.md`、`docs/architecture.md`、`docs/v1_progress.md`、`docs/p6_runtime_integration_plan.md`、`runtime/sitl*.toml`、`tests/manual_p6_sitl.sh`；记录到 `docs/simulation/phase-0.md`。
- **Required implementation**：只补审计记录与可复现环境清单；核对 Python 包、SITL 参数、Gazebo 插件依赖和 ABI、world/model 资源路径、端口与现有脚本。只读查看旧 CUADC 的 Gazebo 启动用法，禁止复制其任务进程。
- **Forbidden shortcuts**：不因有 `.so` 就声称插件可用；不碰真实飞控；不改旧项目；不覆盖占用端口的外部进程。
- **Tests to add**：环境 preflight 脚本/测试只检查工具、二进制、资源解析、端口及可启动性；不将缺少 Rover 文件误报为通过。
- **Commands to run**：`git status --short`; `python -m unittest discover -s tests -q`; `python -m app.main status`; `gz sim --version`; `gz topic -l`; `ldd /home/level6/gz_ws/src/ardupilot_gazebo/build/libArduPilotPlugin.so`; `python /home/level6/ardupilot/Tools/autotest/sim_vehicle.py --help`。启动测试用自己的临时工作目录和进程组：`gz sim -s -r -v4 /home/level6/gz_ws/src/ardupilot_gazebo/worlds/iris_runway.sdf`；确认 world/pose topic 后结束自有进程。SITL 依本地 `sim_vehicle.py` 帮助选择 `--no-mavproxy --use-dir <临时目录>`，不要将构建/日志写入旧 CUADC。
- **Simulation scenario**：Iris world 启动、插件加载、SITL Copter JSON 握手、只读遥测及 truth pose 采样；不解锁。
- **Acceptance criteria**：记录真实命令/版本/port/topic/模型实体；无插件加载错误，SITL 握手和 pose 实际更新；若无法启动，保留诊断，修复后重跑。
- **Failure diagnostics**：Gazebo stderr、`ldd`、`gz topic -l`、`ss -ltnup`、SITL stdout/参数、资源路径、Gazebo server exit code。
- **Artifacts/logs produced**：`docs/simulation/phase-0.md` 与 `artifacts/simulation/<run>/` manifest、Gazebo/SITL 日志和 topic 样本。
- **Exit gate**：基线可重现、Copter 空载 Gazebo 连通、Rover 缺项明确列出；单元测试仍通过；审计文档 commit。

## 5. Phase 1 — Freeze Simulation Scope

- **Goal**：冻结两车命令/模式、运行拓扑、Safety、时钟、Oracle、场景和 DoD。
- **Existing evidence**：P6 profile 只许 Copter GUIDED/mode ID 4；`SafetyLimits` 含必需高度字段；`ArduPilotCommandTranslator` 是 Copter 子集；Rover 只诊断 HOLD。
- **Files/modules likely involved**：新增 `docs/simulation/scope-v1.md`、建议 `runtime/simulation_copter.toml`、`runtime/simulation_rover.toml`、`tests/simulation/scenarios/*.json`；若需修改 `runtime/sitl.py`，必须兼容现有 P6 入口。
- **Required implementation**：按车辆列出 effect→ArduPilot 模式/MAVLink 消息→结果完成条件；核对 Copter GUIDED/LOITER/RTL/LAND 与 Rover HOLD/GUIDED/手动或差速控制模式的**实际固件映射**，不得共享硬编码 mode ID。确定 Rover 前后/转向/pivot 采用原有 `TwistTargetEffect` 的车体 FLU 语义、流式频率与 Stop 零命令；若 ArduPilot Rover JSON/Guided 支持位置目标，则把 Goto 纳入正式场景，否则保存协议试验证据并显式拒绝。冻结 loopback TCP、单车每次运行、宿主单调时钟与 Gazebo sim time 的用途、port 分配、地理/局部坐标转换、系统+Action 授权入口、Copter/Rover 专属 Safety 数值、阈值和超时。
- **Forbidden shortcuts**：不能为 Rover 借用 Copter 模式 ID、以旧 6WD 模型满足目标、用 ACK 替代位姿判定；不能默许“可选 Goto”而不裁决。
- **Tests to add**：profile 严格校验、未知车辆/模式/帧拒绝、默认 SEND 关闭、两车配置边界与阈值一致性。
- **Commands to run**：`python -m unittest discover -s tests -q`；`python /home/level6/ardupilot/Tools/autotest/sim_vehicle.py -v Rover --list-frame=Rover`（按帮助实际语法修正）；`rg -n 'rover-skid|gazebo-iris|GUIDED|HOLD' /home/level6/ardupilot/Tools/autotest /home/level6/ardupilot/Tools/autotest/default_params`；必要时只读查阅本地固件模式定义和官方 ArduPilot 文档。
- **Simulation scenario**：用 Phase 0 的静止连通性采样，冻结初始 pose、坐标轴、truth topic 和测试命令参数；Rover Goto 先做协议可行性判定计划，完整动作留 Phase 5。
- **Acceptance criteria**：每个要求动作都有明确指令、执行条件、状态/真值判据、timeout；Rover Goto 有二元结论及证据；Safety 和时钟配置固定。
- **Failure diagnostics**：输出模式映射来源、MAVLink 消息字段、坐标样本、配置验证错误。
- **Artifacts/logs produced**：`scope-v1.md`、配置样本、命令能力矩阵和阈值版本。
- **Exit gate**：文档与测试通过并 commit；之后仅以有证据的独立变更修改阈值/范围。

## 6. Phase 2 — Vehicle Runtime Completion

- **Goal**：把现有 P6 单线程循环演进为可配置、可连续运行、可重连的双车共用编排，不改变默认断连状态。
- **Existing evidence**：`SitlRuntime.cycle()` 已执行 RX→WorldModel→Mission tick→Execution→write→结果；`start_mission()` 仍写死 mode/arm 步骤；`ArduPilotSession` 断链会清会话；`VehicleExecution.tick()` 需调用者调度。
- **Files/modules likely involved**：`deployment/sitl_runtime.py`（提取共用循环，保留 P6 外部行为）、`deployment/copter_cycle.py`、`application/mission_service.py`、`runtime/sitl.py`、`app/main.py`、`core/vehicle_execution.py`、`vehicles/multirotor/session.py`、`tests/test_p6_sitl_runtime.py`，新建通用 composition 与 `tests/test_simulation_runtime.py`。
- **Required implementation**：显式 startup/connect/warmup、profile 选择 vehicle plugin、周期 RX/state/tick/dispatch/TX/ACK/result、任务队列或标准控制输入、生命周期状态、信号/异常处理、取消与关闭。每次运动发送前查最新 state/心跳；断链立即禁用双 SEND、撤销 Lease、让流式命令终止并记录 `UNCONFIRMED`，关闭旧 socket；重连使用新 transport/codec/session，须新 run/Action 授权且不带旧队列。区分“Stop 已请求”“零速度已写”“状态/真值确认停止”；授权已失效或失联时禁止虚假补发，记录未确认，重连后只允许新的显式恢复流程。周期 deadline/写队列/ACK 超时必须可观测。保留 `app.main status` 零连接与 P6 旧入口回归。
- **Forbidden shortcuts**：Mission/Action 不直接引用 VehicleCommandPort；不在断链后复用旧 lease/session；不靠 Gazebo truth 驱动恢复；不通过延长 TTL 躲 timeout。
- **Tests to add**：fake clock/transport 的多周期状态新鲜度、单次/流式 Effect、ACK 映射、lease 轮换、重复/过期/取消、RX 异常、断线重连、旧队列隔离、deadman、关闭动作与无授权零写出。
- **Commands to run**：`python -m unittest discover -s tests -q`; `python -m app.main status`; P6 手工或自动 localhost Copter mode/arm 回归（使用自有 SITL 进程，命令见 Phase 0）。
- **Simulation scenario**：Copter 空载连接→断开框架 TCP→恢复 SITL→只读状态恢复；重连前不发旧 mode 命令；保留 P6 mode/arm 任务。
- **Acceptance criteria**：调度周期有上界，状态持续更新；重连 Session ID 改变；旧 run/lease/command 不写出；stop/取消/关闭结果准确；旧 81 tests 无退化。
- **Failure diagnostics**：周期耗时直方图、状态年龄、会话/授权代际、queue/command/effect IDs、TCP 错误、最终 effect phase。
- **Artifacts/logs produced**：运行时状态机图、配置、自动测试日志、`phase-2.md`。
- **Exit gate**：单元和 localhost 集成通过，P6 兼容，提交 runtime integration。

## 7. Phase 3 — ArduCopter Simulation Complete

- **Goal**：用 ArduCopter SITL + Gazebo 完成全部 Copter 基础动作和独立物理验收。
- **Existing evidence**：Iris world/model、已建插件、Copter SITL binary；现有 translator 支持 Arm/Disarm/Takeoff/Land/Mode/Pose/Twist/Stop 的编码，但运动未在 Gazebo 证明；`MavlinkCodec` 目前只编码 COMMAND_LONG 与 local setpoint。
- **Files/modules likely involved**：`vehicles/multirotor/ardupilot_commands.py`、`mavlink_port.py`、`mavlink_state.py`、`protocols/mavlink/codec.py`、`deployment/`、`tests/simulation/oracle.py`、`tests/simulation/test_copter.py`、`runtime/simulation_copter.toml`。
- **Required implementation**：核对 ArduCopter 固件实际 GUIDED/LOITER/RTL/LAND 模式与 ACK/状态转换；补齐基于 Typed Effect 的 Takeoff→Hold→Goto→Velocity→Stop→RTL→Land→Disarm 编排，执行取消分支。Pose/Twist ENU/FLU→MAVLink NED/FRD 的目标和反馈必须与真值对齐；Goto、流式速度、Stop 要有持续刷新/超时/结果语义。用真值 Oracle 读取 `iris_runway` 的 `iris_with_gimbal` 物理模型 pose，记录状态、模式、armed 与实际高度/速度。若该 gimbal 模型带来无关障碍，可在新项目复制并精简为纯 Iris world，记录来源/许可证及原因，不修改外部插件仓库。
- **Forbidden shortcuts**：不直接往 SITL 发测试控制命令，不用 Gazebo 位姿服务“搬运”模型，不只看 ACK，不把接受 setpoint 视为到达。
- **Tests to add**：翻译/frame/mode/ACK 状态单元测试；自动 E2E：正常完整飞行、取消时 stop/land 策略、各门控拒绝、真值缺失失败。
- **Commands to run**：`python -m unittest discover -s tests -q`; `gz sim -s -r -v4 /home/level6/gz_ws/src/ardupilot_gazebo/worlds/iris_runway.sdf`; `python /home/level6/ardupilot/Tools/autotest/sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --no-mavproxy --use-dir <本次运行目录>`；运行新框架的显式仿真 CLI/测试入口，完整命令固定到 `phase-3.md`。实际启动顺序、端口和 `sim_vehicle.py` 选项由 Phase 0 证实后写入脚本。
- **Simulation scenario**：静止→GUIDED→Arm→Takeoff 1.5 m→Hold→局部 Goto→速度段→Stop→RTL→Land→Disarm；每步采样真实高度/位移/速度及 VehicleState，另跑中途 Cancel。
- **Acceptance criteria**：全部动作在冻结超时内完成，状态/真值新鲜、误差在冻结阈值内，最终安全状态可证；独立连续两次通过。
- **Failure diagnostics**：Gazebo pose 轨迹、SITL DataFlash/console、MAVLink ACK/result、状态年龄、frame 变换中间量、prearm 报错。
- **Artifacts/logs produced**：飞行轨迹/断言 JSON、SITL/Gazebo/框架日志、`phase-3.md`。
- **Exit gate**：Copter 完整 E2E + 单元回归通过，提交 copter simulation。

## 8. Phase 4 — Rover Plugin

- **Goal**：在共用 Runtime 下新增完整 ArduPilot Rover 车辆插件及差速运动语义。
- **Existing evidence**：`vehicles/rover/diagnostic.py` 只验证 HOLD；Copter session 的 `expected_vehicle_type` 可配置但当前 composition 写死 `TYPE_QUADROTOR`；`SafetyLimits` 当前有 Copter 高度字段。
- **Files/modules likely involved**：`vehicles/rover/` 新增 translator/adapter/plugin，`vehicles/multirotor/session.py`（若抽共享 session）、`protocols/mavlink/constants.py`、`core/vehicle_safety.py`、`deployment/`、`runtime/simulation_rover.toml`、`tests/test_rover_plugin.py`。
- **Required implementation**：先在 `/home/level6/ardupilot` 执行 `./waf configure --board sitl && ./waf rover` 生成 SITL Rover binary，构建产物仅落该仓库正常 build 路径，不碰旧 CUADC。核对 Rover HEARTBEAT 类型、HOLD/GUIDED/驾驶模式 ID、MAVLink 控制消息与 skid-steer 参数 `Tools/autotest/default_params/rover-skid.parm`。给 Rover 建独立 translator/mode table、车辆能力/Safety（平面边界、线/角速度、zero altitude 或容差、帧）、操作状态/速度反馈，映射前进/倒退/左右转/pivot 为车体线速度 x 与角速度 z 的带期限流式控制；按 SITL 实测协议选择消息编码。共用 Authority、Execution、Port、Session 和 Runtime，不复刻 Copter 控制栈。未知模式/车型/帧 fail closed。若通用 Safety 接口需支持车辆专属规则，优先增加注入式策略，合同确实受阻才走独立变更政策。
- **Forbidden shortcuts**：不把 Copter mode ID 4 当 Rover GUIDED；不从 Actuator 绕过 MAVLink/Execution；不把二维速度检查取消；不修改冻结合同只为省事。
- **Tests to add**：Rover 车型筛选、模式表、速度/角速度正负号、零速度 Stop、平面 Safety、唯一 writer/授权/超时、Copter 回归、Goto 支持或显式拒绝。
- **Commands to run**：`cd /home/level6/ardupilot && ./waf configure --board sitl && ./waf rover`; `python -m unittest discover -s tests -q`; `python /home/level6/ardupilot/Tools/autotest/sim_vehicle.py -v Rover -f rover-skid --model JSON --no-mavproxy --use-dir <本次运行目录>`（模型接入在 Phase 5；先用可用的 Rover SITL JSON 测试协议）。
- **Simulation scenario**：fake transport 与 Rover SITL 内核闭环，验证 HELLO/HEARTBEAT、Arm/Disarm/HOLD/运动消息编码及反向反馈；不声称已有 Gazebo 差速运动。
- **Acceptance criteria**：Rover 插件单元/协议测试通过；能获得新鲜 Rover VehicleState，硬编码 Copter 假设已移除，所有命令经同一写入栅栏。
- **Failure diagnostics**：固件模式值、`COMMAND_ACK`、Rover HEARTBEAT 类型、输出通道/参数、translator 逐字段 dump。
- **Artifacts/logs produced**：Rover 控制映射、SITL build/version、`phase-4.md`、测试日志。
- **Exit gate**：插件与协议测试、既有测试通过，提交 rover plugin。

## 9. Phase 5 — Rover Gazebo 目标底盘

- **Goal**：建立准确的“两主动轮+后两个万向轮”Gazebo 模型，并验证 Rover 物理运动。
- **Existing evidence**：本地 ardupilot_gazebo 无 Rover model/world；官方 [WildThumper 指南](https://github.com/ArduPilot/SITL_Models/blob/master/Gazebo/docs/WildThumper.md) 使用 6WD `wildthumper_runway.sdf` + `Rover -f rover-skid --model JSON`，只可作为 ArduPilot/Gazebo 插件与 skid-steer 配置参考。
- **Files/modules likely involved**：新项目 `simulation/models/<target-rover>/model.sdf`、`simulation/worlds/rover_runway.sdf`、`simulation/params/rover.parm`、`tests/simulation/test_rover.py`、Oracle；不得改 `/home/level6/uav_ws/cuadc2026/`。
- **Required implementation**：优先获取/审阅官方 SITL_Models 的 Gazebo Rover 样例，固定来源 SHA/许可；复用必要插件/轮驱动配置，在新项目中形成目标底盘：左/右驱动轮与轮地接触、后左/右被动万向轮、质量/惯量/碰撞体、关节限位与轮轴、MAVLink JSON 插件端口；验证静态稳定、前后速度符号、左右/pivot 转向与无漂移停止。将 `rover-skid.parm` 中输出通道与模型关节绑定，避免“轮在转、车不动”。裁决 Goto：若 Rover GUIDED 支持本地/全球目标且状态/真值可验，则纳入；若不支持，留命令拒绝测试和协议证据。
- **Forbidden shortcuts**：不把官方 6WD 模型改名充数；不使用 Gazebo 控制服务推动模型；不因模型难调放宽姿态/位移门槛。
- **Tests to add**：SDF 结构检查精确 2 主动轮+2 被动 caster、资源/插件加载、轮/车体运动方向、完整 Rover E2E、禁止状态过期时运动。
- **Commands to run**：`python -m unittest discover -s tests -q`; `gz sim -s -r -v4 <仓库>/simulation/worlds/rover_runway.sdf`; `python /home/level6/ardupilot/Tools/autotest/sim_vehicle.py -v Rover -f rover-skid --model JSON --no-mavproxy --use-dir <本次运行目录>`；使用 Phase 4 的框架仿真 CLI，所有确切参数和端口在 `phase-5.md` 固定。
- **Simulation scenario**：静止→HOLD/控制模式→Arm→前进≥1 m→Stop→后退≥1 m→Stop→左转→右转→原地左/右 pivot→Stop→Disarm；若支持 Goto 增加目标到达。
- **Acceptance criteria**：模型拓扑/轮数符合目标，左右驱动和 caster 被动行为可从关节/pose 证据确认；全部动作实际位移/偏航方向、最终速度、模式/armed/超时满足冻结 Oracle；两次通过。
- **Failure diagnostics**：Gazebo SDF/物理/关节日志、Rover SERVO 输出、wheel angular velocity、模型 pose、SITL 参数 dump、轮地摩擦。
- **Artifacts/logs produced**：模型来源/许可与几何图、joint/pose 轨迹、`phase-5.md`、断言报告。
- **Exit gate**：Rover 完整 E2E + Copter 回归通过，提交 rover Gazebo。

## 10. Phase 6 — 故障注入与恢复

- **Goal**：两车完成可重复的故障矩阵；注入点位于自有 transport/clock/进程代理和测试 harness，不能伪造真值。
- **Existing evidence**：P4 有 TTL/门控/代际及 deadman 单元逻辑，P5 会话重置，P6 在断链时 fault；尚无系统级自动验证。
- **Files/modules likely involved**：`tests/simulation/faults.py`、`tests/simulation/test_faults.py`、`core/vehicle_execution.py`、`vehicles/multirotor/session.py`、`vehicles/multirotor/mavlink_port.py`、`deployment/`。
- **Required implementation**：建立 TCP 透明代理用于丢/延 RX、ACK、TX 与断连；fake clock 用于纯单元时间故障，进程管理器仅重启自有 SITL/Runtime；记录注入时刻和所有命令 ID。故障后安全行为的“物理停住”只在链路可控时承诺；失联时真实运动未可确认，必须给出 `UNKNOWN/UNCONFIRMED`，后续恢复不得重放。
- **Forbidden shortcuts**：不只测异常字符串；不把连接失败当 Stop 已成功；不复用旧授权；不关闭核心故障测试。
- **Tests to add**：下表每项分别在 Copter/Rover 适用场景执行；纯逻辑层先单元，关键断线/运动中断在 Gazebo E2E。
- **Commands to run**：`python -m unittest discover -s tests -q`; 新 `python -m unittest discover -s tests/simulation -p 'test_faults*.py' -v`（最终 harness 可替换为固定命令）；自有 Gazebo/SITL 启动命令同 Phase 3/5。
- **Simulation scenario**：各项从已 armed 的安全短距离/低速场景注入，或在 command admission 前注入；隔离测试并重置场景。
- **Acceptance criteria**：矩阵所有预期 phase、零写出、会话轮换、真值停速/未知分类由自动断言证明，且不越过围栏。
- **Failure diagnostics**：代理 RX/TX 丢包时序、会话代际、授权状态、effect/command phase、Gazebo 速度轨迹、SITL/Runtime stderr。
- **Artifacts/logs produced**：逐项 fault report JSON、失败时完整时序、`phase-6.md`。
- **Exit gate**：矩阵通过、两车正常回归仍通过，提交 fault injection。

| 故障 | 注入方式 | 预期行为与自动 Oracle |
| --- | --- | --- |
| telemetry stale | 代理停止转发位姿/心跳直至超 freshness | World/VehicleState 标旧或不可用；新运动零 TX，现有流要求停止或标未确认；检查状态年龄、TX 日志和速度/未知分类 |
| temporary disconnect | 短暂切断自有 TCP 代理再恢复 | 立即撤销 SEND/lease，旧 run 中止；新 Session ID；无旧命令重放，检查代理 TX 和 IDs |
| long disconnect | 超过 link timeout 持续断线 | Runtime fault/关闭，所有在途结果 UNKNOWN/UNCONFIRMED；未授权期间零 TX，日志明确时限 |
| reconnect | 新 TCP 连接与新 heartbeat | 新会话新授权前只读；旧队列空；显式新 run 后才允许新命令，比较会话/代际/TX |
| SITL restart | 仅重启本次 harness 创建的 SITL | 上个会话失效，状态重新 warmup；旧 Effect 不执行；新 run 可从新状态恢复 |
| Runtime restart | 运动期间结束并重启本次框架进程 | 新进程 SEND 默认 false、无旧 lease/queue；物理停止若不可证则 UNKNOWN，检查重启前后 TX/truth |
| duplicate Effect | 同 ID 同内容再次 dispatch，并试同 ID 异内容 | 同内容只对应一条命令/一次写；异内容拒绝；按 idempotency key/TX 计数 |
| expired Effect | fake clock 越过 deadline 后提交 | Safety 拒绝，零 TX，Effect REJECTED 与原因匹配 |
| unauthorized Effect | 关闭任一 SEND、无/错 Action Lease 后提交 | admission 拒绝，零 TX；所有门控组合分别断言 |
| cancelled Effect | 排队前/发送后取消 | 前者零 TX；后者不声称撤回已发送命令，终止后续流并触发有权 Stop 或报告 UNKNOWN；真值验证 |
| command timeout | 代理阻断写完成/状态达成至 deadline | Command UNKNOWN/失败，不标完成；不继续运动流；检查 deadline 和状态 |
| ACK timeout | 代理只丢目标 `COMMAND_ACK` | 不把后续状态误认作 ACK；结果 UNKNOWN 或明确定义的状态确认策略，必须有真值与日志；无盲目重试非幂等 Arm |
| deadman | 发送流式速度一次后停止 refresh | watchdog 在冻结 deadman 期限触发 Stop；检查零速度 TX、真值减速到阈值或 UNCONFIRMED |
| state timeout | 仅阻断定位/速度而保留 heartbeat | 世界状态过期，新运动零 TX；旧流按安全策略停止/未确认；验证非单靠心跳放行 |
| interrupted velocity | 流中断/写失败/周期 deadline 超时 | 不再发旧 setpoint；触发 stop 或明确 UNKNOWN；Gazebo 速度与结果分类一致 |
| shutdown during motion | 对自有 Runtime 发 SIGTERM/正常 shutdown | 双 SEND 撤销，尝试有界 Stop/安全收尾并等待确认；超时则 UNKNOWN，不留下自有框架进程；真值留证 |
| old replay after reconnect | 断链前队列放入未发送 command，再重连 | 旧 command ID、lease、session 全部无 TX；新会话必须新 Effect |
| stale-state motion block | 造过期/未来/异域 VehicleState 与新 Effect | Safety 拒绝运动，发送计数不增，原因与时间域匹配 |

## 11. Phase 7 — 单命令回归自动化

- **Goal**：提供 `./scripts/test_simulation_v1.sh` 一键可重现的完整验收。
- **Existing evidence**：现有 `tests/manual_p6_sitl.sh` 需外部 SITL，不能覆盖双车、Gazebo、真值或故障清理。
- **Files/modules likely involved**：`scripts/test_simulation_v1.sh`、`tests/simulation/harness.py`、环境/配置清单、`.gitignore`、`docs/simulation/README.md`。
- **Required implementation**：preflight 工具/版本/二进制/端口，给每轮隔离工作目录与端口；自建 Gazebo、SITL、Runtime 与只读 Oracle，等待显式 readiness（world、plugin、SITL heartbeat、fresh state、truth），运行单元→Copter→Rover→故障矩阵→汇总；用 process group/trap 清理自己的进程，保存失败日志/exit codes。端口被外部占用时选空闲端口并把 Gazebo/SITL/框架参数一起改，不能杀外部进程。支持 headless CI `gz sim -s`，检测没有 GPU 时不依赖 GUI；设置总/分场景 timeout。失败不得进入绿色总结。
- **Forbidden shortcuts**：不跳过失败场景；不以 sleep 固定秒数代替 readiness；不删除日志；不 kill 其他用户进程；不自动 push。
- **Tests to add**：harness 的成功、故意失败、超时、端口冲突、Ctrl-C/信号清理、重复执行测试。
- **Commands to run**：`./scripts/test_simulation_v1.sh`; 再运行一次；`git status --short`; `ss -ltnup` 验证自有端口释放。
- **Simulation scenario**：两轮完整双车 normal + fault suite，第二轮从全新运行目录启动。
- **Acceptance criteria**：两次 0 exit，报告场景数/失败数/跳过数（核心 skip=0），资源释放，失败注入能让脚本返回非 0。
- **Failure diagnostics**：manifest、每进程 stderr、ready 阶段、最后状态/真值、端口/PID 清单。
- **Artifacts/logs produced**：两个独立 `artifacts/simulation/<run>/`、摘要 JSON、`phase-7.md`。
- **Exit gate**：一键回归可重复，提交 regression automation。

## 12. Phase 8 — Simulation Complete Audit

- **Goal**：按证据审计而非文件数量判定整个车辆仿真部分是否完成。
- **Existing evidence**：Phase 0–7 的 Git commits、manifest、场景报告、故障矩阵及两次完整回归。
- **Files/modules likely involved**：`docs/v1_progress.md`、`docs/architecture.md`、新增 `docs/simulation/completion-audit.md`、本计划状态；不改未相关模块进度。
- **Required implementation**：逐项核对第 0 节 DoD、支持/不支持能力矩阵、Copter/Rover 正常/故障结果、真值偏差、进程/资源清理、已知限制、真实硬件边界；检查 Git diff、合同变更独立提交及许可证记录。若任何核心验收失败，状态保持未完成，回相应 Phase 修复重跑。
- **Forbidden shortcuts**：不把接口/占位包算作实机/服务器/RKNN 支持；不因 81 单元测试绿色就称仿真完成；不以手工视频代替自动真值。
- **Tests to add**：必要时补缺失的证据检查，不新增无意义同构测试。
- **Commands to run**：`./scripts/test_simulation_v1.sh`（最终审计再跑）；`python -m unittest discover -s tests -q`; `git status --short`; `git log --oneline -10`；校验两车报告及无 core skip。
- **Simulation scenario**：最终干净启动的完整 Copter/Rover/fault 回归。
- **Acceptance criteria**：所有 DoD 对应具体场景报告和 commit；不支持项明确；工作区干净；不触碰真实设备与旧 CUADC。
- **Failure diagnostics**：列出失败项→证据→负责 Phase→修复/重测链接，不能给无证据的完成比例。
- **Artifacts/logs produced**：`completion-audit.md`、最后 manifest/测试报告、更新后的进度文档。
- **Exit gate**：证据完整才标记 `Simulation Complete` 并提交审计；仍不得自动 push。

## 13. 优先风险与处理顺序

1. **Rover 模型差距**：本地无 Rover model，官方 WildThumper 为 6WD。先用官方配置思路验证协议，再在新项目实现并核实目标 2+2 底盘。
2. **运动与停止的真实语义**：P4 Stop 依赖授权和写出条件；失联时任何软件结果都不能保证物理停止。先在 Phase 2 固化 `UNCONFIRMED` 与恢复策略，Phase 3/5 用真值证实可控条件下停车。
3. **MAVLink 命令完成语义**：P5/P6 主要验过 Mode/Arm；流式 setpoint、RTL、Goto 和 Rover 模式需要分别核实固件接受、状态反馈与物理结果。
4. **坐标/时钟对齐**：SITL NED 与 Gazebo ENU、世界与局部原点、接收时间代理和仿真时间容易造成假阳性；Oracle 和控制帧必须独立校验。
5. **本机环境版本/端口**：插件是本地 fork 的已编译 `.so`，Copter 可执行已有而 Rover 缺失；必须先完成 Phase 0 实际加载和 Phase 4 Rover 编译，所有版本/端口写入 manifest。

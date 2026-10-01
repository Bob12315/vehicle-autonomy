# Vehicle Autonomy Framework

Vehicle Autonomy Framework 是面向多旋翼、无人车、固定翼、VTOL 及未来自主移动平台的**可复用自主系统框架**。它通过合同、插件和受控执行边界组合 Vehicle、Sensor、Perception、World Model、Mission、Action、Intelligence、Protocol、Transport 与 Deployment。通用 Core 不绑定特定比赛、机型、飞控、计算板或感知模型。

完整的职责、数据流、依赖规则和目标包归属见 [V1 目标架构](docs/framework_v1.md)；时间、坐标、状态、Effect 和端口的冻结语义见 [V1 基础合同冻结规范](docs/foundation_contracts_v1.md)。这两份文档描述设计目标，不代表其中的组件已由当前代码实现。

## 当前实现

根目录目前提供 P1 基础合同、P2 离线 World Model 状态链、P3 Typed Action/Mission 决策链、P4 控制边界、P5 ArduCopter/MAVLink/TCP 插件，以及 P6 本机 SITL 单进程模式任务运行组合。通用 TransformTree 求解静态/动态 Frame 关系。P5 已在内存传输、本机 Copter SITL 和已连接 Copter 飞控的受限 USB 模式诊断中验证；此前还完成 Rover 飞控的受限 USB HOLD 诊断。P6 将 Effect 经双 SEND、Lease、Safety 和唯一 writer 分派，并等待 ACK 与后续模式状态。**尚无**经过整车实机验收的生产车辆连接、Web UI、相机进程或服务器部署。

车辆基础仿真新增了共享 `SimulationRuntime`、完整 Rover 插件和两主动轮/两后万向轮模型。Copter、Rover 正常动作与故障场景已通过四轮完整回归；**本轮基础车辆控制 Simulation Complete：PASS**，见[审计记录](docs/simulation/completion-audit.md)。

一键构建、启动、真值验收、故障测试和清理：

```bash
./scripts/test_simulation_v1.sh
```

环境与报告位置见[仿真说明](docs/simulation/README.md)。这仅覆盖 localhost SITL + Gazebo；真实飞控和整车仍未验收。

P6 的 localhost SITL 范围已完成；**当前暂缓真实飞控接入**。P5 整车实机验收仍是未完成项，后续软件工作按[模块进度文档](docs/v1_progress.md#5-p6-完成后的工作范围)推进。

车辆发送默认关闭。P5 命令端口在唯一字节写入点前重新检查系统 SEND、Action SEND、Lease、代际、会话和期限；断链时停止结果保持未确认。TCP/串口连接只能由调用方显式创建；显式 `run-sitl`/`run-sitl-arm` 和受控仿真脚本装配 localhost TCP 与专用 Safety，默认入口不连接车辆。旧演示网关仍使用旧 Effect 测试端口，不能据此宣称已支持实机飞行。

```bash
python -m app.main status
python -m unittest discover -s tests -v
```

P6 的配置为 [runtime/sitl.toml](runtime/sitl.toml)，仅接受数值 loopback 地址和 ArduCopter 四旋翼。先单独启动本机 ArduCopter SITL 的 TCP 5760 端口，再运行 `python -m app.main run-sitl --config runtime/sitl.toml --allow-send`。省略 `--allow-send` 会连接并发布状态，但 ModeEffect 被授权边界拒绝，且不会写出车辆命令。可用 `tests/manual_p6_sitl.sh runtime/sitl.toml '<SITL 版本>'` 验收 ACK 与新心跳状态；版本参数由操作者报告，日志标明来源。P6 只请求一次未解锁 `GUIDED` 模式，不发解锁、起飞、运动或 StopMotion。

另有独立的 **SITL 解锁验收任务**：`python -m app.main run-sitl-arm --allow-send --allow-arm` 使用 [解锁专用 profile](runtime/sitl_arm.toml)，依次确认 `GUIDED`、Arm 和 Disarm，最终回到未解锁。全新本机 SITL 的验证命令、拒绝记录、取消及未知结果边界见 [SITL 解锁任务验收](docs/sitl_arm_mission.md)。该入口只允许 loopback SITL；不提供起飞或运动命令。

ArduCopter 插件使用 [requirements-p5.txt](requirements-p5.txt) 中的可选依赖。本机 SITL 验证需先自行启动 ArduCopter 的 TCP 5760 端口，再显式运行 `PYTHONPATH=. python tests/manual_p5_sitl.py --allow-send`；脚本仅连接 `127.0.0.1`，确认未解锁后请求 `GUIDED` 模式并等待 ACK。它不会执行起飞或实机连接。

USB 飞控诊断须显式运行 `PYTHONPATH=. python tests/manual_p5_rover_usb.py --port /dev/ttyACM0 --allow-send`（实际设备路径可用 `/dev/serial/by-id/...`）。脚本仅接受 ArduPilot Rover 心跳，要求飞控已处于未解锁的 HOLD 模式，经过同一 Execution/双 SEND/Safety/唯一 writer 链发送一次 HOLD 请求，并等待 ACK 与后续状态。该诊断不提供解锁、运动或参数修改能力；这不等于 Copter 实机或整车运动验收。

Copter USB 诊断使用 `PYTHONPATH=. python tests/manual_p5_copter_usb.py --port /dev/ttyACM1 --allow-send`（连接路径可能改变，优先使用对应 `/dev/serial/by-id/...`）。脚本仅接受 ArduPilot 四旋翼心跳，要求飞控未解锁且已在 STABILIZE 模式，只发送一次 STABILIZE 同模式请求并检查 ACK 与后续状态。它不提供解锁或运动请求；USB 控制器通过不等于整车飞行或停止验收。

当前裸飞控的 `FRAME_CLASS=0`（未定义），持续报告机架类别/类型预解锁错误。机架参数须按实际装配选择，且改变后需重启；目前未为裸飞控指定一个假定机架，也未关闭预解锁检查。USB 遥测检查见[迁移记录](docs/migration_plan.md)。

裸飞控台架曾临时配置 `FRAME_CLASS=1`、保留 `FRAME_TYPE=1`（四旋翼 X）并重启。通过受控端口验证未解锁的 `STABILIZE → ACRO → STABILIZE`；Arm 请求由飞控预解锁检查拒绝，随后 Disarm 请求获确认。测试结束已恢复 `FRAME_CLASS=0` 并重启复核。复现台架脚本须分别显式运行 `PYTHONPATH=. python tests/manual_p5_copter_bench_mode.py --port /dev/ttyACM0 --allow-mode-roundtrip` 与 `PYTHONPATH=. python tests/manual_p5_copter_bench_arm.py --port /dev/ttyACM0 --bare-controller --allow-arm-bench`；路径随重新连接可能变化，**Arm 脚本仅供确认没有执行器连接的裸飞控使用**。预解锁阻断、日志存储错误和未验收项见[迁移记录](docs/migration_plan.md)。

[当前实现边界](docs/architecture.md)记录已有能力与限制。[迁移计划与记录](docs/migration_plan.md)给出从合同、状态链到控制与设备接入的阶段顺序。[历史程序说明](docs/migration.md)介绍 `legacy/cuadc_2026/`：它完整保存旧应用的代码、配置、测试和资源，供后续逐项评估复用；新根目录不导入该目录。

[V1 模块进度与未完成项](docs/v1_progress.md)按目标架构逐项记录当前成熟度、证据与待验收工作。

[P6 首个持续运行组合实施计划与验收](docs/p6_runtime_integration_plan.md)记录 localhost ArduCopter SITL 的装配顺序、测试结果和未覆盖范围。

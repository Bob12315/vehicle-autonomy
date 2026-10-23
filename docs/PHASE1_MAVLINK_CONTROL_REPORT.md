# Phase 1 — MAVLink / ArduPilot 基础控制验收报告

**结论：Phase 1 PASS。** 两次独立运行中，Rover 与 Copter 均完成真实 ArduPilot SITL + Gazebo 的 A–F 门槛；350 项单元测试通过，无失败、无错误、无跳过。仅完成阶段一，未开始阶段二。

## 开发与架构

- V1.1 改造记录统一放在 [v1.1/](v1.1/README.md)，用户原始任务完整保存在 [phase1-task.md](v1.1/phase1-task.md)。
- 复用现有 MAVLink2/pymavlink、Session、Execution、Authority、Safety、唯一 Writer、Rover/Copter 翻译器、源时钟和物理验收场景，没有重写协议栈或运动控制器。
- contracts.vehicle 新增可选遥测合同；VehicleStateSnapshot 的遥测生产者使用 schema 1.1，旧位置参数和字段兼容。vehicles.ardupilot 提供标准化与动态新鲜度查询，app 只作显式装配。仍为七模块结构，无新顶层 adapters/capabilities。
- 遥测覆盖 HEARTBEAT、ATTITUDE、GLOBAL_POSITION_INT、LOCAL_POSITION_NED、GPS_RAW_INT、EKF_STATUS_REPORT、SYS_STATUS、POWER_STATUS、COMMAND_ACK、STATUSTEXT。每字段保留来源/会话、收发时间、坐标、质量、可用性和重复/倒序/无效计数。
- 未带可靠采样时间的消息保持 captured_at=null；新接收不伪装成新采样；缺失/过期/无效明确报告。告警保留 id/chunk_seq，不伪造完整多分块告警。新连接清空旧遥测与 ACK 状态。
- 修复 ACK 目标控制器核对，以及 ACK 栅栏后队列项到期仍留队的问题。迟到 ACK 保持 UNKNOWN，并阻止同会话内同类命令自动重放。
- 仿真 Copter 增加 MAV1_EXTRA3=2，打开既有 EKF 遥测流；未更改任何安全或运动参数。新增独立验收入口、原始报文代理记录、写入观测、两轮汇总及二进制/插件 SHA256。
- 关键文件：`contracts/vehicle/{models,telemetry}.py`，`vehicles/ardupilot/{telemetry_state,telemetry_monitor,coordinates,session,command_port}.py`，`vehicles/ardupilot/mavlink/telemetry.py`，`app/bootstrap/simulation_runtime.py`；测试为 `tests/test_phase1_telemetry.py`、`tests/test_p5_mavlink.py`、`tests/simulation/phase1_{probe,harness}.py`、`faults.py`、`launch.py`。详见 [增量合同](v1.1/phase1-telemetry-contract.md)。

## 环境与复现

- 开发起点 `7444885`；正式验收代码提交 `371ab0c88bf6c2422c08cdf77fbf650ce0269a13`；启动时工作区干净。两轮运行前后源码 SHA256 相同：`8c773a532f9ad80a12d6dffc3c475e2ea2c923db2d95579ef0b963b1e7062785`。
- Python：`3.12.3 (main, Jul 15 2026, 23:46:41) [GCC 13.3.0]`；pymavlink 2.4.49、pyserial 3.5。
- ArduPilot：`b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`，实际二进制内标识 ArduRover/ArduCopter V4.8.0-dev；Gazebo Sim 8.15.0；插件源码 `3ec51428fd43deb7b71137192ba16394b450d78e`。
- 复用 `/home/level6/ardupilot/build/sitl/bin/{ardurover,arducopter}` 与 `/home/level6/gz_ws/src/ardupilot_gazebo/build/libArduPilotPlugin.so`；未修改这些外部源码、模型或已有未跟踪文件。每个 manifest 含实际二进制与插件 SHA256。
- Rover 使用本项目 target_rover 模型 / rover_runway；Copter 使用原有 iris_with_gimbal / iris_runway。profile 为 simulation/profiles/{rover,copter}.toml，参数及生成 world/model 均存入 manifest 和独立目录。

```bash
# 使用已安装项目及 MAVLink/Gazebo 依赖的 Python 环境
PATH="$PWD/.venv-migration/bin:$PATH" ./scripts/test_phase1_control.sh --allow-send
```

本次实际指定 `--run-dir artifacts/phase1-control/acceptance-final`，该目录保留原始证据；复跑使用上面命令自动生成新目录。入口要求全新目录，默认生成唯一 run ID；两轮各为两类车执行 probe、physical、faults，共 12 个真实仿真场景。先预检及单元测试，所有场景均收集结果，不静默跳过；退出码与机器汇总一致。缺少 --allow-send 会拒绝启动。故意指定不存在二进制的负向测试返回 1，报告位于 `artifacts/phase1-control/preflight-failure-proof/`，未启动车辆进程。

## 两次独立 A–F 验收

| 门槛 | Rover 第一次 | Rover 第二次 | Copter 第一次 | Copter 第二次 | 判定依据 |
| --- | --- | --- | --- | --- | --- |
| A | PASS | PASS | PASS | PASS | 真实心跳、ID/车型、唯一会话与持续接收；只读阶段命令写入为 0 |
| B | PASS | PASS | PASS | PASS | 姿态/位置/速度、时间与坐标、EKF/供电/告警、缺失与过期状态；独立 Gazebo 真值 |
| C | PASS | PASS | PASS | PASS | 正式 Execution → 车型翻译器 → 唯一 Writer；ACK 与后续状态分离，运动另验 Gazebo 真值 |
| D | PASS | PASS | PASS | PASS | 默认 SEND、Action SEND、缺失/错误 Lease、过期命令/状态、非法 Frame、不支持能力、错误会话：9 类实际写入均为 0 |
| E | PASS | PASS | PASS | PASS | 真实断链、心跳超时、遥测延迟/重复、迟到 ACK、SITL 重启、旧队列隔离、Cancel/Stop 不确定性 |
| F | PASS | PASS | PASS | PASS | 持续接收、重复连接与关闭、两轮独立场景、Socket/线程/进程/端口清理与无会话污染 |

| 量化证据 | Rover 第一次 | Rover 第二次 | Copter 第一次 | Copter 第二次 |
| --- | --- | --- | --- | --- |
| 首次只读阶段心跳数量 | 45 | 45 | 41 | 41 |
| 归一化 yaw 真值误差 / rad | 7.55e-08 | 7.55e-08 | 2.22e-16 | 2.22e-16 |
| 归一化速度真值误差 / m/s | 4.57e-08 | 4.57e-08 | 5.76e-06 | 5.76e-06 |
| 位置目标 Gazebo 误差 / m（≤0.75） | 0.487 | 0.510 | 0.117 | 0.130 |
| 位置目标状态误差 / m（≤0.75） | 0.520 | 0.547 | 0.137 | 0.145 |
| 起飞真值增高 / m（目标1.5，误差≤0.35） | 不适用 | 不适用 | 1.495 | 1.495 |
| 9 类拒绝实际写入次数 | 0 | 0 | 0 | 0 |
| 重连探针不同 session 数 | 5 | 5 | 5 | 5 |
| 迟到 ACK 最终状态 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| SITL 重启旧队列写入次数 | 0 | 0 | 0 | 0 |

原有 takeoff、goto、速度/转角、Stop 稳定时长和故障阈值均沿用 `simulation/scenarios/acceptance-v1.json`，该文件与 7444885 完全相同。Rover/Copter 所有运动结果均由 Gazebo 只读 oracle 独立判定；ACK 或目标状态不能替代物理结果。逐项位移、转角、起飞/降落及停车速度/时间见原始 physical/summary.json 和 [机器证据索引](v1.1/phase1-evidence.json)。

## 证据与清理

- 正式入口：`artifacts/phase1-control/acceptance-final/summary.json`、`stages.json`、`unit.json`；开始 `2026-10-23T03:28:25.597726+00:00`，结束 `2026-10-23T03:53:20.804500+00:00`。
- 独立运行 `run-1-29db89c3`：该目录的 `summary.json` 汇总两类车；每车的 `*-probe`、`*-physical`、`*-faults` 含原始 `summary.json`、`manifest.json`、SITL/Gazebo 日志、runtime/trajectory/observations/proxy/telemetry JSONL。
- 独立运行 `run-2-0ad45180`：该目录的 `summary.json` 汇总两类车；每车的 `*-probe`、`*-physical`、`*-faults` 含原始 `summary.json`、`manifest.json`、SITL/Gazebo 日志、runtime/trajectory/observations/proxy/telemetry JSONL。
- 12 个场景均正常结束；12 份车辆 manifest 记录的 36 个仿真子进程及 14 个验收阶段进程已退出，各 manifest 的 `ports_released=true`、`remaining_process_groups=[]`；三次重连的旧运行时 Socket 均已关闭，代理线程 join 完成、端口释放。
- 补充终检覆盖含调试运行在内的全部 16 份 manifest、44 个仿真进程，以及 TCP/JSON UDP/RC UDP 端口，均已清理；见 `artifacts/phase1-control/final-resource-audit.json`。
- `phase1-evidence.json` 保存各门槛数字、全部场景路径、进程身份和原始证据的 SHA256；原始大日志保存在本机 artifacts（Git 忽略），不以摘要替换或删除。

## 安全审计

- 默认 CLI 显示 send_commands=false、vehicle_connection=unwired；硬件检查为 hardware_readonly、双 SEND=false；hardware_controlled 的既有拒绝测试继续通过。
- Authority、Execution、两类 SafetyPolicy、动作/任务/运动翻译逻辑与基线逐字节一致。写入点继续在同一 authority lock 下重检双 SEND、Lease、代际、Session、TTL 与动态写前 guard。
- 所有测试目标由 OwnedSimulation 新建，只连接本轮已拥有的 127.0.0.1 SITL/透明代理端口；不扫描或打开 /dev 串口，不向真实设备发送控制。测试未绕过 Execution 发送控制命令；D 组白盒故障只修改 Execution 已准备的队列身份或输入快照，验证最终 Writer 会拒绝。
- COMMAND_LONG 的模式/解锁/上锁使用实际 ACK 和后续心跳确认；流式 SET_POSITION_TARGET_LOCAL_NED 本身没有 ACK，保持 TRANSMITTED，另由 Gazebo 真值验证效果。状态严格区分 ACCEPTED、TRANSMITTED、ACKNOWLEDGED、后续状态 COMPLETED、独立物理验证；延迟 ACK 后 UNKNOWN 不升级，物理 Stop 无法确认时保持 UNCONFIRMED。MAVLink ACK 没有请求 UUID，超时后的同命令协议号在当前会话内保持歧义栅栏，不自动重试。

## 已知失败与范围限制

- 本阶段最终强制门槛没有失败、阻塞或跳过。调试失败保留：`dev-rover-probe/` 在 active run 中冻结遥测而触发原有过期保护；测试改为在空闲只读状态检查重复样本的诊断过期，运行中的真实过期保护仍由 fault_scenario 验证。`dev-copter-probe/` 暴露默认未发布 EKF；通过仅打开本项目 MAV1_EXTRA3 遥测流修复。
- 350 项单元测试从 342 项基线增加 8 项；没有删除测试、放宽断言或修改安全阈值。特殊非法/非有限/倒序输入使用单元测试补充，真实强制场景没有用 Mock 替代。
- 历史迁移 21 场景中的两个 Copter Application oracle 启动失败、P26 Nav2 导航越轨/定位新鲜度失败仍保留在原报告/证据中；不属于本阶段 PASS，也没有修复或重新认证它们。见 [迁移报告](ARCHITECTURE_MIGRATION_REPORT.md)、[硬件审计](HARDWARE_READY_AUDIT.md)。
- 仅限定 localhost SITL/Gazebo。未做实机/ARM64 控制安全验收；未开发 Plane 专属控制、新感知/SLAM/Nav2/LLM/VLM、并行 Mission、新 Action 业务或 Web 编辑器。阶段二须用户明确批准。

## Git 阶段提交

- `5e6fd2c`：V1.1 目录、原始任务及基线审计（342 项基线通过）。
- `8d2ecde`：统一遥测、协议边界修复与单元回归（350 项通过）。
- `371ab0c`：供电/EKF 遥测、专用入口和两次验收实现；正式两轮均基于此提交，启动时工作区干净。
- 本报告与证据索引为最后文档阶段提交；准确 SHA 可由 `git log -1 --format=%H -- docs/PHASE1_MAVLINK_CONTROL_REPORT.md` 获取。最终答复给出该 SHA 和最终工作区状态。

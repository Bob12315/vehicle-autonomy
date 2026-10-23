# Phase 1 独立审查缺陷修复报告

**状态：READY FOR RE-AUDIT。** 开发侧确定性边界测试及两轮完整 Rover/Copter SITL + Gazebo A–F 验证均通过，等待用户安排独立审查。本文不宣布最终 Phase 1 验收通过；未开展 Phase 2。

## 基线与历史证据

- 起点 `6833e4b8e4b23609bf8dbfc9efe84964e410e153`，开始时工作区干净；修复分支 `fix/phase1-review-remediation`。已阅读两份架构基线、AGENTS、README、现有报告及相关源码/测试。
- 用户通知独立审查结论为 FAIL；本轮在旧源码上再次实际复现缺陷。原 [Phase 1 开发侧报告](PHASE1_MAVLINK_CONTROL_REPORT.md)、原机器索引及 143 份原始验收文件均按 SHA256 核对未变，没有将旧 PASS/FAIL 改写。
- 全部新证据放在 `artifacts/phase1-remediation/`，与 `artifacts/phase1-control/` 分开。
- 原始基线 350 项单元测试通过；修复后 365 项通过、0 失败、0 错误、0 跳过。新增 14 个 Writer/协议边界用例及 1 个代理证据用例，保留全部原有断言。

## 四个问题的根因与修改

| 问题 | 根因 | 修改 |
| --- | --- | --- |
| P1：旧 ACK/HB 错误完成 Disarm | 按 MAV_CMD 400 找到当前 in-flight 请求；ACK 无 Arm/Disarm 参数回显或请求 UUID，旧未解锁 HB 又按新接收时间成为完成依据 | Session 用带源时间的报文锚定接收窗口，无时间戳回复不推进锚点；重复、乱序、歧义区间丢弃。ACK 明确记录 `unproven_mav_cmd_only`。完成需发送后两份不同源时间上下文的有效目标 HB，单份状态变化不替换已确认 operation；状态确认不足则 UNKNOWN |
| P1：过期命令仍被 Writer 写出 | caller now 在等锁前取得；Guard 运行后沿用旧值，且异常未被安全处理 | 锁内重新读单调时间；Guard/编码后、write 前再次读时间，重检双 SEND、Lease、Session、Generation、期限及 Guard 事实有效期。异常、非法返回、超预算均拒绝。校验与调用保持同一 Authority 临界区 |
| P2-A：代理字段与真实转发不一致 | repeat_pose 替换 raw 后仍从原 message 提取 payload/sequence，且没有完整表示被替换报文的丢弃 | rx 记录实际输入，rx_forward 记录实际发送字节并重新解析字段；rx_discard 记录替换/过滤/断连丢弃，explicit_replay 标识原样重放。延迟/持有队列按连接 epoch 隔离；转发行为不变 |
| P2-B：发送序号始终为 0、排队顺序不对应 | pymavlink message.pack 不推进发送者 seq；submit 时预编码也不对应最终 Writer 顺序 | standalone encode 递增并模 256 回绕；Writer 延迟编码，在最终校验后、真实 write 尝试前提交序号。取消、拒绝、编码失败不占号，部分/失败写占一次尝试并锁住后续发送；新连接 Codec 从 0 开始 |

关键生产文件为 `vehicles/ardupilot/{session,command_port,telemetry_state}.py`、`mavlink/codec.py`、`transports/bytes.py`、`app/bootstrap/{simulation_runtime,sitl_runtime}.py`。没有改 Action/Mission/控制原理、Authority/Execution/SafetyPolicy 或七模块架构。新增测试入口复用原脚本的 `--remediation` 选项。

部分旧内存夹具一直以 seq=0 打包，另有夹具的编码顺序与转发顺序不同。现用 `tests/mavlink_fixture.py` 生成真实递增序号和源时间证据，修正实际送入顺序；没有删测试、降低物理误差/安全/超时门槛或改断言来获取通过。

## 确定性修复前后对照

| 场景 | 原始 6833e4b | 修复后证据 |
| --- | --- | --- |
| Arm 完成后 Disarm，重放旧 Arm ACK 与未解锁 HB | 错误 COMPLETED；回归断言失败 | 不完成，已确认 operation 仍为 armed；合法新 ACK/两份状态随后可完成 |
| 等 Authority 锁时过期 | 发生一次实际写入 | 实际调用及发送帧为 0，REJECTED；新有效命令仍可发送 |
| Guard 内过期、Lease 到期、Guard 异常/非法值/超预算/授权变化 | 过期场景写入；异常向外逃逸 | 实际调用及发送帧为 0，REJECTED |
| 连续编码/队列发送、取消、拒绝、失败、回绕 | 编码序号全为 0 | 260 个入队运动请求，经取消/拒绝后实际 258 帧，序号为 0…255,0,1；独立核查 payload 与调用次数 |
| source packet 丢失整圈，header 相同但 boot 前进 | 原实现没有对应判别 | 允许源时间重锚；原样重复仍拒绝；ACK 不据此获得唯一请求身份 |
| repeat_pose 第二份新消息被第一份旧消息替换 | raw 解码为 boot=1000，日志 payload 却为 1100 | 输入保留 1100，明确丢弃；输出保留 1000 并对应相同 sequence/payload |

- 修复前日志：`before-reproductions.log`、`reference-current-assertions-before.log`（5 项，4 断言失败、1 Guard 未捕获异常）；后者在隔离的 6833e4b 源码副本中运行。
- P2-A 旧源码复现：`before-proxy-reproduction.log`；修复后：`final-proxy-boundaries.log`、`full-wrap-boundaries.log`、`pre-final-injection-boundaries.log`。
- 新回归不仅检查 CommandStatus，还检查 transport.attempts、真实帧类型/参数/序号、取消/拒绝后是否调用 Writer。传输开始后才超时的用例为 UNKNOWN、一次尝试、没有自动重试。

## 两轮真实 SITL/Gazebo 验证

- 固定代码提交 `f66be9f033287393c87abbad00d8829d44c33b07`，启动工作区干净；两轮源码 SHA256 相同：`94faae5e6516b6c7926d76900148c48e2779f3e1bbcb705e244f10e20001c0ec`。
- Python `3.12.3 (main, Jul 15 2026, 23:46:41) [GCC 13.3.0]`；ArduPilot `b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`（Rover/Copter V4.8.0-dev），Gazebo 8.15.0，插件 `3ec51428fd43deb7b71137192ba16394b450d78e`。
- 使用现有 target_rover / rover_runway、iris_with_gimbal / iris_runway 及原 profile/参数。未修改外部 ArduPilot/Gazebo 源码、插件、模型或独立旧工程。实际二进制、参数、生成模型及各进程身份见每个 manifest。

```bash
PATH="$PWD/.venv-migration/bin:$PATH" ./scripts/test_phase1_control.sh --remediation --allow-send
```

本轮实际目录为 `artifacts/phase1-remediation/acceptance-v4/`。入口要求新目录，复跑默认生成新标识，不覆盖现有证据。两轮各有 Rover/Copter probe、physical、faults，共 12 场景；新重放/期限场景被加入 probe 的强制判定，不替换原完整场景。

| 门槛 | Rover 第一次 | Rover 第二次 | Copter 第一次 | Copter 第二次 |
| --- | --- | --- | --- | --- |
| A | PASS | PASS | PASS | PASS |
| B | PASS | PASS | PASS | PASS |
| C | PASS | PASS | PASS | PASS |
| D | PASS | PASS | PASS | PASS |
| E | PASS | PASS | PASS | PASS |
| F | PASS | PASS | PASS | PASS |

A 连接/车型/会话，B 真实遥测与归一化，C 正式 Execution 与独立物理结果，D 零写入安全拒绝，E 故障恢复与新增重放/期限，F 持续接收、重连和资源清理。

| 修复专用量化证据 | Rover 第一次 | Rover 第二次 | Copter 第一次 | Copter 第二次 |
| --- | --- | --- | --- | --- |
| 重放后、释放真实 Disarm 前状态 | ACKNOWLEDGED | ACKNOWLEDGED | ACKNOWLEDGED | ACKNOWLEDGED |
| 真实上游与已确认状态仍 armed | True | True | True | True |
| 正常 Arm/Disarm 连续完成数量 | 4 | 4 | 4 | 4 |
| 锁等待到期 Writer 调用次数 | 0 | 0 | 0 | 0 |
| Guard 跨期限 Writer 调用次数 | 0 | 0 | 0 | 0 |
| 位置目标 Gazebo 误差 / m（≤0.75） | 0.498 | 0.509 | 0.114 | 0.153 |
| SITL 重启旧队列写入次数 | 0 | 0 | 0 | 0 |

真实重放中，代理先持有正式 Execution/Writer 生成的 Disarm 帧，使 AP 实际保持解锁，再原样重放历史 ACK/HB；同时核查真实上游 HB、框架稳定状态与请求状态。随后只释放已授权的原帧，收到 AP 新 ACK，并用新状态完成；再执行一组正常 Arm/Disarm 对照。没有直接构造另一条控制发送捷径。

期限场景用真实单调时钟：20 ms 请求在 Authority 锁等待 30 ms 后被拒绝；Guard 在期限前开始、期限后返回的起止时间明确保存。它在已完成 Execution 准入后直接调度唯一 Writer，避免 socket.read 先耗尽期限而伪装成 Guard 内过期。之后正常有效请求仍完成。

## 安全链、协议边界与遗留限制

- 默认双 SEND 关闭、hardware_controlled 仍拒绝；仅使用本轮 OwnedSimulation 的 loopback 目标。没有连接真实飞控/实车；既有串口单元测试仅使用临时伪终端。
- 原 Authority、Execution、两类 SafetyPolicy、物理验收阈值和两份架构基线逐字节未变；唯一 transport.write 点仍在车辆命令端口，未绕过任一安全层。
- ACK 只表明收到同 MAV_CMD 的候选回复，8 位序号不是请求 UUID，400 也不回显 Arm/Disarm 参数。`COMPLETED` 表示获得规定的新目标状态证据，不证明该 ACK 唯一属于本请求，也不证明运动物理完成。位置/速度流仍无 ACK，物理结果由原 Gazebo oracle 单独验证。
- 顺序无法可靠重建的区间、重复/旧采样及无合格源时间的状态不参与确认。ACK/状态超时保留 UNKNOWN；当前会话的歧义命令号不自动重试，须明确新连接/重新授权。正常合法连续 Arm/Disarm 已通过，两类车型没有被整体禁用。
- 无签名 MAVLink 无法防御伪造来源、重打包序号/时间、或一整段自洽历史流的主动攻击；本修复不是密码学反重放。协议无法识别的字节别名不等于新请求证明，仍需独立审查上述源时间/有序链路信任边界。
- Guard 为持 Authority 锁的同步、非阻塞接口，新增 50 ms 预算，返回超预算/异常均不写。Python 不能安全抢占一个永不返回的任意回调；其挂起会阻塞该 Writer，并不能保证主动 Stop 继续调度，不能据此解锁实机控制。
- 生产 TCP 写超时为现有周期的一半（当前 50 ms），注入阻塞 socket 默认限 1 s；串口保留既有有界超时。开始调用时的有效准入不能撤回已进入内核/链路的字节，部分/晚返回/失败写报告 UNKNOWN 并封锁后续写入，不能称为车辆已经执行。
- 飞控 boot 回退要求新 transport/session 和重新授权；32 位 boot 时钟回绕同样保守地要求新 epoch，本轮不声称长期实机运行资格。
- 其他阶段的 P26 Nav2 失败、迁移中的既有 Application oracle 失败原封保留，不属于本次重新认证；未开发 Phase 2、Plane 专属控制或新感知/导航/智能能力。

## 原始证据、清理与提交

- 正式总表：`artifacts/phase1-remediation/acceptance-v4/summary.json`；`unit.json`、`stages.json`；开始 `2026-10-23T05:51:03.783795+00:00`，结束 `2026-10-23T06:17:09.734328+00:00`。
- 独立运行 `run-1-ff12462f`：每车 `*-probe` 保存 remediation 字段、原始报文、实际写入和 guard/lock 时间；`*-physical`、`*-faults` 保存完整原场景结果、真值、SITL/Gazebo 日志和清理 manifest。
- 独立运行 `run-2-4ba8f842`：每车 `*-probe` 保存 remediation 字段、原始报文、实际写入和 guard/lock 时间；`*-physical`、`*-faults` 保存完整原场景结果、真值、SITL/Gazebo 日志和清理 manifest。
- 独立解码核查 184654 条原始报文日志：raw_hex/payload/sequence/system/component 全部一致；实际重放转发 8 条，repeat_pose 替换丢弃 468 条。
- 最终 12 个车辆场景 manifest、36 个仿真子进程及 14 个阶段进程均正常结束、端口释放。含调试/中止运行的全部 21 份 manifest、54 个仿真进程另作终检，均已清理。
- `acceptance-final`、`acceptance-v2`、`acceptance-v3` 是开发中主动中止的记录，保留 FAIL/InterruptedError 和原始日志；原因分别为完善 P2 替换丢弃记录、补齐整圈序号跳跃边界、加强真实 Guard/上游状态证据。它们不计作完整验收轮次。
- [机器证据索引](v1.1/phase1-remediation-evidence.json) 保存源版本、各门槛细节、所有文件 SHA256、历史保护校验、进程身份和中止记录。原始大日志保留在 artifacts，不纳入 Git，不以摘要替代。
- `9485d36`：四项修复、源时间/状态确认与确定性/实测探针。
- `8123b51`：明确替换、未转发报文的丢弃证据。
- `663aafb`：整圈 packet sequence 跳跃的源时间重锚边界。
- `f66be9f`：真实 Guard 跨期限、上游 armed 与新 ACK 证据；两轮完整测试基于此提交。
- 最后报告提交 SHA 由 `git log -1 --format=%H -- docs/PHASE1_REMEDIATION_REPORT.md` 获取，最终答复给出该提交与工作区状态。

**可以重新提交独立审查。** 开发侧测试全部通过；最终 Phase 1 验收仍由独立审查员决定。修复完成后停止，等待用户安排审查。

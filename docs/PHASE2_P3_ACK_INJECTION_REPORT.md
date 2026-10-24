# Phase 2 P3：ACK 故障注入修复记录

状态：**READY FOR RE-AUDIT**。本轮修复侧验证全部通过，等待用户最终确认；不自行宣布最终验收通过。

## 基线与范围

任务输入为独立审查 CONDITIONAL PASS，遗留 P3 为 Plane Cancel Window 的 ACK 故障注入参数错误。
基线 `5d00ecb2891d4e3546f73416f50c356362d62a35`，工作区干净；独立分支 `fix/phase2-p3-ack-injection`。
基线 415 单元通过，修复代码提交 `561e1785079eb1b678f1ac22463d6b0e7c8a2610`。只修改四个测试文件，未修改生产控制器、
Mission、Action、Execution、Authority、Safety、协议、车型配置或阈值；全部 190 个生产 Python 文件哈希未变。
不开发下一阶段，不连接实机，不修改独立的 ArduPilot/Gazebo 源码或用户资源。

## 根因、修复和直接证据

`plane_cancel_window.py` 原传入 `drop_ack_commands={176}`；代理实际只读取单个命令号
`drop_ack_command`。`inject()` 原对任意名字执行 setattr，因而静默创建无效属性。
已读取原两轮代理日志，均有 1 条目标 ACK 实际转发。此前不再 poll 应用的行为不足以证明代理丢弃，
原 `peer_ack_observed_not_delivered` 声明缺少相应证据，旧验收中的该故障注入覆盖不成立。原始报告、索引和独立审查不覆盖，
以本报告和新目录作为纠正及补充；原样复核见 `original-injection-defect.json`。

最小测试修改：

- `tests/simulation/faults.py`：仅允许既有八项故障参数，先校验整个参数批次；未知名字抛 ValueError，
  不部分改变配置、不记录成功注入。验证拼写错误及原有非故障属性均被拒绝。
- `tests/simulation/plane_cancel_window.py`：使用 `drop_ack_command=176`。要求实际收到飞控接受 ACK、
  同字节/同 epoch 的 filter 丢弃记录，且全窗口无目标 ACK 转发；观察真实应用 Transport.read 返回字节，
  保存 `application-rx.jsonl`，断言应用收到目标 ACK 为零、CommandPort 未采纳该 ACK。
  用正常 Arm COMPLETED 及其应用收包 ACK 作为观察器正对照，避免靠拒绝全部消息取得通过。
- 加入同作用域尚未写出的第二个 TAKEOFF，要求取消后 CANCELLED、退出旧队列、零额外写入。
  已写出的 TAKEOFF 必须 UNKNOWN，飞行停止 UNCONFIRMED；不能重标为已取消或伪称已停。
- `tests/simulation/test_proxy.py` 与 `tests/test_plane_cancel_window.py`：稳定复现未知参数缺陷，
  验证缺少真实丢弃、错误原始帧、错误 epoch、旧 ACK、已转发或应用已收到 ACK 均不能通过。
  同时验证已发送/排队 TAKEOFF 的不同取消语义和实际 Writer 次数。

修复前严格参数测试有 4 个稳定失败子例，见 `strict-before-clean.log`；最初对内部属性的探索探针
还出现自身异常，保留 `strict-before.log`，不计为修复后结果。修复后 36 项定向回归全部通过。

## 两轮独立真实 SITL + Gazebo

每轮全新自有状态目录、进程、世界/partition、会话和临时签名凭据。45 秒预热、Arm 7 秒、
ACK 拦截 1 秒、取消后运动 5 秒等原有上限均不改变。不是内存/Mock 结果。

| 轮次 | ACK 收到/丢弃/转发/应用收到 | 已发送命令/停止结果 | 旧队列/写入 | Writer 总数/TAKEOFF/恢复 | 取消后真实移动 m |
| --- | --- | --- | --- | --- | --- |
| 1 | 1 / 1 / 0 / 0 | UNKNOWN / UNCONFIRMED | CANCELLED / 0 | 2 / 1 / 0 | 0.832995 |
| 2 | 1 / 1 / 0 / 0 | UNKNOWN / UNCONFIRMED | CANCELLED / 0 | 2 / 1 / 0 | 0.882937 |

两轮正常 Arm 均 COMPLETED，应用端均实际观察到正常 Arm ACK。两轮 Action 交接拒绝且旧 Action、
Lease、授权/SEND 代际不变；旧 World 样本未被改写。新会话只读重连后有新鲜已解锁遥测，
没有旧授权或命令重放，shutdown 仍为 UNCONFIRMED，额外 Writer 为 0。
实际写出帧严格仅为 COMMAND_LONG Arm=400 和 TAKEOFF 模式=176/13，额外排队 TAKEOFF 未写出。
真实 Gazebo 运动说明收到旧静止地面样本不能证明已写出的 TAKEOFF 不会继续执行。

## 全量与受影响回归

- 全量单元：420 项，0 失败、0 错误、0 跳过，`unit.json` / `unit.log`。
- 定向回归：36 项，代理过滤/延迟/重复、证据判定、Plane 控制、原生恢复边界和 Rover RTL，全部通过。
- 两轮 Plane Cancel Window：全部通过，目标 ACK 真实拦截且应用端未收到。
- 正常 Plane 完整物理回归：滑跑起飞、原生目标确认/运动、LOITER/RTL 续飞段、实际 AUTOLAND/Disarm，
  以及原有期限/Lease、回绕重放、正常连续 Arm/Disarm、取消和失联检查全部通过，未修改阈值。
- 共享故障代理 Rover/Copter 回归：各完整 18 项故障检查通过，原故障集保留。

原始执行命令、退出码、冻结提交和输入摘要见 `stages.json`、`real-summary.json`。
运行 UTC：`2026-10-24T19:39:43.616074+00:00` 至 `2026-10-24T19:51:38.969922+00:00`；输入 SHA256 `082122ffa7c9a1909c7b228e0523f2b30f7bece19ed91a4078d33588c6ea7bfe`，结束时一致。
新增证据单独保存在 `artifacts/phase2-control/p3-ack-injection/`，不冒充旧版完整两轮验收的替代。

## 清理、历史保护和交付

五个真实场景均验证凭据销毁、自有状态与私有文件不存在、进程身份退出和端口释放；包括应用代理端口。
只核查 PID/start_ticks 对应的自有进程，不停止未知进程或删除外部文件。审计见 `audit.json`。
114 份既有文档/审查文件及旧索引的 625 项证据均逐项哈希不变；原报告、独立审查结论和失败证据保留。
未读取 EEPROM 密钥，不记录或提交临时认证密钥。凭据销毁后保留在线签名验证记录，不声称能用已销毁密钥重新验旧 MAC。

本轮真正拦截 ACK 后未发现新的生产控制缺陷；因此没有扩大生产修改范围。
本报告为修复侧结果，未代替用户安排的最终确认。后续停止开发。

修复代码精确 SHA：`561e1785079eb1b678f1ac22463d6b0e7c8a2610`。报告/证据提交后的最终 SHA 和干净工作区检查，
见 `artifacts/phase2-control/p3-ack-injection/delivery.json`；避免报告自引用其自身提交。
完整文件哈希索引见 [P3 证据索引](phase2/p3-ack-injection-evidence.json)。

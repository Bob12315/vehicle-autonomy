# P1-03 当前安全与发送基线

**状态：Current Implementation 源码基线。** 本文记录默认配置下的可达路径，不是 V1 Target 链已全部落地的声明。依据源码与配置静态核查，未连接车辆、未开启 SEND、未做实机验证。未来任何改变 Execution、Safety、writer、连续运动或 payload 的迁移，须与本基线及对应离线测试比较。

## 实际控制链与 owner

```text
app/main.py → SystemRunner
  → MissionApplicationService / MissionOrchestrator 或 Action Lab
  → ActionRuntimeService → ActionRunner → ActionResult.effects
  → ActionDispatcher: dispatch policy + SEND / RunAuthorization
  → ActionSafetyPipeline: request / telemetry / envelope / payload
  → ServiceManager.command_port (VehicleCommandAdapter)
  → LinkManager → MavlinkCommandAdapter
  → CommandBroker + CommandBrokerWorker (默认 v2 writer)
  → MavlinkEnvelopeWriter → CommandSender encoder
  → MavlinkClient.send_raw_message → MAVLink link
```

证据：[生产入口](../../app/main.py#L32)、[SystemRunner 组装](../../application/runner.py#L163)、[Mission tick](../../application/mission_service.py#L314)、[Action tick](../../application/action_runtime.py#L100)、[Dispatcher](../../execution/dispatcher.py#L120)、[Safety](../../execution/safety_pipeline.py#L194)、[LinkManager v2 分支](../../telemetry_link/link_manager.py#L150)、[broker 实发](../../telemetry_link/command_broker.py#L139)、[MAVLink 写入](../../telemetry_link/mavlink_encoder.py#L36)。`ActionResult.effects` 属于当前 Action Contract；某些 `align_descend` 控制值还从 result detail 转成 `FlightCommand`，见[兼容转换](../../execution/dispatcher.py#L130)。

`application/core/runtime.py` 的 `build_core_runtime`、`missions/core/` 与 `execution/dispatcher_v2.py` 有目标方向的实现和离线测试，但全仓非测试代码未见该 builder 从生产入口调用；**它们不是当前 Mission / Action 运行 owner**。平台侧 v2 CommandBroker 则已由默认配置选为实际 writer，不能把两者混为同一“v2 是否上线”结论。

上述链限定于 `app/main.py` 入口。独立开发工具 [`tools/telemetry_debug.py`](../../tools/telemetry_debug.py#L22) 通过 [`dispatch_text_command`](../../telemetry_link/command_dispatcher.py#L65) 直接调用 LinkManager 的 arm/takeoff/servo 等方法，**没有 ActionSafetyPipeline**。默认 v2 broker 的 WriteContext `send_enabled=False`，[源码](../../telemetry_link/mavlink_command_adapter.py#L21)，所以没有显式上下文时正常 command admission 会拒绝；若切换到 legacy writer，此工具可能形成缺少 Action Safety 的直发路径。它不能被视作正式操作入口，未来必须按唯一出口约束处理。

## 当前 Safety 门禁

| 门禁 | 源码事实与保持要求 |
| --- | --- |
| 系统 SEND | [`config/app.yaml`](../../config/app.yaml#L120) 默认 `executor.send_commands: false`；[`app/config.py`](../../app/config.py#L209) 装载初始值，[`SystemSendState`](../../application/send_state.py#L12) 保存开关。不得将连接 telemetry 等同于可发送。 |
| Action / Mission 授权 | [`MissionApplicationService`](../../application/mission_service.py#L93) 对需授权 Action 要求 `authorize` 并创建含 run ID、操作者、source、allowed actions 的 [`RunAuthorization`](../../execution/authorization.py#L8)；Mission 启动同样检查，[源码](../../application/mission_service.py#L203)。 |
| 双门控和白名单 | [`SafetyGate`](../../execution/policy.py#L10) 检查 run authorization 与 SEND；[`ACTION_DISPATCH_POLICY`](../../execution/policy.py#L49) 限定 action type 与允许的 Action。视觉目标锁定 effect 的 `requires_send_commands=False` 仅适用于非车辆运动的视觉命令。 |
| Action Safety | [`ActionSafetyPipeline.evaluate`](../../execution/safety_pipeline.py#L194) 检查授权范围、source、请求 TTL、telemetry freshness、数值与动作包线；GLOBAL/FIELD 请求还检查 reference，[源码](../../execution/safety_pipeline.py#L384)。配置来自 [`config/safety.yaml`](../../config/safety.yaml)。 |
| Payload | `set_servo` 仅由 `payload_release` 的 dispatch rule 允许；Safety 检查允许的 servo output/PWM 与幂等 key，[规则](../../execution/policy.py#L69)、[校验](../../execution/safety_pipeline.py#L507)。当前路径为 `payload_release → set_servo`，不使用 RC override。 |
| broker late gate | [`CommandBroker._admission_reason`](../../telemetry_link/command_broker.py#L336) 检查 send enabled、source、session、generation、deadline、Field version；[`drain_one`](../../telemetry_link/command_broker.py#L139) 在物理 write 前再次执行 final check。 |

Dispatcher 在派发时把 run ID 与 SEND 状态写入 command port 的 [`update_write_context`](../../execution/dispatcher.py#L189)；[`LinkManager`](../../telemetry_link/link_manager.py#L573) 用 generation 隔离旧命令，并在 SEND 关闭时取消 source。默认配置 [`legacy_writer_enabled: false` / `v2_writer_enabled: true`](../../config/telemetry.yaml#L99)，配置解析要求二选一，[源码](../../telemetry_link/config.py#L192)。同一 source 的生产 vehicle command writer 是 CommandBrokerWorker 调用 MavlinkEnvelopeWriter；legacy CommandSender thread 是配置切换用分支，默认未启动。启动连接时另有直接发送 `REQUEST_MESSAGE_INTERVAL` 的链路初始化，[源码](../../telemetry_link/link_manager.py#L272)；它是遥测频率请求，**不应被误写成经 broker 的运动命令，也不能据此放宽车辆运动门禁**。

## Deadman、停止、取消与断链

- [`ContinuousCommandGuard`](../../execution/safety_pipeline.py#L35) 独立监视最近接受的连续 request，过期、source 改变、telemetry 断连/stale、control disallowed 时调用 `stop_body_velocity_and_clear`，并清 pending navigation，[判定](../../execution/safety_pipeline.py#L119)、[停止](../../execution/safety_pipeline.py#L137)。
- Action stop/reset 与切换经 [`ActionRuntimeService.clear_navigation_queue`](../../application/action_runtime.py#L167) 请求显式 BODY_NED stop 和旧导航清理；撤销授权还会停止 Continuous Guard，[源码](../../execution/dispatcher.py#L854)。系统 SEND 关闭、source 切换、重连均撤销授权并清队列，[源码](../../application/system_control.py#L40)。
- 默认 v2 broker 的 [`cancel`](../../telemetry_link/command_broker.py#L204) 冻结写入、取消匹配队列、必要时尝试 stop barrier，返回 `TRANSMITTED` / `STOP_UNDELIVERABLE` 等 disposition。断链时不能保证物理 STOP 送达，必须保留这种显式结果，不可将“请求停止”写成“车辆已停止”。`LinkManager` 在 source 切换与 shutdown 触发取消，[源码](../../telemetry_link/link_manager.py#L228)、[切换](../../telemetry_link/link_manager.py#L444)。
- [`TelemetryReceiver`](../../telemetry_link/telemetry_receiver.py#L95) 在 heartbeat/RX 超时标记断连；[`SourceRuntime`](../../telemetry_link/link_manager.py#L258) 停止 worker、清队列并重连。v2 broker 的 source/session/generation/deadline 二次检查防止旧 envelope 在恢复后正常写出。需要持续用测试验证竞态，不把静态审计当成运行证明。

## ACK、完成与 writer 的区别

[`MavlinkEnvelopeWriter`](../../telemetry_link/mavlink_encoder.py#L100) 为需 ACK 的命令注册 slot；[`AckRouter`](../../telemetry_link/ack_router.py#L26) 按 link session、MAV command 与系统/组件关联 `COMMAND_ACK`，处理 early ACK、超时和 quarantine；[`TelemetryReceiver`](../../telemetry_link/telemetry_receiver.py#L113) 上报 ACK。Broker 分开记录 queue、transport、ACK 与 state-observed completion，[状态更新](../../telemetry_link/command_broker.py#L308)。**accepted submission、wire transmitted、MAVLink ACK 和动作完成是不同事实**，迁移时不能合并成一个布尔值。

## P1 回归门禁

后续相关代码迁移至少验证：`SEND=false` 不实发、无授权被拒绝、过期/旧 generation/旧 session 被拒绝、stop/cancel 与断链结果、连续命令 deadman、servo 白名单、ACK 关联，以及默认仅一个 production command writer。可复用的离线测试包括[Action Safety](../../tests/unit/execution/test_p0_safety_pipeline.py)、[broker](../../tests/unit/adapters/test_command_broker.py)、[telemetry integration](../../tests/integration/test_telemetry_link.py)和[dispatcher policy](../../tests/unit/execution/test_atomic_dispatch_policy.py)。SITL 验证留给后续涉及控制链的代码阶段；P1 仅做分析文档。

P1 文档阶段执行上述 Action Safety、broker、dispatcher policy 三组离线测试，**30 passed**。使用 `uav-dev` Python 并显式指定本仓库 `tests` 路径；默认 shell 的 `pytest` 不可用，环境中另有旧 `cuadc2026` 测试包会干扰 `tests.fakes` 导入。此结果验证当前离线基线，不代表 SITL 或实机验收。

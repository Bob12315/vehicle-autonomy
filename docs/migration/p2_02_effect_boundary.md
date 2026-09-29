# P2-02 Typed Effect Boundary Inventory & Consolidation

**状态：P2-02 Contract 边界已确定；生产切换未执行。** 本文把 V1 目标与当前可达代码分别标注。Effect 是 Action 请求外部世界产生副作用的 **typed intent**，不是已完成事实，也不是 Mission / Planning / Intelligence 的高层 Intent。Effect payload 不得持有 pymavlink message、socket、serial、`LinkManager`、FastAPI request、硬件实例或可变回调。Command 是通过授权与 Safety 后送往 Vehicle/Perception 边界的请求；Effect 与 VehicleCommand 不同。

## Baseline

任务开始时为 `main`、`a9b30e1 config: shorten field GPS sampling to 6 seconds`。P0/P1/P2-01 的文档、资源及 `contracts/core/common.py` 等改动仍未提交；本任务保留它们，没有 reset、checkout、clean、stage 或 commit。本轮只检查离线源码与测试，不连接 SITL 或实机。

## Current effect graph

**当前生产 Action 主线：**

```text
missions/common/actions/*.py 产生 contracts.effects.Effect
→ contracts.action.ActionResult.effects (list)
→ missions.common.actions.runner.ActionRunner 验证 allowed_effect_types
→ application.action_runtime.ActionRuntimeService.tick
   ├→ result.to_dict() 存入 last_result 供 Mission/UI 读取
   └→ execution.dispatcher.ActionDispatcher.dispatch_result
      ├→ align_descend 的 result.detail.command 可补 FlightCommand
      ├→ Effect.to_request() 转当前 request dict
      ├→ SEND + RunAuthorization + ACTION_DISPATCH_POLICY
      ├→ ActionSafetyPipeline.evaluate
      ├→ once/servo key 检查、continuous stop/clear
      └→ command_port/LinkManager 或 yolo_client
         → telemetry_link v2 CommandBroker (默认 writer)
         → MavlinkEnvelopeWriter → CommandSender → MAVLink
```

证据：[ActionResult](../../contracts/action.py)、[Action Runtime](../../application/action_runtime.py)、[production Dispatcher](../../execution/dispatcher.py)、[Safety](../../execution/safety_pipeline.py)、[LinkManager](../../telemetry_link/link_manager.py)、[broker](../../telemetry_link/command_broker.py)。`dispatch["accepted"]` 只表示提交被接受，不能解释为已发到 wire、已 ACK 或已完成。视觉目标命令走 `YoloCommandClient`，不进入 MAVLink writer。

**已有候选 Core 离线链，未从 `app/main.py` 接管生产 Action：**

```text
legacy ActionResult.effects
→ missions/core/legacy_action_adapter.LegacyActionModuleAdapter
→ contracts.core.action.EffectEmission(local_token, typed payload)
→ application/core/run_coordinator.RunCoordinator
→ contracts.core.execution.EffectEnvelope
   (EffectId, IdempotencyKey, RunId, RunExecutionGeneration,
    ActionInstanceId, emission_sequence, local_token, emitted_input_ref)
→ EffectDispatchAttempt (lease, grant, SEND generation, evaluation snapshot, now)
→ execution/dispatcher_v2.EffectDispatcher
   → authorization/fence → SafetyPolicy → explicit route/translator
   → VehicleCommandEnvelope 或 VisionCommandEnvelope
→ EffectDeliveryTracker + PlatformEffectStatusProjection
→ EffectFeedback 返还 Action
```

证据：[adapter](../../missions/core/legacy_action_adapter.py)、[envelope](../../contracts/core/execution.py)、[coordinator](../../application/core/run_coordinator.py)、[candidate dispatcher](../../execution/dispatcher_v2.py)、[delivery](../../application/core/effect_delivery.py)。生产 Dispatcher 和候选 Dispatcher 没有同时接到真实 writer。本轮也没有把候选 Dispatcher 接入生产入口。

## Effect inventory

分类：A Core generic；B Vehicle；C Perception/Sensor；D Environment；E Application-specific；P Platform/Protocol request。Action 中 `MOVE-LATER` 表示本轮仅确认未来归属，没有移动文件。`ADAPT` 表示已有兼容转换需要保持或补齐，不表示生产链已切换。

| Effect / Request | Producer | Current Owner | Domain | Consumer | Target Owner | Action |
| --- | --- | --- | --- | --- | --- | --- |
| `SetMode` / `SetFlightMode` | takeoff Action、候选 native Action | `contracts/effects.py`; `contracts/core/effects.py` | B，飞控 mode | production Dispatcher；候选 translator | Vehicle Effect family / Plugin | MOVE-LATER P3 |
| `Arm` | takeoff Action、候选 native Action | 同上 | B，车辆武装 | 两套各自 dispatcher | Vehicle contract | MOVE-LATER P3 |
| `Takeoff` | takeoff Action、候选 native Action | 同上 | B，多旋翼/可起飞车辆 | 两套各自 dispatcher | 支持起飞的 Vehicle Effect family | MOVE-LATER P3 |
| `Land` | land Action、候选 native Action | 同上 | B，车辆着陆 | 两套各自 dispatcher | Vehicle Effect family | MOVE-LATER P3 |
| `ConditionYaw`, `ChangeSpeed` | takeoff / align_descend / change_speed Action | 同上 | B，当前飞行控制 | production handlers / candidate translator | Vehicle Effect family | MOVE-LATER P3 |
| `LocalGoto` / `LocalPositionTarget` | 旧类型、候选 native | 同上 | B，车辆位置控制 | production policy 不含 `local_position`；候选 translator | Vehicle Effect family | MOVE-LATER P3 |
| `GlobalGoto` / `GlobalPositionTarget` | goto_waypoint Action | 同上 | B + D reference provenance | production Safety/handler；候选 translator | Vehicle Effect，Environment reference 单独保留 | MOVE-LATER P3/P6 |
| `BodyVelocity`, `FlightCommand`, `BodyVelocityTarget` | align_descend Action / detail.command | 同上 | B，连续 BODY_NED | production deadman/stop；候选 translator | Vehicle Effect family | MOVE-LATER P3 |
| `SetServo` | payload_release Action | 同上 | B；release 选择/评分属 E | production servo whitelist；候选 translator | Vehicle capability Effect；CUADC 投放规则留应用层 | MOVE-LATER P3/P8 |
| `ClearMotion` / `clear_continuous_commands` | 生产控制/Action 请求 | `contracts/effects.py` | B/P，连续运动取消与 stop barrier | production Dispatcher | Execution cancel/Vehicle stop boundary | ADAPT；MOVE-LATER P3/P4 |
| `VisionTargetCommand` / `SetVisionTarget` | target_lock、gps_target_lock Action | `contracts/effects.py`; `contracts/core/effects.py` | C，感知目标锁定 | production YoloCommandClient；候选 VisionCommandPort | Perception Effect family | MOVE-LATER P5 |
| `SetTargetLock`, `SetRecording`, `ResetVirtualNadir` | Action 或 SystemControl | `contracts/platform/perception.py` | C，感知/媒体命令；录制属于 Sensor/IO | VisionCommandEnvelope → YoloCommandClient | Perception/Sensor command contract | MOVE-LATER P5 |
| `RunIoRequest` (acquire/release recording, result projection) | 候选 RunIoAggregate | `contracts/core/run_io.py` | A，Run 生命周期 IO 请求，**不经 EffectDispatcher** | RunIoPort | Core Run IO contract | KEEP |
| `recording_start/stop`, `target_command`, `reset_virtual_nadir` | Web/SystemControl/Mission service | `application/system_control.py` | C/Application use case，非 Action Effect | YoloCommandClient | Application use case + Perception/Sensor port | KEEP |
| Field calibration/commit/reference mutation | Web/Application FieldService | `field/`, `contracts/platform/field.py` | D，Environment 命令，非车辆运动 Effect | FieldService / calibration transaction | Environment application command | MOVE-LATER P6 |
| `select_drop_targets`, GPS fusion/capture outputs | CUADC Actions | `missions/common/actions/` | E，计算与选择，本身不产生执行 Effect | Mission blackboard / result | CUADC application | MOVE-LATER P8 |
| `VehicleCommandEnvelope` with vehicle command union | 候选 EffectDispatcher；当前 LinkManager adapter | `contracts/platform/vehicle_commands.py` | P/B，已过 Effect 裁决的下游命令 | CommandBroker → MAVLink writer | Vehicle command boundary | KEEP；P3/P4 后归位 |
| `VisionCommandEnvelope` | 候选 dispatcher / YoloCommandClient | `contracts/platform/perception.py` | C，下游视觉命令 | VisionCommandPort | Perception command boundary | KEEP；P5 后归位 |

`GimbalAngle/GimbalRate/StopMotion` 目前在下游 VehicleCommand union，未见对应 Action→Execution Core Effect；不能仅因平台命令存在就声明 Action 有该能力。生产 `FlightCommand` 是控制意图兼容形态，候选 Core 无同名 payload；`ClearMotion` 在现有 adapter 中也未覆盖。

当前没有可确认的 **Core generic Action Effect**。`RunIoRequest` 与事件发布等虽是车辆无关的副作用请求，却各有专用 Port 和生命周期，不应仅因通用就并入 Action→Execution Effect union。

## Canonical Effect contract and compatibility

- **唯一 canonical envelope：** `contracts.core.execution.EffectEnvelope`。本轮保留其类身份、字段和导入路径；没有创建第二套 envelope。`EffectEmission` 只是 Action 本地候选输出，不含足够 provenance，不能当作正式请求。生产 `ActionResult.effects` 是旧链 payload 容器，同样不是 canonical envelope。
- **唯一 Effect identity：** `EffectId`，由 RunCoordinator 在 emission 入执行链时分配；`IdempotencyKey` 与该 ID 绑定，retry 复用同一 envelope。`local_token` 和 `emission_sequence` 负责 Action 内反馈关联；它们不能替代 `EffectId`。
- **Provenance：** envelope 保存 run、run generation、action instance、emission sequence 和产生时的 input snapshot ref。评估时的 snapshot、grant、lease、SEND generation 和当前时间在 `EffectDispatchAttempt`，不伪装成 Action 可自行声明的 payload 字段。TTL/deadline/priority 当前在 Action dispatch policy 或下游 command envelope，不在 EffectEnvelope；本轮没有擅自增加生产语义。
- **Typed payload 扩展点：** `contracts.core.effects.TypedEffect` 仅要求类型化 payload 暴露 `kind`；`EffectEnvelope` 与 `EffectEmission` 使用它作注解。现有 `Effect` union / `EffectKind` 和 `EFFECT_REGISTRY` 仍是**候选 dispatcher 的封闭兼容集合**，不能据此声称车辆中立的分发已经完成。未来 domain payload 须为小型不可变 DTO，由显式注册、能力、授权与 Safety 共同允许；仅满足 `TypedEffect` 不能获得发送权。当前 `contracts/core/effects.py` 仍包含 UAV/Field/vision 变体，是 P3/P5/P6 兼容债。
- **Production compatibility：** 生产链保持 `ActionResult.effects → Effect.to_request() → ActionDispatcher`，不额外路由至候选 dispatcher。已有 `LegacyActionModuleAdapter → EffectEmission → RunCoordinator → EffectEnvelope` 能在离线候选链转换部分生产 Effect。该 adapter 按 11 种已识别 action type 显式转换，`FlightCommand`、`ClearMotion` 没有通用转换；`align_descend` 仅对其 `detail.command` 有专门 `BodyVelocityTarget` 处理。旧 Effect 的 `key`、`once`、`priority`、`metadata` 不被这一转换逐字段保留。故它是**部分兼容层**，不能直接用于生产切换；不能通过静默丢弃 Effect 宣称完全兼容。本轮未改变这些算法或 SEND 行为。
- **Effect ≠ VehicleCommand：** `execution/translators/vehicle.py` 是候选显式转换；`contracts/platform/vehicle_commands.py` 定义下游车辆命令和 broker receipt/status。平台命令自身不能由 Mission/Action 直接提交。生产链尚未统一使用 canonical envelope，属于明确的迁移差距。

## Lifecycle and retry ownership

| 轴 | 当前 owner / 事实 |
| --- | --- |
| created / emission | Action 的 `EffectEmission`，RunCoordinator 分配 `EffectId`；生产旧链仅持有 Effect list 与可选 key |
| admitted / rejected | production Gate + ActionSafetyPipeline + handler receipt；候选 `DispatchReceipt` 区分 ACCEPTED/REJECTED/FAILED_TO_SUBMIT |
| queued / submitted | Vehicle `CommandSubmissionReceipt` 与 `QueueState`；视觉 `VisionSubmissionReceipt`；Effect ACCEPTED 不等于 wire sent |
| transmitted | broker `TransportState`，下游 writer 尝试结果；不能由 ActionResult 的 `reason="*_sent"` 推断 |
| ACK | broker `AckState` + `AckRouter`，仅适用需 ACK 的车辆命令；视觉有自己的状态 |
| observed completion | broker `CompletionState` / VisionResultState，经 `PlatformEffectStatusProjection` 映射到 `EffectLifecycleFeedback` |
| failed / cancelled / expired | `DispatchReceipt`、queue/cancel receipt、ACK timeout、completion timeout 分开记录；`EffectFeedback` 保持 admission、transport、ack、completion 四轴，不压成 `sent: bool`。当前投影尚未把全部 queue cancellation/expiry 单独规范化，是后续反馈缺口 |

Retry 分属不同 owner：Action 可按自身状态重新产出 Effect；Mission 的 retry 会重启 step；候选 `EffectDeliveryTracker` 只对 `FAILED_TO_SUBMIT`、非连续 `BodyVelocityTarget` 在限次内复用 envelope 做受限 retry，**ACCEPTED 不重提**；broker 用 idempotency key 判重、queue 处理 supersede/cancel/expiry，不能等同于 Action retry；MAVLink writer 的 `ActionCommand(retries_left=0)` 不做 wire 重发；`AckRouter` 关联并超时 ACK，不将 ACK timeout 变成自动重发。`FAILED_TO_SUBMIT` 若来自提交异常，仍可能有受理结果不明的窗口，生产切换前须证明重试的幂等行为。已受理但状态未知的命令不能由 Core 生成新 Effect 再发送，尤其 servo/payload 与连续运动必须保持专门的幂等及停止规则。

## Deferred and risks

- **P3 Vehicle：** `SET_FLIGHT_MODE`, `ARM`, `TAKEOFF`, `LAND`, `CONDITION_YAW`, `CHANGE_SPEED`, `LOCAL_POSITION_TARGET`, `GLOBAL_POSITION_TARGET`, `BODY_VELOCITY_TARGET`, `SET_SERVO` 及其能力规则、VehicleEffect family 和 translator 所属边界。`takeoff` 与 `land` 的精确能力需由具体车辆声明，不能直接推广到 Rover。
- **P4 Protocol/Transport：** VehicleCommandEnvelope、broker queue/late gate、ACK、MAVLink writer/encoder、LinkManager facade。当前默认 v2 broker 是唯一生产车辆 writer；P2-02 不改变它。
- **P5 Perception/Sensor：** `SET_VISION_TARGET`、TargetLock、录制、VirtualNadir 等的独立 Effect/Command 归属及反馈。录制的系统/Run IO 与 Action Effect 需区别对待。
- **P6 Environment：** Field `ReferenceVersion` 当前仍被 Core `LocalPositionTarget`/`GlobalPositionTarget` 引用；Field calibration/reference mutation 属 Environment command，不应伪装成车辆 Effect。
- **P8 Application：** CUADC 投放、bucket 评分、目标选择和 payload release 参数策略；`set_servo` 本身是 Vehicle capability Effect，但投放决策属于应用。
- **Compatibility debt：** `contracts/core/effects.py` 仍定义具体车辆/视觉变体并 import `contracts.platform.field`；静态测试固定此现状，不允许新增其他 domain import。旧 `VehicleEffect` 名下混入视觉命令，且其 frozen dataclass 内含可变 `params`/`metadata`。候选 adapter 转换不完整，候选 `EffectDispatcher` 的路由/安全规则尚不能处理任意新 `TypedEffect`。这些事实禁止宣称生产链已经切换或 Core Effect 已完全车辆中立。

## Verification and next scope

本轮代码修改纯 Core Contract 的 typed 注解，并修正未接入生产入口的 `PlatformEffectStatusProjection` 中误置的视觉 revision 计算，使车辆与视觉两条候选反馈路径可分别生成 observation；另增文档、静态/契约及投影测试。未修改 production Dispatcher、Action 实现、Safety policy、SEND、授权、broker、ACK、telemetry writer、Field/YOLO 算法或 Mission JSON。最终广泛回归 **400 passed, 1 failed**，唯一失败为既有 goto 测试与 registry 默认 `settle_time_s=1.0` 的断言冲突；此前 P2-01 也记录了同一结果。排除该已知用例后为 **400 passed, 1 deselected**。独立 P1 Safety/broker/dispatcher **30 passed**，telemetry 集成 **37 passed**；候选投影修复的新增测试包含在 400 项中。

**P2-03 建议，仅提出：** 审计现有 `RuntimeInputSnapshot` 对 Vehicle、Perception、Field 具体 DTO 的耦合，确定通用输入快照及 provenance；维持当前生产快照采集和 Safety 顺序，单独验证后再迁移。P2-03 未执行。

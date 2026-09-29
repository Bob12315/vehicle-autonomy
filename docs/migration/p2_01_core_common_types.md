# P2-01 Core Common Types Inventory & Consolidation

**状态：P2-01 已实施；仅盘点与最小 Contract 加固。** V1 目标架构与当前实现须分开理解。扫描范围为 `contracts/`、`application/`、`execution/`、`missions/`、`app/`、`telemetry_link/`、`fusion/`、`field/`、`web_ui/` 中的 Python 定义、导入和相关测试。当前没有独立的 `core/` 源码目录。分类：A = Core Generic，B = Vehicle，C = Platform / Infrastructure，D = Application-specific。表中的目标 owner 是长期归属；`DEFER` 不表示本轮已迁移。

## Baseline and decision

开始时为 `main`、`a9b30e1 config: shorten field GPS sampling to 6 seconds`。工作树已有 P0/P1 的未提交文档、资源迁移及 README 改动；本任务保留这些改动，没有 reset、checkout、stage 或 commit。当前生产链仍是 `ActionRuntimeService → ActionDispatcher → ActionSafetyPipeline → LinkManager → telemetry_link`；`application/core/` 不是生产入口的 Core owner。

本轮的 canonical 决策是**复用已有单一定义**：`RunId` 等跨层 ID 目前只在 `contracts.platform.common` 创建，`contracts.core.common` 只是导入并转出同一对象；`MissionId`、`EffectId` 等只在 `contracts.core.common` 创建。没有创建第二个 `NewType`，也没有把含不同语义的结果、时间或 JSON 类型强制合并。`contracts.platform.common` 的标准库独立性已由现有测试约束；把这些 ID 本轮移动进 Core 会扩大跨层导入与兼容面，留待后续独立迁移决策。

## Existing types

| Type / classification | Current Owner | Current Uses | Target Owner | Action |
| --- | --- | --- | --- | --- |
| `RunId`, `RunResourceGenerationId` (A) | `contracts/platform/common.py`；Core re-export | Core run token、fence、broker/vehicle envelope、run IO | `contracts/core/` 长期；当前唯一 owner 保持 | DEFER |
| `ActionInstanceId` (A) | `contracts/platform/common.py`；Core re-export | Core Action/Mission/Execution、fence | `contracts/core/` 长期 | DEFER |
| `ActionDefinitionId`, `ActionContractFingerprint` (A) | `contracts/core/common.py` | Action definition/ref、Mission step | 当前 | KEEP |
| `MissionId`, `MissionDefinitionId`, `StepId` (A) | `contracts/core/common.py` | Mission definition、step token、snapshot | 当前 | KEEP |
| `EffectId`, `DispatchReceiptId`, `PreparationId`, `IdempotencyKey` (A) | `contracts/core/common.py` | Effect envelope/dispatch、Action delivery | 当前 | KEEP |
| `InputSnapshotId`, `CoreCycleId`, `SchedulerSessionId` (A) | `contracts/core/common.py` | Input/cycle correlation、scheduler | 当前 | KEEP |
| `OperationId`, `RequestId` (A) | `contracts/core/common.py` | Run/System/IO request and receipt | 当前 | KEEP |
| `RunExecutionGeneration`, `AuthorizationGeneration`, `LeaseGeneration`, `SendGeneration`, `CancellationGeneration` (A) | `contracts/platform/common.py`；Core re-export | Fence、grant、lease、SEND/cancel checks | 独立类型保持；未来纯 Core 基础 owner | DEFER |
| `ResourceVersion`, `SchemaVersion` (A) | `contracts/platform/common.py`；Core re-export | Snapshot revision、optimistic concurrency、schema | 单一定义保持；未来纯 Contract 基础 owner | DEFER |
| `CoreTime`, `CoreClock`, `SystemCoreClock`, `ManualCoreClock` (A) | `contracts/core/time.py` | Core lifecycle, scheduler, run/mission timestamps | 当前 | KEEP |
| `ClockStamp` (C) | `contracts/platform/common.py` | Boundary request, vehicle/perception snapshot, observability | 当前 | KEEP |
| `FrozenScalar`, `FrozenObject`, `FrozenJson` alias, `freeze_json`, `thaw_json` (A) | `contracts/core/common.py` | Immutable Action/Mission payload, cycle/system snapshot | 当前 | KEEP |
| `StableReason` (A) | `contracts/core/common.py` | Stable generic reason vocabulary | 当前 | KEEP |
| `RunState`, `RunCommandDisposition` (A) | `contracts/core/run.py` | Run lifecycle / command admission | 当前 | KEEP |
| `ActionState`, `ActionStepState`, `CodecResult` (A) | `contracts/core/action.py` | Action lifecycle and codec | 当前 | KEEP |
| `MissionState`, `FailureMode` (A) | `contracts/core/mission.py` | Mission lifecycle / policy | 当前 | KEEP |
| `SafetyDisposition`, `DispatchState`, Core `SafetyDecision` / `DispatchReceipt` (A, domain-specific) | `contracts/core/execution.py` | Typed Effect authorization / dispatch | 当前，待 P2-02 检查 Effect 边界 | KEEP |
| `FreshnessState`, `ComponentFreshness`, `InputSnapshotRef`, `CycleCorrelation` (A) | `contracts/core/input_state.py` | Input freshness and reference, cycle provenance | 当前，具体 snapshot composition 待 P2-03 | KEEP |
| `SchedulerHealth` (A) | `contracts/core/cycle.py` | Scheduler timing metrics | 当前 | KEEP |
| `RunIoState`, `RunIoSubmissionReceipt`, `RunIoObservation` (A, specific) | `contracts/core/run_io.py` | Recording/result projection lifecycle | 当前 | KEEP |
| `LeaseId` (A), `LinkSessionId`, `CommandId`, `CancellationId`, `SubmissionReceiptId` (C) | `contracts/platform/common.py` | Execution lease; link/broker command identity | Lease identity later Core; transport/broker IDs platform | DEFER |
| `SourceId = Literal["real", "sitl", "test"]` (C, deployment source) | `contracts/platform/common.py` | Fence, runtime source, vehicle/perception routing | 当前；不是通用 Vehicle identity | KEEP |
| `ExecutionFenceSnapshot` / query port (A/C boundary) | `contracts/platform/common.py` | Core authority and broker late gate | 保持单一跨层 contract，后续边界决策 | DEFER |
| `RequestContext`, `OperationReceipt`, `ApplicationError`, mutable `JsonValue` (C) | `contracts/platform/common.py` | Application/platform API serialization | 当前 | KEEP |
| Observability `FrozenJson` class (C) | `contracts/platform/observability.py` | Canonical JSON text + SHA-256 for cycle recording | 当前 | KEEP |
| `ActionResult` (legacy), `OperationResult` (C, production/application) | `contracts/action.py` | Production Action effects and Web/System operation result | 当前兼容 owner，迁移 Action 时再处理 | DEFER |
| `RunAuthorization` (C, production), `SafetyDecision` (C, production) | `execution/authorization.py`, `execution/safety_pipeline.py` | Active Action authorization and safety evaluation | 当前执行链；不可用候选 Core DTO 替换 | DEFER |
| `ActionDefinition` (C, production) | `missions/definitions.py` | JSON Schema, factory, Web catalog | 当前 Mission/Action application boundary | DEFER |
| `SystemSendState`, `SendStateSnapshot` (C, production) | `application/send_state.py` | Active SEND gate | 当前 | KEEP |
| `SystemSendState`, `SendGateSnapshot` (A/C candidate runtime) | `application/core/system_send_state.py`, `contracts/core/input_state.py` | Candidate fence versioned SEND state | 当前候选 runtime；不得接成第二个生产 gate | DEFER |
| `VehicleStateSnapshot`, `VehicleCommandEnvelope`, vehicle command payloads (B) | `contracts/platform/vehicle_state.py`, `vehicle_commands.py` | Vehicle state and motion command | `contracts/vehicle/` / Vehicle Plugin (P3) | DEFER |
| `CommandStatusSnapshot`, ACK/queue/transport/completion states (C) | `contracts/platform/vehicle_commands.py` | Broker admission, wire/ACK/completion projection | Protocol/execution boundary (P4) | DEFER |
| `PerceptionFrameSnapshot`, `PerceptionHealthSnapshot`, `Detection` (C, perception domain) | `contracts/platform/perception.py` | Vision input/health | Perception Contract (P5) | DEFER |
| `FieldReferenceSnapshot`, `ReferenceVersion`, calibration DTOs (D, environment) | `contracts/platform/field.py` | CUADC field reference and calibration | Environment Contract / CUADC profile (P6) | DEFER |
| `DroneState`, `LinkStatus`, `ControlCommand` (B/C legacy) | `telemetry_link/models.py` | MAVLink telemetry/link implementation | Vehicle/Protocol adapters (P3/P4) | DEFER |
| `PerceptionTarget`, `FusedState` (C/D current fusion) | `fusion/models.py` | Drone/gimbal/vision fusion | Perception/World (P5) | DEFER |
| `FieldReference`, `FieldProfile`, `RuntimeFieldGeometry` (D) | `field/` | CUADC competition geometry/calibration | Environment profile (P6) | DEFER |
| Web request DTO / `Identity` / session (C) | `web_ui/` | HTTP/auth boundary | Web/Application | KEEP |

## Duplicate concepts and canonical boundaries

- `RunId` / generation / lease identifiers: `contracts.core.common` re-exports the **same** `NewType` objects from `contracts.platform.common`; it does not redefine them. `MissionId`, `EffectId` and other Core IDs have one definition each. `run_id`, `session_id`, `generation`, `revision`, `sequence` and `snapshot_id` remain distinct identities even where legacy code stores them as `str` or `int`.
- `CoreTime` and `ClockStamp` both carry UTC, monotonic nanoseconds and a domain ID. `CoreTime` adds domain-safe elapsed calculation and is Core lifecycle time; `ClockStamp` is platform boundary/event time. They have different constructor order and API; keep both until a dedicated compatibility migration. `execution.RunAuthorization` additionally keeps seconds as floats in two time domains.
- Core `FrozenJson` is a recursive immutable **value alias**; observability `FrozenJson` is a canonical serialized **record with hash**. They share a name but not a contract. Platform `JsonValue` is mutable serialization input and is not a substitute. Direct `FrozenObject` construction now rejects mutable nested values.
- Production `ActionResult` uses mutable effects, `done`/`failed` flags and output dicts; candidate `ActionStepResult` models a Core step state. Production `RunAuthorization` and `SafetyDecision` likewise differ from candidate Core grant/decision. There is no safe mechanical merge in P2-01.
- `RunState`, `MissionState`, `ActionState`, `RunIoState`, `DispatchState`, command ACK/transport/completion states describe different lifecycle axes. A generic `Outcome` would erase distinctions. Generic reason vocabulary remains `StableReason`; GPS, target, field and ACK codes stay with their domains.
- `SystemSendState` exists in production application and candidate `application/core`; the latter has fence generations and optimistic versioning. Merging now could change SEND semantics. Current production owner remains `application/send_state.py`.
- No vehicle-neutral `VehicleCapability` or universal health type exists. `SchedulerHealth` is scheduler-specific, `PerceptionHealthSnapshot` perception-specific. P2-01 does not invent a capability registry or merge unrelated health DTOs.

## Deferred types and risks

- **P3:** vehicle state, vehicle command/effect semantics (`ARM`, `TAKEOFF`, `SET_SERVO`, BODY_NED), vehicle capabilities, and current UAV-specific arms in `contracts/core/effects.py`. Core currently imports platform Field/Vehicle/Perception *contracts* in `effects.py` and `input_state.py`; the new test permits contract imports but rejects implementation/hardware imports. The vehicle-neutrality gap remains.
- **P4:** link session, broker command/receipt/cancellation IDs, transport/ACK statuses, writer ownership and `telemetry_link` implementation. The diagnostic `tools/telemetry_debug.py` path identified in P1 remains a separate future control-exit issue.
- **P5:** `PerceptionFrameSnapshot`, perception health, fusion output and World snapshot boundary. Current `contracts/core/input_state.py` still names concrete platform Perception and Vehicle snapshots; P2-03/P5 should revisit composition without claiming it is already generalized.
- **P6:** Field reference/version, calibration and CUADC competition state. They are not generic Core or Vehicle identity.
- **String IDs:** active `execution.RunAuthorization.run_id` and many observability/broker records use bare strings; do not substitute one ID category for another solely because both wrap `str`.
- **Time:** TTL, deadline and age should compare monotonic values in the same clock domain; UTC is for audit/display. Existing float seconds, nanoseconds and serialized timestamps coexist. This task did not rewrite them.
- **Nested mutability:** `FrozenObject` direct construction previously accepted lists/dicts despite a frozen dataclass; now guarded. Other frozen DTOs such as `missions.ActionDefinition`, `OperationReceipt` and observability payloads still contain mutable mappings; their owners must address this when migrated.
- **Cross-layer imports:** `contracts/core/common.py` re-exports platform IDs, and Core modules import platform Field, Vehicle and Perception contracts. A pure Core owner move must preserve import identity and test compatibility; this is not solved by copying type declarations.

## Verification and next scope

P2-01 changed only Core immutable-value validation, its unit test, an AST dependency test, this report and its documentation index link. No Mission schema/JSON, config, Web behavior, Action behavior, dispatch policy, command broker, ACK or writer code was edited. Static test checks imports in every `contracts/core/*.py`, including function-local imports, for hardware and implementation roots. The broad contract/Core/execution/Mission/Action selection yielded **378 passed, 1 failed**; the failure is the unchanged `test_goto_reaches_target_and_releases_active_action`: registry default `settle_time_s=1.0` leaves the fourth tick in `waypoint_settling`, while the test expects `waypoint_reached`. The same selection excluding that one known mismatch yielded **378 passed, 1 deselected**. The P1 Safety/broker/dispatcher selection separately yielded **30 passed**. After the final immutable-container check, Core Contract plus the P1 Safety selection yielded **38 passed**. This does not imply SITL or hardware validation.

**P2-02 recommendation only:** inspect `contracts/core/effects.py` against `contracts/effects.py` and vehicle command contracts, identify the single typed Effect protocol and the compatibility adapter, then separately verify dispatch/Safety invariants before any production wiring. P2-02 is not executed here.

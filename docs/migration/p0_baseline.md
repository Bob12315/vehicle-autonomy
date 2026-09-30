# P0 baseline: legacy system and command writer audit

Date: 2026-09-30 (workspace date, Asia/Ulaanbaatar)

## 1. Repository baseline

| Item | Observed value |
|---|---|
| Repository | `/home/level6/vehicle-autonomy-framework`; legacy project is preserved at `legacy/cuadc_2026/` |
| Branch | `main` |
| HEAD | `48f14c847ebbc4e3569d405773aa5ec6de1897e7` |
| Initial working tree | Clean (`git status --short` returned no entries) |
| Python | Python 3.12.3 (`/home/level6/venv-ardupilot/bin/python`) |

No checkout or source modification was performed. The new root is the hardware disconnected framework described in [README](../../README.md) and [architecture](../architecture.md). It has a status CLI, Mission validation, Action registration, minimal contracts, and a guarded Execution gateway; no root production Vehicle, Protocol, Transport, telemetry connection, Mission scheduler, or command port is assembled.

The legacy tree is a substantial operational application, not just a library. It contains CUADC Mission/Action, Web, perception and camera code, MAVLink telemetry, multirotor adapters, and an older Core runtime. This P0 follows only the requested contracts/state/execution path and direct writers; it does not audit the broader business behavior.

## 2. Environment

The active Python environment has, among many system packages, `pymavlink==2.4.49`, `numpy==2.5.2`, `opencv-python==5.0.0.93`, `PyYAML==6.0.3`, `pyserial==3.5`, and `requests==2.31.0`. The new root has no dependency manifest; the archived application has dependency profiles under [`legacy/cuadc_2026/requirements/`](../../legacy/cuadc_2026/requirements/README.md). `pytest` is absent from the active Python environment; an existing isolated pytest executable at `/home/level6/agent-bridge/.venv/bin/pytest` was used for legacy tests, with the legacy root and active environment site-packages on `PYTHONPATH`. The legacy app also reads YAML configuration and runtime files; the inspected test group used fakes and did not open a vehicle link.

## 3. Current main architecture facts

### New root

- State input and commands are contracts only. The current `WorldSnapshot` contains a revision and generic observations; it is not a live vehicle state stream.
- `Action.plan(snapshot, parameters)` returns `Effect` values. Mission validates registered Actions and declared vehicle capabilities; it does not execute them.
- The only new-root call to `VehicleCommandPort` is `core.ExecutionGateway.submit()`. It checks two default-false SEND flags and an injected `SafetyPolicy` before calling the port. The CLI does not wire a command port or policy.
- No real vehicle, SITL, or MAVLink path exists in the new root.

### Legacy system

- **Vehicle state source:** `telemetry_link.MavlinkClient` opens a pymavlink connection; `TelemetryReceiver` updates `StateCache`. `vehicles.multirotor.state.MavlinkVehicleStateAdapter` publishes `VehicleStateSnapshot` from a cache publication cut. `VehicleStateAdapter` exposes that platform snapshot and also projects it into old `DroneState`/`GimbalState`/`LinkStatus`. The legacy `StatePublisher` can publish these compatibility values over UDP.
- **Command path:** `ActionDispatcher` and `telemetry_link.command_dispatcher.dispatch_text_command()` submit through `LinkManager` methods/ports. Depending on the exclusive writer configuration, commands go via `CommandQueue` to `CommandSender`, or via `MavlinkCommandAdapter` → `CommandBroker` → `MavlinkEnvelopeWriter` → the same `CommandSender` encoders. `CommandSender` hands messages to the pymavlink master through `MavlinkClient.send_raw_message()`.
- **Effect / Execution path:** the production-style Action route passes action dictionaries through `execution.ActionDispatcher` and its policy/safety checks before the vehicle command facade. A separate typed path exists in `execution.EffectDispatcher`: authorize/fence → safety → translate typed Effect to `VehicleCommandEnvelope` → `VehicleCommandPort.submit()`. `application.core` has scheduler/cycle/runtime aggregation around input snapshots and dispatch. This is not the new root's current Execution contract.
- **Mission / Action connection:** Mission/Action code produces or advances action data; runtime services hand those actions to the legacy dispatcher. The scoped direct MAVLink writer is in telemetry link. Development telemetry debug commands form a separate path around Execution (details below).

## 4. Baseline test commands and results

| Command | Result | Duration |
|---|---:|---:|
| `python -m unittest discover -s tests -v` (new root) | 4 passed, 0 failed, 0 skipped | 0.003 s (reported test time) |
| `PYTHONPATH=/home/level6/vehicle-autonomy-framework/legacy/cuadc_2026:/home/level6/venv-ardupilot/lib/python3.12/site-packages /home/level6/agent-bridge/.venv/bin/pytest -q tests/contracts/test_contracts.py tests/contracts/test_action_contract_v1.py tests/contracts/test_vehicle_command_contract.py tests/contracts/test_platform_common.py tests/contracts/core/test_common_contracts.py tests/contracts/core/test_effect_boundary.py tests/unit/core/test_stable_core_models.py tests/unit/adapters/test_vehicle_state_snapshot.py tests/integration/test_telemetry_link.py tests/integration/test_telemetry_link_interfaces.py tests/unit/adapters/test_command_broker.py tests/unit/execution/test_p0_safety_pipeline.py tests/unit/execution/test_dispatcher_state_command_separation.py tests/unit/core/test_execution_fence_authority.py tests/integration/core/test_core_runtime_composition.py` (run from `legacy/cuadc_2026/`) | 138 passed, 0 failed, 0 skipped | 1.49 s (pytest-reported) |

The legacy run directly covers contracts and IDs/versioning, effects, vehicle commands, snapshots/state adapter, telemetry link/broker, Execution safety/fence, and Core runtime composition. It is a focused P0 set, not the entire archived test suite.

### P0 completion verification

The scoped audit was completed after checking additional tests cited by the [candidate inventory](p0_inventory.md). All additional groups below were run from `legacy/cuadc_2026/` with the same `PYTHONPATH` and pytest executable shown in the baseline command above:

| Additional test files | Result |
|---|---:|
| `tests/contracts/core/test_dependency_boundary.py`, `tests/contracts/test_perception_platform_contract.py`, `tests/unit/core/test_runtime_input_boundary.py`, `tests/unit/core/test_core_scheduler.py`, `tests/unit/core/test_world_model_p5.py`, `tests/unit/adapters/test_v2_mavlink_backend.py` | 25 passed |
| `tests/unit/core/test_effect_status_projection.py`, `tests/unit/core/test_run_aggregate.py`, `tests/unit/core/test_run_io_aggregate.py`, `tests/unit/core/test_system_control_aggregate.py`, `tests/integration/core/test_core_run_lifecycle.py` | 8 passed |
| `tests/unit/adapters/test_link_control_port.py` | 2 passed |

The baseline legacy group was rerun with **138 passed**, and the new-root `python -m unittest discover -s tests -q` returned **4 passed**. These are four separate legacy runs totaling **173 passed** in the selected P0 groups, not a claim that the entire archive passes now. No vehicle connection or source modification was involved.

### Known failures

- **No test failure in the executed baseline groups.** There are no failed test names to report as baseline known failures.
- Initial runner setup attempt `python -m pytest ...` could not start because `pytest` is not installed in the active environment. The first attempt with the isolated pytest executable also failed collection because the old tree was not on `PYTHONPATH`. After configuring the already-installed runner and dependency path, the listed legacy suite collected and passed. These are test-harness setup errors, not failing tests or product regressions.

## 5. Vehicle command writer audit

Search scope: the full `legacy/cuadc_2026/` Python tree for MAVLink `_send` calls, `send_raw_message`, `command_long`, position target writes, servo writes, transport `write`, socket send, and their nearby submit callers. File/line references below identify the inspected call sites.

| Writer / route | File | Calling entry | Final write destination | Through current/legacy Execution? | Risk |
|---|---|---|---|---|---|
| Legacy queued command backend | `legacy/cuadc_2026/telemetry_link/command_sender.py:98-350,407-713`; raw handoff at `mavlink_client.py:122-125` | Legacy `ActionDispatcher` / `LinkManager` action and control methods enqueue a `ControlCommand` or `ActionCommand`; `CommandSender` drains the queue | `master.mav.*_send` methods on the pymavlink connection to configured real or SITL endpoint | Normally YES for Action dispatch, following legacy policy/safety. Compatibility methods and other internal callers also reach the facade | Vehicle motion, arm/takeoff/land, modes, gimbal, and servo writes; old frame/unit semantics are encoded here |
| Typed broker backend, mutually exclusive with legacy queue mode | `legacy/cuadc_2026/telemetry_link/command_broker.py:30-438`; `mavlink_encoder.py:13-66`; common encoder in `command_sender.py`; selected in `link_manager.py:156-203` | `MavlinkCommandAdapter.submit_*()` → broker `submit()`/worker `drain_one()`; Core `EffectDispatcher` can submit an envelope to the VehicleCommandPort facade | Same `CommandSender` encoders → same pymavlink master | YES for typed Effect dispatch when assembled. Broker enforces fence/generation/connection checks before its writer | Highest control impact; envelope has lease, generations, deadline, cancellation/status and Safety Stop barrier behavior. These protections do not make the separate compatibility/debug route safe by association |
| Development diagnostic bypass | `legacy/cuadc_2026/tools/telemetry_debug.py:24-29,33-39,77-83`; `telemetry_link/command_dispatcher.py:65-...`; `link_manager.py` queue methods | Interactive stdin commands; requires explicit `--allow-send` (otherwise read-only), then `dispatch_text_command()` calls methods such as `arm`, `takeoff`, `local_position`, and `set_servo` | Legacy queued backend → `CommandSender` → pymavlink master | **NO.** It routes to the same low-level writer while skipping ActionDispatcher / Execution safety authorization | Explicit opt-in still allows direct vehicle commands outside the normal Execution decision chain; retain as a bypass candidate during migration |

**Count interpretation:** one shared MAVLink writer stack: `CommandSender` / `MavlinkClient.send_raw_message`, with `protocols/mavlink/codec.py` as a helper for `COMMAND_LONG` encoding. The typed `MavlinkEnvelopeWriter` reuses this stack. There are two exclusive command submission backends selected by config: legacy queue or typed broker. `telemetry_link/config.py` rejects configurations where both `legacy_writer_enabled` and `v2_writer_enabled` are equal. The development debug entry can drive the legacy backend and bypass Execution. Thus there is one configured MAVLink writer stack, two selectable submission routes, and a direct diagnostic bypass—not evidence of two simultaneous physical writers.

Additional boundaries found:

- `infrastructure/transports/{serial,udp}.py` contain generic byte `write()` implementations. The P4 test references them; this audit found no production command composition from those classes into the active `LinkManager` MAVLink write path. Their use as a live vehicle writer is **UNKNOWN** beyond the inspected composition and must not be assumed.
- `telemetry_link/state_publisher.py` and `attitude_udp_publisher.py` send telemetry/datagrams, not vehicle commands. YOLO/perception UDP command traffic is application/perception control, not a direct MAVLink vehicle writer.
- No direct Mission → MAVLink or Web → low-level writer call was found in the inspected control chain. Web Action endpoints enter the Action runtime/dispatcher. The debug tool is a confirmed Execution bypass.

## 6. P0 conclusion

The archived system has a usable base of immutable/versioned contracts and state/command boundary tests, but its owner and semantics are split across `contracts/core`, `contracts/platform`, compatibility `contracts`, telemetry link, and `application/core`. State uses NED-oriented scalar fields and carries `source` and dynamic age fields. Command submission has both a typed fenced broker path and older method-style compatibility APIs. P1 should selectively adapt verified data contracts first; it should not copy these implementations wholesale or wire a vehicle. No P1 code migration was started in this P0.

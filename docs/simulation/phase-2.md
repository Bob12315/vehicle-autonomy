# Phase 2 common simulation runtime (2026-10-01)

Status: **partial integration**. The common explicit composition exists and
was exercised with real Copter SITL/Gazebo for Mode, Arm, and Disarm. Full
motion, long-running scheduling, and Rover integration remain open.

## Implemented boundary

`deployment/simulation_runtime.py` composes one TCP transport, MAVLink codec,
ArduPilot session, fenced command port, ControlAuthority, VehicleExecution,
VehicleSafetyPolicy, and WorldModel for an injected vehicle translator. It
opens a connection only on `connect()`. `begin_run()` defaults SEND off and
requires an active link and fresh state. `submit_effect()` accepts typed
Effects, applies one Action-scoped lease, and queues commands for `cycle()`;
it does not write bytes directly. The cycle receives telemetry, publishes
state, ticks deadman, then invokes the sole fenced writer. The caller owns
the 10 Hz schedule.

`SimulationSafetyPolicy` requires fresh pose and twist, an armed state, and
the vehicle's audited GUIDED mode for motion Effects. The final write guard
rechecks those facts before transport write. Stop remains available when
localization is stale but the link and heartbeat are fresh. Duplicate Effect
IDs with equal content return the first result; unequal content is rejected.
On link loss, the session disables both SEND gates and revokes the lease;
the runtime closes the owned socket, records unresolved command status, and
requires `connect()` to create a new codec/port/session epoch. Reconnect
starts with SEND off and an empty command queue. `end_run()` requests zero
setpoints for active streams and waits a bounded period for a new zero-motion
VehicleState; otherwise it reports `UNCONFIRMED` and closes the link.

The P6 `run-sitl` and `run-sitl-arm` entry points still use their narrow
existing runtime. A discovered empty-session comparison bug was corrected:
starting before a heartbeat now reports missing fresh state.

## Verification

- `python -m unittest discover -s tests -q`: **92 passed**, 0 failures,
  0 skips. New tests cover explicit authorization, ACK plus later heartbeat,
  pose/twist freshness, future/wrong clock, disarmed/wrong mode rejection,
  duplicate Effect IDs, link epoch isolation, and cancellation with a
  transmitted zero setpoint followed by a new zero-motion state.
- The live Copter run used Gazebo `iris_runway.sdf`, ArduPilot
  `b5fbe26515`, plugin `3ec5142`, the Phase 0 parameter files, and the
  common runtime. After fresh `odom` telemetry it submitted `ModeEffect`,
  `ArmEffect`, then `DisarmEffect` through Execution; each reached
  `COMPLETED` after ACK and subsequent heartbeat. It printed `PASS` and
  released the owned processes. Evidence:
  `artifacts/simulation/phase2_runtime_live/runtime.jsonl`, `gazebo.log`,
  `sitl.log` (local ignored artifacts).
- `python -m compileall -q deployment/simulation_runtime.py
  deployment/simulation_safety.py vehicles/multirotor/session.py
  tests/test_simulation_runtime.py` and `git diff --check` passed. Port 5760
  was free after the run.

## Open gates

- The live check covered no takeoff or physical motion. An ACK and later
  mode/arm heartbeat do not establish motion success.
- The runtime has a typed Effect input and common vehicle loop, but the
  autonomous Action/Mission sequence and unattended process harness are not
  built yet. Its 10 Hz cycle is caller scheduled.
- Only Copter has a motion-capable translator. Rover needs its Phase 4
  plugin; both vehicles need the Phase 3/5 truth Oracle and Phase 6 physical
  fault matrix.
- A telemetry-confirmed zero command is a simulation software result.
  Physical stopping after transport loss remains unconfirmed.

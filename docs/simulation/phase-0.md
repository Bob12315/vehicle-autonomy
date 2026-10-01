# Phase 0 environment audit (2026-10-01)

Status: **partial**. The Copter Gazebo/SITL link, telemetry path, and existing
controlled `GUIDED → Arm → Disarm` task were exercised. Body motion has not yet
been commanded or checked against Gazebo truth, so the Phase 0 exit gate and
Simulation Complete remain open.

## Baseline and versions

- Framework HEAD at start: `61827b0`; clean worktree. `python -m unittest
  discover -s tests -q`: 81 passed, 0 skipped. `python -m app.main status`:
  no vehicle connection and SEND false.
- ArduPilot local HEAD `b5fbe26515`; Copter binary present. Configured waf for
  `sitl` and built `ardurover` with `./waf rover -j4` (successful, 56.5 s).
  An initial `./waf rover` ran under the previously selected `MicoAir743v2`
  board; it produced a hardware-board build artifact **only**. No device was
  connected, configured, flashed, or addressed. The board was then switched
  to `sitl` before the Rover SITL build.
- Gazebo Sim 8.15.0; plugin checkout `3ec5142`, local
  `build/libArduPilotPlugin.so`; `ldd` reported no missing dependencies.
  Python `pymavlink 2.4.49`, `pyserial 3.5`.
- `python scripts/preflight_simulation.py --phase0` passed. Full preflight
  correctly reports the absent target Rover world. Ports 5760, 5762, and 9002
  were free before and after each owned run.

## Copter launch and observations

Gazebo was started headless with `gz sim -s -r -v3
/home/level6/gz_ws/src/ardupilot_gazebo/worlds/iris_runway.sdf`. The log
reported `ArduPilotPlugin` loaded for `iris_with_gimbal`; the
`/world/iris_runway/pose/info` topic supplied that entity's pose. The plugin
received SITL packets. The framework received ArduPilot heartbeats and an
active link session. Each run used a new state directory under ignored
`artifacts/simulation/`, and only its own process groups were terminated.

The working Copter SITL invocation for this checkout is:

```bash
python /home/level6/ardupilot/Tools/autotest/sim_vehicle.py \
  -v ArduCopter -f gazebo-iris --model JSON --no-mavproxy --no-rebuild \
  --add-param-file /home/level6/ardupilot/Tools/autotest/default_params/copter.parm \
  --add-param-file /home/level6/ardupilot/Tools/autotest/default_params/gazebo-iris.parm \
  --add-param-file simulation/params/copter_telemetry.parm \
  --use-dir artifacts/simulation/<run>/sitl_state
```

`--model JSON` is necessary for the local plugin's JSON protocol, but prevents
this ArduPilot revision from finding `gazebo-iris` frame defaults by model
name. Without the explicit two ArduPilot parameter files, Arm was rejected
with `Motors: Check frame class and type`. Omitting `--model JSON` loaded the
frame defaults but did not establish a usable JSON exchange. The first
experimental `SR0_*` stream settings had no effect: this revision defines
channel-zero stream rates under `MAV1_*`. With `MAV1_POSITION=10` and
`MAV1_EXTRA1=10`, a read-only 45 s probe counted 385 `LOCAL_POSITION_NED`,
385 `ATTITUDE`, and 41 heartbeats. These rates are simulation startup
parameters; the production command path gained no additional writer.

With these parameters, the existing framework command
`python -m app.main run-sitl-arm --allow-send --allow-arm` exited 0. Its Mode,
Arm, and Disarm Effects each progressed through transmitted, ACK, and
completed states; final `armed=false`. During the task, 472 WorldSnapshot
events were published and `vehicle_frame=odom` appeared after position and
attitude arrived. This checks telemetry publication, not motion accuracy.
The run log is `artifacts/simulation/phase0_state_check2/runtime.log` and the
earlier read-only message counts are in
`artifacts/simulation/phase0_stream_check/counts.txt`.

## Open gates and next checks

- No Takeoff or other motion request exists in the P6 task. Gazebo body
  movement and telemetry/truth alignment remain unverified. Phase 3 must
  command motion through Execution and compare new Gazebo pose samples with
  VehicleState before this Phase 0 gate can be closed.
- The Rover SITL binary now exists; the target two-drive-wheel plus two-rear-
  caster Gazebo model/world is absent. Phase 4/5 must establish it and test
  physical motion. The full preflight remains red until then.
- A separate probe exposed a P6 startup bug when no session exists:
  `start_mission()` compares two `None` session values and raises an
  irrelevant "in-flight cancelled mode" error. This is recorded for Phase 2;
  it did not affect the successful run after a fresh heartbeat.
- The successful task reported `sitl_version=null` because this revision did
  not emit a matching version status text. The binary and Git SHA above are
  the local version evidence.

# Phase 3 Copter physical simulation (2026-10-01)

Status: **Copter normal scenario passed twice**. Rover and fault gates remain
open; this does not establish Simulation Complete or real flight support.

## Command and environment

From the repository root:

```bash
python -m unittest discover -s tests -q
PYTHONPATH=. python tests/simulation/copter_scenario.py --allow-send --full
PYTHONPATH=. python tests/simulation/copter_scenario.py --allow-send --full
PYTHONPATH=. python tests/simulation/copter_scenario.py --allow-send
```

The first command passed 94 tests, zero failures or skips. The full scenario
passed twice on final code: `artifacts/simulation/copter-scenario-10bb3492/`
and `artifacts/simulation/copter-scenario-6e562e99/`. The separate explicit
Land run passed at `artifacts/simulation/copter-scenario-e06952cf/`. Each run
has `summary.json`, `observations.jsonl`, runtime events, SITL and Gazebo logs.
The harness owns and terminates its own process groups.

Environment: ArduPilot `b5fbe26515`, Gazebo Sim 8.15.0, local ArduPilot Gazebo
plugin `3ec5142`; `iris_runway.sdf` / `iris_with_gimbal`, TCP 5760, JSON plugin
port 9002. The scenario launches Gazebo, Copter SITL with explicit `copter.parm`,
`gazebo-iris.parm`, and `simulation/params/copter_telemetry.parm`, then the
common simulation runtime. SEND is enabled only by `--allow-send` and the
run-scoped Action lease. Without the flag, the script exits before launch.

## Physical checks

The final full run took off to 1.5 m (state rise 1.49 m, Gazebo truth rise
1.495 m), held a GUIDED position, reached the 2 m east/1 m north Goto with
0.11 m truth and 0.12 m state horizontal error, and stopped with truth speed
0.056 m/s. Three-second world X/Y velocity segments displaced 1.17 m and
1.16 m with peaks 0.54/0.53 m/s for a 0.5 m/s target. Positive body yaw
rotated 0.99 rad; body-forward displacement projected 1.18 m along the
heading. Subsequent Stop checks were under 0.038, 0.028, and 0.014 m/s.
Cancel confirmed its zero-motion stream. RTL returned 0.003 m from home,
landed, and disarmed. The separate Land run likewise checked ground pose and
disarm. The preceding full run had equivalent passing values in its summary.

`tests/simulation/oracle.py` subscribes read-only to Gazebo pose; it checks
fresh host receive times and monotone simulation time. The scenario checks
command/result status, new VehicleState and independent truth with deadlines.
Gazebo data never feeds the production runtime. Streamed setpoints are checked
for transmission and response, without inventing an ACK. Takeoff remains
`ACKNOWLEDGED` at the command layer; physical completion is established by the
scenario's state and truth assertions.

An early LOITER Hold experiment ACKed but descended without RC input, so the
accepted Hold uses refreshed GUIDED position setpoints. A second early run
forwarded measured roll/pitch into a yaw-only target and failed; corrected
targets contain yaw only. Failure artifacts are retained under
`copter-takeoff-f283cff0` and `copter-takeoff-aee93a0b`.

## Remaining gates

Rover plugin/model, fault matrix, and the single-command two-vehicle regression
remain open. The accepted run uses the scripted runtime loop; an independent
long-lived production scheduler is not claimed. No hardware was connected.

# Phase 5 target Rover Gazebo model (2026-10-01)

Status: **normal physical scenario passed twice**. Fault, Cancel, and deadman
gates remain open for Phase 6, so Simulation Complete is not claimed.

## Model and source

`simulation/models/target_rover/model.sdf` is an original primitive-geometry
model with two powered front wheels and two passive rear casters. Each caster
has a free vertical swivel and free wheel roll joint. The body, wheels,
swivels, collisions, inertias, tires, and floor are explicit. Only the two
front drive joints are bound to ArduPilot SERVO1/SERVO3 channels 0/2 and the
Gazebo force plugin. `tests/test_rover_model.py` checks the exact topology and
bindings. `gz sdf -k simulation/models/target_rover/model.sdf` reported
`Valid.`; the headless world loaded ArduPilotPlugin and its IMU without an
error. Initial body pose stayed effectively at world origin.

The official ArduPilot SITL_Models [WildThumper guide](https://github.com/ArduPilot/SITL_Models/blob/master/Gazebo/docs/WildThumper.md)
and model SDF at `master` SHA `25bc38ed8c6c0345840159a8cbc0b02781d52f3c`
were read for JSON plugin, channel, and joint control conventions. That 6WD
model and its visual meshes were not copied; the target model contains only
our seven primitive links. The installed Gazebo plugin fork is `3ec5142`,
ArduPilot is `b5fbe26515`, and Gazebo Sim is 8.15.0.

## Commands and evidence

From the repository root:

```bash
python scripts/preflight_simulation.py
python -m unittest discover -s tests -q
PYTHONPATH=. python tests/simulation/rover_protocol.py --allow-send --full
PYTHONPATH=. python tests/simulation/rover_protocol.py --allow-send --full
PYTHONPATH=. python tests/simulation/copter_scenario.py --allow-send --full
```

Full preflight passed with free owned ports and both worlds. The unit suite
passed **99 tests**, zero failures or skips. Two independent final Rover runs
passed at `artifacts/simulation/rover-protocol-b7db9150/` and
`artifacts/simulation/rover-protocol-45beb8e5/`. A third confirming run passed
at `artifacts/simulation/rover-protocol-641bbeea/`; its
`joint_state_sample.txt` captured all six moving joints. The Copter full
regression passed at `artifacts/simulation/copter-scenario-5f0599b3/`.

The final second Rover run measured forward +1.001 m, reverse -1.027 m,
left +0.799 rad, right -0.846 rad, pivot left +0.786 rad, and pivot right
-0.797 rad against fresh Gazebo pose. It measured Goto truth error 0.490 m
and state error 0.520 m. All post-motion Stop truth speeds were below
0.013 m/s after the configured two-second stable window. Mode, Arm, Stop,
and Disarm reached completed command state; streamed setpoints were counted
by distinct transmitted IDs. Joint-state evidence showed both rear swivel
positions changed by more than 1 rad and both passive roll joints by more
than 38 rad during the run. They had no motor channel or force plugin.

The scenario launches only its own Gazebo/SITL process groups, uses the
shared typed Effect→Execution→Safety/Authority→port chain, and records
`summary.json`, `trajectory.jsonl`, SITL/Gazebo logs, and status text in an
ignored run directory. Gazebo truth is read-only test data. Rover SITL uses
`--model JSON` plus explicit rover, skid, and simulation parameter files.

Early attempts are retained: a -46.3 wheel multiplier drove backwards and
could not stop in time; +10 fixed the direction and bounded speed. The first
speed-loop setting stopped too slowly after a long drive. The simulation
`ATC_SPEED_P/I` tune and 0.1 m/s Rover telemetry Stop tolerance made the
unchanged 0.1 m/s Gazebo Stop threshold pass. Fixed five-second turns
overshot one direction; the final scenario ends each turn at the original
45° truth target under a nine-second cap. None of the displacement, angle,
Goto, or physical Stop thresholds was lowered.

## Remaining gates

The Rover normal scenario does not yet assert Cancel or deadman behavior;
those belong to the Phase 6 fault matrix. The model is simulation-only. No
real vehicle, flight controller, serial port, or external deployment was used.

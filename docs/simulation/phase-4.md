# Phase 4 Rover plugin and protocol (2026-10-01)

Status: **protocol gate passed** against internal Rover SITL. Gazebo Rover
physical motion remains the Phase 5 gate.

## Implementation

`ArduRoverCommandTranslator` uses the audited Rover HOLD=4 and GUIDED=15 map.
Arm, Disarm, and Mode use the common command port. Rover Guided body drive uses
`SET_POSITION_TARGET_LOCAL_NED` in `BODY_NED`, mask 1479: forward speed in
`vx`, FLU positive yaw converted to negative NED yaw rate. A zero setpoint
stops the active drive stream. Goto uses `LOCAL_NED` position, mask 3576,
with ENU east/north converted to NED east/north fields. Stop also accepts an
active local Goto stream and sends a body-frame zero speed/turn-rate setpoint.
The local ArduPilot
`Rover/GCS_MAVLink_Rover.cpp` handler accepts these position and velocity plus
turn-rate combinations in Guided mode. Takeoff/Land, sideways/vertical drive,
and nonplanar Goto are rejected. The common Runtime/Execution/Authority/port
retains both SEND gates, lease/session fence, SafetyPolicy, and sole writer.

This Rover build sends `GLOBAL_POSITION_INT`, `GPS_GLOBAL_ORIGIN`, and
`ATTITUDE` at 10 Hz with `MAV1_POSITION/MAV1_EXTRA1`, but did not send
`LOCAL_POSITION_NED` during three 35-second probes. `RoverTelemetryState`
projects the GNSS origin and global location to a local ENU tangent plane and
uses global-position NED velocity. It requires the origin, checks a 50 m
projection domain, and treats a changed origin as a receive fault that closes
the link. Gazebo truth does not enter this adapter.

## Verification

ArduPilot `b5fbe26515`, Rover SITL binary built with `./waf configure --board
sitl` and `./waf rover -j4`; Python 3.12.3 and pymavlink 2.4.49. The local
`rover-skid.parm` maps output functions 73/74 to SERVO1/SERVO3. The owned
internal SITL probe command is:

```bash
PYTHONPATH=. python tests/simulation/rover_protocol.py --allow-send
```

It starts Rover `-f rover-skid` with `rover.parm`, `rover-skid.parm`, and
`simulation/params/rover_telemetry.parm`, waits for fresh state and the 45 s
profile warmup, then exercises GUIDED, Arm, one forward drive setpoint, Stop,
and Disarm. `artifacts/simulation/rover-protocol-9408b60c/summary.json`
reports completed mode, arm, stop, and disarm; the drive setpoint reached
`TRANSMITTED`. Owned SITL processes were removed. An earlier Arm attempt
before EKF position readiness failed with `Arm: Need Position Estimate` and
MAV result 4; its report is retained at `rover-protocol-4844ddf3`.

`python -m unittest discover -s tests -q`: **98 passed**, zero failures or
skips. Tests verify MAVLink frame, masks and signs, type filtering, flight
effect rejection, SEND fence, and origin/velocity projection. Compile and
`git diff --check` passed.

## Open gate

The internal SITL probe is a protocol check only. It does not establish wheel
motion, traction, turn direction, or stopping in Gazebo. The target two drive
wheel plus two rear caster model and independent physical Oracle remain for
Phase 5. No hardware was connected.

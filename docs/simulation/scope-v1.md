# V1 simulation scope and acceptance contract

Status: command scope and numeric targets fixed on 2026-10-01; physical
acceptance is **unverified**. Profiles are
[`simulation/profiles/copter.toml`](../../simulation/profiles/copter.toml),
[`simulation/profiles/rover.toml`](../../simulation/profiles/rover.toml), and
[`acceptance-v1.json`](../../simulation/scenarios/acceptance-v1.json).
Changing a threshold requires evidence and a separately reviewed change;
an E2E failure alone does not justify relaxing it.

## Vehicle and protocol mapping

The mode IDs below come from this host's ArduPilot `b5fbe26515` source
(`ArduCopter/mode.h`, `Rover/mode.h`), checked against the
[ArduCopter mode source](https://github.com/ArduPilot/ardupilot/blob/master/ArduCopter/mode.h)
and [Rover mode source](https://github.com/ArduPilot/ardupilot/blob/master/Rover/mode.h).
The two vehicles share command, session, transport, Execution, and Authority
concepts, but retain separate translators and safety policy. Only the
configured vehicle type and modes are accepted.

| Vehicle | Mode IDs | Required actions and wire form | Completion evidence |
| --- | --- | --- | --- |
| Copter | GUIDED 4, LOITER 5, RTL 6, LAND 9 | Mode `MAV_CMD_DO_SET_MODE`; Arm/Disarm `MAV_CMD_COMPONENT_ARM_DISARM`; Takeoff `MAV_CMD_NAV_TAKEOFF`; Land `MAV_CMD_NAV_LAND`; Goto/velocity/stop `SET_POSITION_TARGET_LOCAL_NED` | ACK for COMMAND_LONG, later mode/armed state, fresh VehicleState pose/twist, and independent Gazebo pose/velocity within timeout. A setpoint has no COMMAND_ACK; transmission plus response and truth must be checked. |
| Rover | HOLD 4, GUIDED 15 | Mode/Arm/Disarm use the same command IDs with Rover's mode map. Forward/reverse/turn/pivot/stop use Guided `SET_POSITION_TARGET_LOCAL_NED` body velocity and turn rate. Goto uses Guided local position target. | ACK plus later mode/armed state where applicable; new state and Gazebo truth for movement/stop; setpoint transmission is not physical completion. |

Rover Goto is **in the mandatory scenario**, since this ArduPilot revision's
`Rover/GCS_MAVLink_Rover.cpp` handles `SET_POSITION_TARGET_LOCAL_NED` position
targets in Guided mode and calls `ModeGuided::set_desired_location`. The
[official Rover Guided command documentation](https://software.ardupilot.org/dev/docs/mavlink-rover-commands.html)
also specifies local position and velocity targets. A live Rover/Gazebo
protocol trial and physical arrival remain open; a static handler is not an
acceptance result.

## Control, frame, and time rules

- All vehicle sends begin as Typed Effects and pass VehicleExecution,
  VehicleSafetyPolicy, ControlAuthority, the vehicle translator, one MAVLink
  writer, and TCP. Both SEND gates default false. A new run and Action lease
  are required after reconnect. Gazebo truth is test-only.
- `odom` is local ENU: +X east, +Y north, +Z up; `base_link` is body FLU:
  +X forward, +Y left, +Z up. MAVLink local/body NED uses +X north/forward,
  +Y east/right, +Z down. Translation belongs in the vehicle plugin. Positive
  ENU yaw is counterclockwise; positive NED yaw/turn rate is clockwise.
  The test Oracle will measure the initial Gazebo model rotation and SITL
  local origin rather than assuming they coincide.
- Effect creation/deadline, lease, receive proxy, state publication, and
  freshness use one host monotonic clock domain. SITL boot time and Gazebo
  simulation time are recorded separately and never compared directly with
  host monotonic values. Unknown capture time is represented in this
  simulation as a loopback receive-time proxy, not a hardware claim.
- Motion admission requires a fresh vehicle pose and twist after warmup;
  heartbeat alone establishes link/operation state but not localization.
  Future, delayed, stale, and wrong-domain state must fail closed.
- The loop runs at 10 Hz. The current profile has 3 s link/state maximum
  age, 1 s deadman, 5 s Effect TTL, and a 90 s lease. Continuous setpoints
  require refresh; deadman/stop results retain accepted/transmitted/confirmed
  versus unknown distinctions. A disconnected vehicle is never labelled
  physically stopped from software state alone.

## Acceptance thresholds

The exact values are in `acceptance-v1.json`. The Copter target is 1.5 m
takeoff, at most 0.35 m steady height error, at most 0.75 m Goto horizontal
error, and at most 0.15 m/s horizontal speed for 2 s after Stop. Rover must
travel at least 1.0 m in each requested forward/reverse direction, rotate at
least 45° in each requested turn direction, then stay below 0.10 m/s for 2 s
after Stop. Stop timeout is 8 s for both. Takeoff timeout is 30 s; Goto is
45 s. These values are candidate limits taken from the execution plan and
frozen before motion testing; they have not been measured as achieved.

Each physical assertion needs a new command result, a new VehicleState, a
new independent Gazebo truth sample, and a bounded elapsed host time. Truth
absence, model/entity mismatch, backward simulation time, or unresolved
ENU/NED alignment fails the scenario. The eventual regression must test
positive local X, positive local Y, positive yaw, and forward body motion
explicitly.

Rover's required `SafetyLimits` altitude fields describe a narrow ground
height band and do **not** authorize Takeoff; the Rover plugin must reject
Takeoff and Land. Its planar geofence and speed limits remain active.

## Open Phase 1 trial

Rover's source and official documentation establish local Goto support, so
Goto stays mandatory. The live Guided protocol trial needs the target
Rover Gazebo model and Phase 4 translator. It is recorded as an open
acceptance item rather than an unsupported feature.

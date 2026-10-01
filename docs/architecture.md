# V1 framework boundary

This page describes the **implemented root**. The reusable framework's full
target responsibilities and dependency rules are in [Vehicle Autonomy Framework
V1: target architecture](framework_v1.md).

The root has no automatically opened hardware connection. Its implemented path is:

```text
Application -> Mission compilation -> typed Action runtime -> Effect requests
WorldReader --------------------------------------^

Fake Sensor + Fake Vehicle -> OfflineStateChain -> WorldModel -> WorldReader

Typed Effect -> offline VehicleExecution -> system SEND + Action SEND
             -> ControlAuthority + SafetyPolicy -> FakeVehicleCommandPort

Explicit ArduCopter composition -> VehicleExecution -> ArduPilotCommandPort
                             -> MAVLink codec -> TCP byte transport -> local SITL

Explicit P6 run-sitl -> loopback TCP receive -> WorldModel -> typed Mode Action
                     -> Effect result feedback -> VehicleExecution -> same sole writer

Explicit Copter STABILIZE diagnostic -> VehicleExecution -> ArduPilotCommandPort
                                    -> MAVLink codec -> serial byte transport -> USB controller

Explicit bare Copter bench diagnostics -> VehicleExecution -> ArduPilotCommandPort
                                       -> MAVLink codec -> serial byte transport -> USB controller

Explicit Rover HOLD diagnostic -> VehicleExecution -> ArduPilotCommandPort
                              -> MAVLink codec -> serial byte transport -> USB controller
```

`contracts/` contains shared, vehicle independent data and ports, including the
P1 time, geometry, observation, vehicle state, localization, world snapshot,
typed effect, and vehicle command contracts. `core/`
implements Action registration, Mission compilation/runtime, TransformTree,
the P4 offline control boundary, and the older demonstration Execution
gateway. `application/` exposes use cases without a hardware port. `app/`
contains only the new status CLI. `sensors/`, `vehicles/`, `localization/`, and
`world_model/` contain P2 offline fake sources, a pure reported-pose projection,
and a World Model that publishes immutable snapshots. `vehicles/multirotor/`
normalizes received ArduPilot telemetry and translates approved commands;
`protocols/mavlink/` packs/parses messages; `infrastructure/transports/` owns
only TCP/serial byte I/O. The P5 `ArduPilotCommandPort` is the sole writer in
these explicit compositions. It holds the authority lock across the final
fence and transport write, and the session receiver handles heartbeat, ACK and
state observations.
`ArduPilotSession` requires an expected MAVLink vehicle type and ArduPilot
autopilot heartbeat before granting a link session. Separate narrow USB
diagnostics expose only Rover HOLD-to-HOLD or Copter STABILIZE-to-STABILIZE;
neither exposes arm, takeoff, or motion. Separate bare-controller bench
translators limit requests to STABILIZE/ACRO modes or Arm/Disarm/STABILIZE.
`deployment/CopterCycleDriver` connects receive, P4 deadman, and queue drain
when explicitly scheduled by a caller; the CLI does not schedule it.
`deployment/SitlRuntime` is the P6 single-process scheduler for an explicit
`run-sitl` CLI invocation. It validates the loopback-only profile before
connecting, publishes a WorldSnapshot each cycle, runs one unarmed Mode Action,
and maps Effect IDs to command statuses. A final write guard rechecks the
disarmed state and freshness; the SITL translator permits only the configured
mode. The Action sees read-only results and succeeds only after ACK plus a
later heartbeat and a fresh WorldSnapshot reporting the target mode. `status`
still opens no connection; both SEND gates default to false, and `run-sitl`
requires `--allow-send` to authorize one Mission lease.

Core never imports a concrete vehicle, protocol, transport, CUADC application,
or `legacy/`. Mission validates registered Actions, typed parameters and vehicle
capabilities; it does not issue commands. Actions receive only a WorldSnapshot
and parameters and emit unapproved Effect requests.
The P1 `VehicleCommandPort` is used by P4/P5 `VehicleExecution`, with either
the fake port or the ArduCopter port injected. The older demonstration gateway
still uses its old Effect submission interface.
P2 state producers and `WorldModel` have no vehicle command port. The World
Model computes freshness from captured/received/published monotonic facts in
one clock domain, omits stale or unknown inputs from the adopted snapshot, and
retains input versions as dependencies. It preserves source frames. The
separate TransformTree resolves explicit static and dynamic frame relations;
the World Model does not implicitly convert them.

P4 `ControlAuthority` defaults both SEND gates to false. The new Execution
boundary requires an explicit `VehicleSafetyPolicy`, one scoped lease, and an
active link session; its fake queue rechecks generations, lease, deadline, and
session immediately before simulated transmission. Continuous commands have
a caller driven deadman and explicit StopMotion request. Accepted, transmitted,
ACK, and observed completion remain distinct; a disconnected stop is
unconfirmed. The root CLI wires no command port or production vehicle link.
P5 maps StopMotion to zero velocity and yaw rate in the active stream frame;
only a later fresh zero-motion state sample marks it complete. Link timeout
creates a new session and fences queued commands; uncertain transport writes
and missing ACKs remain `UNKNOWN`. The local Copter SITL smoke test exercised a
single unarmed GUIDED mode request and ACK. A separate USB Rover controller
diagnostic received HOLD ACK and a later matching heartbeat while disarmed.
A Copter USB controller diagnostic received STABILIZE ACK and a later matching
heartbeat while disarmed. The controller also reports a frame class/type
pre-arm error, so this result is not flight readiness.
The USB state publication uses receive time as a diagnostic proxy; source
capture time is unknown. Physical stopping, Copter motion, and link-loss
behavior have not been validated. P6 likewise uses a loopback-only receive-time
proxy and does not establish real-device capture timing or physical stop.
Heartbeat-based VehicleHealth does not establish sensor calibration or arming
readiness.
With a temporary Quad X frame configuration, the USB Copter completed a
disarmed STABILIZE/ACRO/STABILIZE round trip. Its pre-arm checks rejected Arm;
an explicit Disarm was confirmed. The original undefined frame configuration
was restored and reboot verified. No physical output or flight was tested.

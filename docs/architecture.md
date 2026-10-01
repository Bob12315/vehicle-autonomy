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

Explicit dual-vehicle SimulationRuntime -> VehicleExecution + Safety/Authority
    -> Copter/Rover translator -> same MAVLink writer -> TCP -> SITL -> Gazebo
Gazebo truth -> read-only test Oracle (no production control input)

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
contains the disconnected status CLI and explicit loopback SITL entries.
`sensors/`, `vehicles/`, `localization/`, and
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
The separate `run-sitl-arm` entry requires both `--allow-send` and `--allow-arm`
before connecting. Its three-step Mission confirms GUIDED mode, Arm, and
Disarm in order. Each step receives a newly scoped lease. The final SITL
translator accepts only Mode, Arm, and Disarm; a write guard checks the
disarmed target mode before Arm and an armed state before Disarm. On an armed
failure or cancellation, the coordinator attempts one fenced Disarm with a
bounded confirmation wait. Link loss and unknown Arm outcomes are reported
unconfirmed. This is simulation-only evidence, not real vehicle arming or
physical stop validation.

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
capture time is unknown. Those USB diagnostics do not validate real physical stopping, motion or
link-loss behavior. The narrow P6 runtime still uses a loopback receive-time
proxy. The shared simulation runtime separately maps source boot time per
epoch and validates Copter/Rover motion and faults against Gazebo truth;
real-device capture timing and physical stopping remain unvalidated.
Heartbeat-based VehicleHealth does not establish sensor calibration or arming
readiness.
With a temporary Quad X frame configuration, the USB Copter completed a
disarmed STABILIZE/ACRO/STABILIZE round trip. Its pre-arm checks rejected Arm;
an explicit Disarm was confirmed. The original undefined frame configuration
was restored and reboot verified. No physical output or flight was tested.

## Dual-vehicle simulation composition

`deployment/SimulationRuntime` shares Execution, Authority, codec, session and
the sole command port between Copter and Rover. Vehicle differences are the
injected translator, reported-state adapter, profile and explicit safety
policy. Rover projects MAVLink GPS global origin/state into bounded local ENU
and rejects flight effects and sideways/vertical body motion. Root packages
do not import archived modules. No vehicle connection opens on import.

Callers explicitly connect, schedule at 10 Hz and begin a run. Both SEND gates
and lease default disabled; `allow_send` explicitly grants one scoped run.
Source boot timestamps are mapped to host monotonic time only for the pinned
localhost speed-one composition. Repeats/delay preserve sample age; clock
regression/skew, stale state, link loss, missed cycles and uncertain writes
close the link and revoke authority. Reconnect creates a fresh codec/session/
world epoch and requires a new authorized run; no old queue is replayed.

Stop/deadman/cancel/shutdown request zero velocity through the same writer and
require a later state to confirm it. Physical test success additionally needs
fresh independent Gazebo truth under the original speed/time bounds. At link
loss physical Stop is UNCONFIRMED. Takeoff/Land ACK receipts alone do not
complete a physical action; the test scenario verifies height/ground/final
state. This composition certifies no real hardware, server or RKNN backend.

`./scripts/test_simulation_v1.sh` builds in a fresh owned output directory and
runs both vehicles plus faults, with bounded stage deadlines, unique world
names and unused matching ports. It retains process/command/state/truth
manifests and fails on missing evidence or cleanup failure. See
[simulation usage](simulation/README.md) and [completion audit](simulation/completion-audit.md).

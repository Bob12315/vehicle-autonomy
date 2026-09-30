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
only byte I/O. The P5 `ArduPilotCommandPort` is the sole writer in this explicit
composition. It holds the authority lock across the final fence and transport
write, and the session receiver handles heartbeat, ACK and state observations.
`deployment/CopterCycleDriver` connects receive, P4 deadman, and queue drain
when explicitly scheduled by a caller; the CLI does not schedule it.

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
and missing ACKs remain `UNKNOWN`. The local SITL smoke test exercised a
single unarmed GUIDED mode request and ACK. Physical stopping, capture-time
calibration, and real-device behavior have not been validated; the CLI still
does not open a vehicle link.

# V1 framework boundary

This page describes the **implemented root**. The reusable framework's full
target responsibilities and dependency rules are in [Vehicle Autonomy Framework
V1: target architecture](framework_v1.md).

The root is a new, hardware disconnected framework. Its implemented path is:

```text
Application -> Mission compilation -> typed Action runtime -> Effect requests
WorldReader --------------------------------------^

Fake Sensor + Fake Vehicle -> OfflineStateChain -> WorldModel -> WorldReader

Future Action Effect -> Execution -> system SEND + Action SEND -> SafetyPolicy
                    -> VehicleCommandPort -> Vehicle plugin -> Protocol -> Transport
```

`contracts/` contains shared, vehicle independent data and ports, including the
P1 time, geometry, observation, vehicle state, localization, world snapshot,
typed effect, and vehicle command contracts. `core/`
implements Action registration, Mission compilation/runtime, TransformTree,
and the guarded demonstration Execution
boundary. `application/` exposes use cases without a hardware port. `app/`
contains only the new status CLI. `sensors/`, `vehicles/`, `localization/`, and
`world_model/` contain P2 offline fake sources, a pure reported-pose projection,
and a World Model that publishes immutable snapshots. They contain no device
connection.

Core never imports a concrete vehicle, protocol, transport, CUADC application,
or `legacy/`. Mission validates registered Actions, typed parameters and vehicle
capabilities; it does not issue commands. Actions receive only a WorldSnapshot
and parameters and emit unapproved Effect requests.
The P1 `VehicleCommandPort` is not wired to a root component. The existing
demonstration Execution gateway still uses its old Effect submission interface.
P2 state producers and `WorldModel` have no vehicle command port. The World
Model computes freshness from captured/received/published monotonic facts in
one clock domain, omits stale or unknown inputs from the adopted snapshot, and
retains input versions as dependencies. It preserves source frames. The
separate TransformTree resolves explicit static and dynamic frame relations;
the World Model does not implicitly convert them.

The demonstration Execution boundary defaults both SEND gates to false and
requires an injected SafetyPolicy. No policy or vehicle port is wired by the
root CLI.
The framework does not yet implement physical continuous command stopping,
stale command cancellation, or physical link lifecycle. Those are
required before any real vehicle integration.

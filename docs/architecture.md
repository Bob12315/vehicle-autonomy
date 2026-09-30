# V1 framework boundary

This page describes the **implemented root**. The reusable framework's full
target responsibilities and dependency rules are in [Vehicle Autonomy Framework
V1: target architecture](framework_v1.md).

The root is a new, hardware disconnected framework. Its implemented path is:

```text
Application -> Mission validation -> registered Action contracts
WorldSnapshot --------------------------^

Future Action Effect -> Execution -> system SEND + Action SEND -> SafetyPolicy
                    -> VehicleCommandPort -> Vehicle plugin -> Protocol -> Transport
```

`contracts/` contains shared, vehicle independent data and ports, including the
P1 time, geometry, observation, vehicle state, localization, world snapshot,
typed effect, and vehicle command contracts. `core/`
implements Action registration, Mission validation, and the guarded Execution
boundary. `application/` exposes use cases without a hardware port. `app/`
contains only the new status CLI. The remaining top level packages reserve
the target owner boundaries and contain no device implementation yet.

Core never imports a concrete vehicle, protocol, transport, CUADC application,
or `legacy/`. Mission validates registered Actions and vehicle capabilities;
it does not issue commands. Actions receive only a WorldSnapshot and parameters.
The P1 `VehicleCommandPort` is not wired to a root component. The existing
demonstration Execution gateway still uses its old Effect submission interface.

The demonstration Execution boundary defaults both SEND gates to false and
requires an injected SafetyPolicy. No policy or vehicle port is wired by the
root CLI.
The framework does not yet implement continuous command stopping, stale command
cancellation, a Mission scheduler, or physical link lifecycle. Those are
required before any real vehicle integration.

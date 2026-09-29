# V1 framework boundary

The root is a new, hardware disconnected framework. Its implemented path is:

```text
Application -> Mission validation -> registered Action contracts
WorldSnapshot --------------------------^

Future Action Effect -> Execution -> system SEND + Action SEND -> SafetyPolicy
                    -> VehicleCommandPort -> Vehicle plugin -> Protocol -> Transport
```

`contracts/` contains shared, vehicle independent data and ports. `core/`
implements Action registration, Mission validation, and the guarded Execution
boundary. `application/` exposes use cases without a hardware port. `app/`
contains only the new status CLI. The remaining top level packages reserve
the target owner boundaries and contain no device implementation yet.

Core never imports a concrete vehicle, protocol, transport, CUADC application,
or `legacy/`. Mission validates registered Actions and vehicle capabilities;
it does not issue commands. Actions receive only a WorldSnapshot and parameters.
The only root component that can call `VehicleCommandPort` is Execution.

The Execution boundary defaults both SEND gates to false and requires an
injected SafetyPolicy. No policy or vehicle port is wired by the root CLI.
The framework does not yet implement continuous command stopping, stale command
cancellation, a Mission scheduler, or physical link lifecycle. Those are
required before any real vehicle integration.

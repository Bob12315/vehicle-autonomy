# Vehicle Autonomy Framework

This repository now has a clean V1 framework root. The complete previous
CUADC 2026 application is preserved in [`legacy/cuadc_2026/`](legacy/cuadc_2026/).
Its relative source, configuration, tests, docs, and assets remain together.
Nothing in the new framework imports that archived tree.

## Current scope

The new root provides vehicle independent Mission and Action contracts,
registration and validation, a WorldSnapshot contract, and a guarded Execution
boundary. It has **no production vehicle adapter, Mission scheduler, Web UI,
camera process, flight controller connection, or server deployment** yet.
Those integrations will be added behind the defined ports. The old application
is not launched from the new root.

All vehicle sends are disabled by default. Execution requires system SEND,
Action SEND, and an explicit SafetyPolicy decision before it can submit to a
VehicleCommandPort. The root CLI is status only:

```bash
python -m app.main status
python -m unittest discover -s tests -v
```

See [architecture and current limits](docs/architecture.md) and
[migration policy](docs/migration.md). `legacy/cuadc_2026/README.md` describes
the archived implementation as it existed before this split.

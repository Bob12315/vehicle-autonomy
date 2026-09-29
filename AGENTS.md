# Development rules

The repository root is the new Vehicle Autonomy Framework. The previous
application, its tests, configuration, documentation, assets, and deployment
scripts are preserved under `legacy/cuadc_2026/` as one historical tree.

Read `README.md` and `docs/architecture.md` before editing the new framework.
Do not import from `legacy/` in root packages or move an old module into the
new runtime without reviewing its dependencies and safety behavior.

The new root has no production vehicle connection. Vehicle commands require
both system and Action SEND authorization and an explicit SafetyPolicy. Both
SEND gates default to false. Mission, Action, Web, perception, and intelligence
must not call a vehicle command port directly. Keep hardware access behind
Execution, Vehicle, Protocol, and Transport boundaries. Do not claim real
flight, server, or RKNN support from an interface or placeholder package.

Commit each completed stage after checking its relevant tests. Run legacy
tests from `legacy/cuadc_2026/` when changing the archived tree.

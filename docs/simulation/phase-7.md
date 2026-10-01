# Phase 7 single-command regression (2026-10-02)

Status: **three full suites passed**; stricter request-to-truth deadlines
passed in the third. Final completion audit subsequently passed; see [Phase 8](phase-8.md).

Entry: `./scripts/test_simulation_v1.sh`. It builds both SITL vehicles and the
Gazebo plugin in an owned output directory, performs isolated-port preflight,
runs unit tests and five physical scenarios: Copter full, explicit Copter
Land, Rover full, Copter faults, Rover faults. Default execution uses initially empty build outputs and all scenario
worlds, profiles, SITL EEPROM/state directories and command epochs are new.
No external build outputs are deleted. It launches only direct SITL binaries,
headless Gazebo and separate test Runtime processes; no real device or legacy
code is used.

The harness checks scenario exit status AND machine acceptance reports AND
manifest port/process cleanup. It records failures and not-run counts and
never turns a missing report into PASS. Core skip count is zero. Total and
per-stage deadlines are bounded; signal/timeout cleanup targets owned groups.
Fallback manifest cleanup validates PID start-time identity and PGID so a
reused PID cannot identify an unrelated process.

`tests/simulation/test_harness.py`: 8 tests passed, covering success/repeat,
intentional nonzero exit, timeout with child-process cleanup, Ctrl-C cleanup,
occupied-port selection, unique world epochs for repeated stage names,
reused-PID rejection and the CLI's deliberate failing
exit with a machine report. These tests exercise process behavior and reports,
not merely command construction.

Artifacts retain source revisions, tool versions, exact build and launch
commands, profiles/parameter paths, PIDs/PGIDs/start times, exit codes,
telemetry/truth, proxy injection timestamps and accepted command IDs. Model
ports and profile ports are modified together per free SITL instance.

An actual owned Gazebo/SITL startup was interrupted by the StageRunner's
five-second timeout. It returned nonzero, preserved the interruption error,
terminated both owned groups and released ports. Diagnostic PASS report:
`artifacts/simulation/cleanup-check-77c7e4e6/summary.json`.

First complete suite passed at `artifacts/simulation/suite-10a5d103/summary.json`
with 11 stages, five scenarios, 124 unit tests, zero failures, zero not-run
scenarios and zero core skips. Its build outputs began empty. A subsequent
world-epoch regression test increases the current count to 125.

## Required recorded runs

Two consecutive suites passed at `suite-10a5d103` and `suite-535c13b0`.
The second had 125 unit tests and five scenarios; all failure, not-run and
core-skip counts were zero. Both started with empty owned build outputs.
The second held TCP 5770 open throughout; every scenario selected TCP 5780
and the protected listener remained intact (`port-conflict.json`).

During final inspection, the Rover Stop and some Cancel/fault checks were
found to restart their physical timeout after command/state confirmation.
They now share a single deadline from the request, including the two-second
stable window. No numeric limit was relaxed. Rover normal runs now also
retain Runtime event logs. The third full run passed at `artifacts/simulation/suite-3ddd55b2/summary.json`,
with 125 unit tests, five scenarios, initially empty build output, and zero
failures/not-run/core skips. Rover request-to-truth stable Stop times were
2.50–6.31 s; Copter Cancel was 3.41 s and RTL including touchdown/disarm
was 26.52 s. Copter fault deadman/Cancel/shutdown/SIGTERM were 3.31–4.11 s.
All original numerical limits remain unchanged. Every scene manifest reports
released ports and no remaining owned process groups. The final audit must
run the complete suite again after the stage commit.

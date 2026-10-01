# Phase 1 frozen simulation scope

Implementation commit: `1b70db0`. The original scope record is
[scope-v1.md](scope-v1.md), written on 2026-10-01. This index was added during
the final audit to give every planned phase an explicit `phase-N.md` record.

Both TOML profiles validate vehicle type, localhost transport, per-vehicle
mode IDs, host clock domain, cadence/deadlines, and explicit SafetyLimits.
SEND is an explicit runtime authorization and is absent from profile files.
`simulation/scenarios/acceptance-v1.json` freezes physical acceptance targets.
The original takeoff/Goto/Stop/translation/rotation thresholds are unchanged.
Later velocity/frame checks add explicit requirements, not weaker tolerances.
Three profile unit tests verify valid configurations and reject foreign hosts,
mismatched Rover modes, extra frames and invalid freshness windows.

Commands: `python -m unittest tests.test_simulation_profile -v` and
`python -m unittest discover -s tests -q`. The final integrated suite contains
125 tests, zero failures/skips; per-run counts are retained in `unit.json`.
Profiles and thresholds were committed before the motion implementation.

Rover Goto stayed mandatory after source/protocol review. The Phase 4 protocol
trial and Phase 5 target-model truth runs subsequently closed that trial.
Static handler presence was not accepted as a physical success. Mode IDs,
axis semantics, safety limits and action evidence are in the original scope;
dependency versions and live logs are in the later stage manifests.

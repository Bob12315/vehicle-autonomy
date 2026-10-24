# Phase 3 development baseline

Branch: `feat/phase3-action-system`, from clean
`1d6de8296e4b727bbc74aabc42bdbfacb1e63902`.

The Phase 2 P3 ACK-injection defect was fixed in
`561e1785079eb1b678f1ac22463d6b0e7c8a2610`. The original conditional verdict
and failed injection evidence remain historical records; see
`../PHASE2_P3_ACK_INJECTION_REPORT.md` for two independently run real corrected
Plane cancel-window tests. The Phase 2 production controller baseline remains
`634c30b02bc7f7b94030e14c2899f3abd375c716`.

Before edits: 420 unit tests passed (40.725 seconds). The isolated
`.venv-migration` environment has pymavlink 2.4.49. Gazebo 8.15.0 and the three
owned SITL binaries are available. The independent ArduPilot checkout is only
read; no external source or installation is modified. ROS 2 Jazzy is available
through `scripts/with_ros2.sh`; use a separate worker, domain and loopback DDS.

The existing ActionSpec/Registry and basic Action stop barriers are reused.
A single standalone scheduler adds the four semantics without changing the
existing Mission scheduler. Application drivers own Execution compositions;
Action instances receive immutable state and emit typed effects only. Resource
claims are scoped by target; arm/mode/motion share a control conflict group to
match the existing single control Lease. Read queries have separate shared
claims. Uncertain physical effects retain claims even after terminal records.

Phase 3 acceptance must run through the Action API and independent Gazebo
truth. Existing direct-controller Phase 1/2 suites are additional regressions,
not evidence that the new Action chain works. Plane mode/target confirmation
does not mean arrival or stopping. No hardware, Mission Graph, autonomous AI,
Nav2 navigation or SLAM algorithms are developed here.

Raw baseline, environment probes, source hashes, preserved historical evidence
hashes and logs: `artifacts/phase3-actions/`. Stage 1 adds deterministic
registry/schema/lifecycle/resource tests; the complete suite passed 430 tests
(40.752 seconds). This stage is infrastructure, not Phase 3 acceptance.

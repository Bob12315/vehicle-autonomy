# Vehicle Autonomy Framework V1 — Simulation completion audit

Status: **Simulation Complete — PASS**. All mandatory gates are closed.
Audit date: 2026-10-02. Tested runtime baseline: `fcbbe46`.

## Evidence and phase history

| Phase | Commit | Evidence |
| --- | --- | --- |
| 0 environment audit | `3dae0d8` | [Phase 0](phase-0.md); motion/environment gate subsequently closed by live Phase 3/5 |
| 1 scope/profiles | `1b70db0` | [Phase 1](phase-1.md), [scope](scope-v1.md), unchanged original thresholds |
| 2 common fenced runtime | `f8801b2` | [Phase 2](phase-2.md), both SEND gates default false, single writer |
| 3 Copter physics | `6a3ec82` | [Phase 3](phase-3.md), two independent full runs and explicit Land |
| 4 Rover plugin | `564a6d7` | [Phase 4](phase-4.md), shared runtime and separate translator/state adapter |
| 5 target Rover model | `69ba51a` | [Phase 5](phase-5.md), two front driven wheels and two passive rear casters, repeated truth runs |
| 6 faults/recovery | `2cd9d56` | [Phase 6](phase-6.md), dual-vehicle deterministic and live fault matrix |
| 7 regression | `fcbbe46` | [Phase 7](phase-7.md), three full passing suites, deliberate failure/timeout/signal/port tests |
| 8 final audit | this audit commit | final clean-build suite, machine verification and this document |

Prior complete suites: `artifacts/simulation/suite-10a5d103/`,
`artifacts/simulation/suite-535c13b0/`, and
`artifacts/simulation/suite-3ddd55b2/`. All returned 0; every suite had five
physical scenarios and zero failed/not-run/core-skipped scenarios. Unit counts
were 124, 125 and 125 respectively; the added case verifies independent world
epochs when stage names repeat. The second suite preserved occupied TCP 5770;
all scenes used TCP 5780. The third verified stricter single request-to-truth
deadlines. Final suite `artifacts/simulation/suite-015782bd/summary.json` returned 0 with **125 unit tests, 11 stages, five scenarios, zero failures/not-run/core skips**. Its build directory began empty. Every scene reports released ports and no remaining owned groups. `artifacts/simulation/suite-015782bd/audit-verification.json` additionally checks original numeric limits, all request-to-truth Stop deadlines, runtime logs, revisions and unchanged contracts/legacy.

## Mandatory DoD mapping

| Gate | Evidence | Audit state |
| --- | --- | --- |
| One command from clean build, twice complete, own cleanup and trustworthy exit | `scripts/test_simulation_v1.sh`; empty owned build directories; suites above; manifests; 8 harness tests | passed |
| Both SEND/lease/session/deadline/Safety/unique-writer fences | deterministic tests for both kinds, live unauthorized/duplicate checks; final write guard | passed |
| Fresh state, stale/link/clock blocks, new session and no replay | source-clock tests, proxy physical faults, runtime/SITL restart reports | passed |
| All required Copter and target Rover motions including Goto | normal reports plus fault Cancel/deadman; independent fresh Gazebo truth | passed |
| Result + state + truth + bounded time; no core skips | unit/scene JSON; telemetry-confirmed stops plus stable truth; ACK-only commands need physical oracle | passed |

Final Copter/Rover Goto truth errors were 0.152/0.500 m, both below 0.75 m.
All connected Stop/Cancel/shutdown/deadman cases met the original 8 s bound
including stable truth. The final unit suite was independently rerun after
the full regression: 125 passed, zero failures/skips.

Important final logs: `artifacts/simulation/suite-015782bd/copter_faults/runtime.jsonl`,
`artifacts/simulation/suite-015782bd/copter_faults/proxy.jsonl`,
`artifacts/simulation/suite-015782bd/copter_faults/sitl.log`, and the corresponding Rover directories.
Copter uses external `iris_runway.sdf`/`iris_with_gimbal`; target Rover sources
are `simulation/worlds/rover_runway.sdf` and
`simulation/models/target_rover/model.sdf`. Exact run copies are in manifests.

## Vehicle actions

| Vehicle | Passed actions |
| --- | --- |
| ArduCopter | Connect, fresh VehicleState, GUIDED Mode, Arm, Disarm, Takeoff, Hold, Goto, ENU +X/+Y velocity, positive yaw, body forward, Stop, Cancel, RTL, explicit Land |
| Target Rover | Connect, fresh VehicleState, GUIDED Mode, Arm, Disarm, forward, reverse, left/right turn, left/right pivot, Stop, Goto, Cancel, deadman |

Mode/Arm/Disarm need ACK and a later matching state. Takeoff/Land command
receipts remain ACKNOWLEDGED; the physical scenario independently requires
fresh state, fresh truth, target height/ground contact and final disarm within
the deadline. Streamed targets have no ACK and require distinct transmitted
command IDs plus measured response. A late link close can leave an ACK-only
receipt UNKNOWN; it does not substitute for the scenario's physical result.

Latest prior normal metrics: Copter Cancel 3.41 s from request, RTL home/land/
disarm 26.52 s; Rover stable Stop 2.50–6.31 s from request, Goto truth error
0.473 m. Original bounds are 8 s Stop with a 2 s stable window, 0.15/0.10 m/s
Copter/Rover stop speed, 0.75 m Goto, 1.5 m takeoff ±0.35 m, Rover translations
≥1 m and signed turns/pivots ≥45°. No numeric bound was relaxed.

## Safety and robustness

All 18 plan rows are mapped in [Phase 6](phase-6.md). Both vehicle profiles
exercise TTL, authorization/lease gates, duplicates, ACK/state timeouts,
stale/future/wrong-domain data, deadman, queued cancellation, uncertain writes,
and missed/regressing clocks. Physical scenarios add telemetry drop/delay,
moving temporary/long disconnect, reconnect, old queue rejection, actual
Runtime/SITL process restart, normal shutdown, and actual SIGTERM during motion.
No old Effect resumes and no SEND/lease is restored by reconnect. Explicit
new run/lease/effect IDs are needed. Missing ACK never becomes success solely
because a mode state matches; no blind Arm retry is sent.

Connected zero-motion results require a later state and independent stable
Gazebo speed. **At transport loss the physical-stop outcome is UNCONFIRMED.**
ArduPilot may independently slow/stop, but software does not label a zero
setpoint delivered or a vehicle stopped without evidence. Runtime resets
fence old queues and statuses; ambiguous transmitted/ACK-only outcomes stay
UNKNOWN. Default `python -m app.main status` still reports disconnected and
`send_commands=false`.

## Process/build evidence

The script runs headless Gazebo, direct SITL binaries and owned Runtime test
processes. Per-run model/world/profile ports agree. It chooses a free instance
and creates unique world names and fresh SITL state directories. Only owned
process groups are terminated; fallback cleanup validates PID start-time
identity and PGID. Every passing manifest shows released ports and no remaining
owned groups. A real five-second scenario timeout preserved its failing exit
and cleaned Gazebo/SITL (`cleanup-check-77c7e4e6`). The deliberate CLI failure
returns nonzero with missing scenarios counted, not silently skipped.

Default builds use a new suite output directory and do not delete external
builds. Exact configure/build/launch commands, code revisions, PID/PGID/start
times, params, worlds, exit codes, runtime logs, trajectories and fault-proxy
logs are retained under each ignored artifact directory.

## Dependency/source inventory

- ArduPilot `b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`, local `COPYING.txt` identifies GPLv3.
- Installed plugin source fork `3ec51428fd43deb7b71137192ba16394b450d78e`, local `LICENSE.md` identifies LGPLv3; Iris model/resources remain in that external tree.
- Gazebo Sim 8.15.0, Python 3.12.3, pymavlink 2.4.49, pyserial 3.5; manifests/preflight/build logs record the environment.
- Target Rover primitive geometry is original. Official SITL_Models WildThumper at `25bc38ed8c6c0345840159a8cbc0b02781d52f3c` was read for control/channel conventions. Its 6WD assets/meshes were not copied into this project.

Contracts are unchanged from execution baseline `61827b0`; no separate contract
change was needed. The archived `legacy/` tree is unchanged. The prohibited
`/home/level6/uav_ws/cuadc2026/` tree and serial devices were not written/opened.
External tracked ArduPilot/plugin source diffs remain empty; normal generated
build/config/lock output is allowed and isolated build artifacts are retained.

## Remaining boundaries

- This certifies basic control for the pinned localhost speed-one SITL/Gazebo profiles and target model only; it does not certify real flight or driving.
- Source boot time is mapped to host monotonic time per epoch using a bounded local first-sample assumption. Excessive skew/regression fails closed. Hardware source-clock synchronization, network latency guarantees and accelerated simulation are unvalidated.
- Rover GPS origin is a per-epoch local tangent-plane projection bounded to 50 m; safety/motion tests use the smaller configured arena. A restarted SITL requires fresh state and new authorization. This is not SLAM, localization fusion or a general navigation system.
- Real frame/actuator calibration, sensor quality, production time/links, real braking and loss-of-link physical behavior need a separate hardware acceptance plan.
- Fixed-wing/VTOL, Camera/YOLO/LiDAR, VIO/SLAM/RTAB-Map/depth, LLM/Agent/planning, CUADC missions, Web/Gateway/server and STM32/MCP4725 are outside this round and remain unimplemented/unvalidated.
- Root default app remains disconnected. Simulation scripts explicitly authorize their own local vehicles; no production onboard profile is added.

Regression command: `./scripts/test_simulation_v1.sh`. Usage, environment and
reports are in [simulation README](README.md). Module maturity is updated only
for the evidenced scope in [V1 progress](../v1_progress.md).

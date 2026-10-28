# Web & Tool Agent V1 test report

Date: 2026-10-28. Initial HEAD: `a49b8b9`. No real hardware is opened or commanded.

## Baseline / Phase 0

* Isolated installation: `python3 -m venv --system-site-packages .venv` then
  `.venv/bin/python -m pip install -e '.[mavlink]' -r requirements-vision.txt`: PASS.
* `.venv/bin/python -m unittest discover -s tests -v`: **675 PASS**, 76.163 s,
  no skips. Log `/tmp/vaf-web-baseline.log` (ephemeral developer log).
* Architecture/audit committed before implementation (`99dd30d`).

## Phase 1

* `.venv/bin/python -m unittest tests.tool_agent.test_core -v`: **9 PASS**,
  2.511 s. Actual OS child processes and actual loopback HTTP. Covers parent
  SIGKILL cleanup, descendants, startup timeout, normal/abnormal exit, duplicate
  launch, context conflict, missing software/display, external process protection,
  credentials, replay fencing and disconnected-command rejection.
* These process fixtures are **not** ROS/Gazebo/SITL integration evidence.
* Initial existing Chrome smoke attempt failed because Playwright was absent
  from the new venv. Installed the repository's `test-browser` extra; rerun below.
* Full regression: **689 PASS**, 87.878 s (`/tmp/vaf-agent-phase1.log`). The
  loaded suite included 14 core/link cases; duplicate inherited test cases were
  then removed and the improved 9-case suite rerun (includes Agent SIGKILL).
* `.venv/bin/python -m tests.simulation.mission_ui_smoke --run-dir
  artifacts/phase4-mission/web-agent-phase1-smoke`: PASS in real Chrome, no JS
  errors, widths 1680/1280/1024/390, original Wait Mission succeeds, zero writer
  calls and both SEND defaults false. This is browser integration, not flight.

## Phase 2

* All six standard manifests validate; custom registration requires no UI code.
  Focused core/registry: **12 PASS**, 2.383 s. Full regression: **687 PASS**,
  76.948 s, no skips (`/tmp/vaf-agent-phase2-full.log`).
* Registry generated with the real local Jazzy wrapper, Gazebo plugin and
  repository-owned SITL binaries. `python -m tests.tool_agent.native_smoke
  --registry runtime/tool-agent-dev/registry.json --run-dir
  artifacts/phase4-mission/tool-agent-native-phase2` actually launches tools.
  Gazebo stats, ROS 2 graph observer and Rover SITL TCP listener: READY and
  clean owned shutdown. SITL listener readiness is not vehicle telemetry or flight.
* RViz2: GUI process actually RUNNING; **not READY** without live namespace TF.
  QGC: correctly blocked, missing trusted telemetry-only relay declaration.
* Complete native Nav2 binaries found in the isolated Phase 5 dependency tree.
  Repeated generator with `VAF_ROS2_ROOT=$PWD/artifacts/phase5-world-navigation/ros2-jazzy/root`
  and ran native smoke (`tool-agent-native-nav2`, `--tool nav2 --observe-s 15`).
  Nodes actually RUNNING; costmap reports missing `map`/`base_link` transform.
  **Nav2 READY not passed**; clean group shutdown observed. No navigation goal
  or vehicle command is sent by these checks.

Later phase results, final native evidence, deployment verification and remaining
limitations are recorded below as work completes.

## Phase 3

* New dashboard projection, per-field age/clock/disconnect checks and original
  Mission HTTP compatibility: **13 focused PASS**. Full suite **691 PASS**,
  79.056 s (`/tmp/vaf-agent-phase3-full.log`).
* `python -m tests.tool_agent.console_browser --run-dir
  artifacts/phase4-mission/tool-console-phase3-browser`: real Chromium/HTTP PASS,
  three fixture vehicle types show unknown telemetry correctly, 1440/1024/390
  widths, zero JS errors, zero writer calls. Screenshots visually inspected.
* `VAF_PYTHON=$PWD/.venv/bin/python .venv/bin/python -m
  tests.simulation.program_launch --kind rover --motion --run-dir
  artifacts/phase4-mission/tool-console-phase3-rover`: real signed SITL/Gazebo
  plus real Chrome PASS. Forward 0.357 m; turn 0.303 rad; release/stop verified;
  Goto error 0.272 m, return error 0.222 m. Default Action SEND rejected.
  QGC monitor drops inbound requests; clean owned groups and credentials cleanup.
* Read-only `tests.tool_agent.console_capture` verified `/console` against this
  live Rover and saved `dashboard.png`/`dashboard.json` in that run. This is
  actual vehicle telemetry, distinct from the fixture browser check.

## Phase 4

* Full suite **695 PASS**, 81.399 s. Targeted service/registry checks **7 PASS**,
  including two live Agents with distinct credentials. No vehicle Actions created.
* `tests.tool_agent.tools_browser` (run `tool-console-phase4-browser-final`):
  real Chrome -> HTTP -> Agent -> actual fixture child process. Launch, Ready,
  logs, profile save, stop, restart and disconnected/unknown states PASS;
  two actual instances, no JS errors or vehicle Actions. Desktop/mobile captures.
* `tests.tool_agent.deployment_smoke` (`tool-console-phase4-deployment`): separate
  backend and Agent CLI **processes**, authentication, launch, Agent SIGKILL,
  owned child cleanup, 5 s timeout, new boot reconnect and no automatic relaunch
  PASS. Logs checked for absence of either credential. This is localhost process
  deployment, not evidence of a second physical host/SSH deployment.
* `VAF_PYTHON=$PWD/.venv/bin/python .venv/bin/python -m
  tests.simulation.program_launch --kind copter --http-controls --run-dir
  artifacts/phase4-mission/tool-console-phase4-copter`: real signed Copter
  SITL/Gazebo HTTP controls PASS (modes, Arm/Disarm, takeoff, managed velocity,
  release/stop, Goto and ReturnHome). Independent physical checks and clean groups/
  credentials in `web-control-result.json`. No real hardware used.
* ROS health probes now use short-lived read-only rclpy workers, avoiding ROS CLI
  auto-daemon startup. Core/server remain ROS-free. Existing ROS daemons are not
  adopted or killed.

## Phase 5

* Full final suite **714 PASS**, 91.546 s. Workspace-specific **18 PASS**,
  plus registry/port checks **4 PASS**. Covers topology, required preflight,
  optional failure, data-availability retry, two Agents, shared in-flight launch,
  shared/manual baseline ownership, parallel HTTP conflicts, timeout, queued
  cancellation, disconnected ownership, durable settings, restart reconciliation
  and abandonment without cleanup claims.
* `tests.tool_agent.workspaces_browser` (`tool-console-phase5-browser-final`):
  real Chrome creates/saves/launches two actual process fixtures in dependency
  order, edits without replacing live instances, stops/cleans both, loads a
  preset, and renders desktop/mobile with no JS errors. Visually inspected.
* `tests.tool_agent.native_workspace` (`tool-console-phase5-native-workspace`):
  actual Gazebo + ROS observer READY; RViz GUI RUNNING without TF -> optional
  failure / DEGRADED. Explicit Workspace stop cleans all three owned cohorts.
  This is actual native software integration, not full navigation data readiness.
* Generated matching `rover-coupled` Profiles via `--coupled-rover` and ran
  `tests.tool_agent.coupled_workspace` (`tool-console-phase5-coupled`): actual
  Gazebo ArduPilot plugin + JSON Rover SITL -> both READY; read-only TCP receives
  unarmed Rover HEARTBEAT, ATTITUDE and GLOBAL_POSITION_INT. **Zero vehicle writes**,
  clean owned exit. Source worlds/models unchanged; fresh per-instance EEPROM.
* `tests.simulation.program_launch --kind plane --http-controls --run-dir
  artifacts/phase4-mission/tool-console-phase5-plane`: actual signed Plane
  SITL/Gazebo PASS, including Arm/Disarm, physical TAKEOFF, Guided turn, LOITER,
  RTL approach and actual AUTOLAND/disarm. No zero-speed Plane stop; clean groups/
  credential cleanup. Command requires `VAF_PYTHON=$PWD/.venv/bin/python` as above.

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

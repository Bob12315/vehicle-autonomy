# Web & Tool Agent V1 test report

Date: 2026-10-28. Initial HEAD: `a49b8b9`. No real hardware is opened or commanded.

Initial accepted implementation: **`17a4940f4f4a80494f152c9ce7dc2be1703eeb37`**.
Current-host development acceptance passes; unverified deployment/hardware scopes
are listed below. Machine-readable results, raw evidence paths/hashes and the
production-tree digest are in [evidence.json](web-tool-agent/evidence.json).

Follow-up: [three-vehicle Web UI acceptance](WEB_UI_THREE_VEHICLE_ACCEPTANCE.md)
tests real browser controls and native ROS2 Tool Agent operations for all three
vehicle types, fixes initial/switching Tool Context selection, and records a
fresh 724-test regression. Its separate evidence index identifies the updated
production tree; the phased evidence below remains the initial acceptance.

## Desktop startup/readiness follow-up — 2026-10-28

An operator using the plain Copter launcher reached an empty Tool Manager:
the optional Agent listener and Desktop Agent had not been started. Local
operator configuration now starts both with separate credentials, detected
software paths and the actual desktop session. RViz2 and QGC were launched
through the Web UI and their native, mapped main windows were verified.
RViz's operator-specific `viewer-only` profile checks its ROS node/window
availability; its description explicitly says Copter map/TF data is absent.
The standard data-qualified profile still requires live TF. QGC remains a
telemetry-only window with internal readiness unqualified.

This exposed a process-management defect: after a tool had already become
Ready, a later failed probe still applied the original startup deadline and
closed the running application. Startup completion is now latched privately
per instance. Subsequent readiness loss reports RUNNING/not-ready (or unhealthy
on probe errors), retains the owned process, and can recover. Tools that never
become ready still time out and clean their descendants; explicit Stop and
ownership rules remain unchanged. Probe exceptions cannot overwrite a concurrent
stop, and a recovered healthy/ready probe clears its previous probe error.

Validation: **725 unit tests PASS**, zero skips, 99.359 seconds
(`/tmp/vaf-desktop-full.log`), including actual process readiness loss,
probe exception, recovery and explicit shutdown. Native RViz2 and QGC main
windows remained mapped for more than 70 seconds, including readiness loss;
no vehicle actions or SEND changes occurred. Local operator evidence is in
`runtime/copter-desktop/runtime-check.json` and `tools-ready.png` (private local
runtime, not packaged source). The fixed speed-one simulation clock correctly
rejected stale state when GUI loading delayed simulation time; this change does
not relax vehicle freshness, authorization, leases or UNCONFIRMED semantics.
The simultaneous desktop-window session still observed stale Copter telemetry
after startup, including a warmed/headless retry. Desktop window lifecycle is
verified; continued vehicle-control readiness in that particular desktop
session is not accepted. Movement must remain blocked until fresh vehicle
evidence is restored. Earlier three-vehicle isolated simulation acceptance
does not qualify this concurrent desktop workload.

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

Later phases below supersede the early missing-data/readiness observations only
for the explicitly stated native software and input fixtures.

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

## Phase 6 — final acceptance

Environment actually used: Ubuntu 24.04.1 LTS, Python 3.12.3, Chrome
152.0.7977.64, Gazebo Sim 8.15.0. Complete isolated ROS prefix: RViz2 14.1.24,
Nav2 Controller 1.3.13, ros2cli 0.32.13. The framework server imports no ROS.

| Verification | Actual result / evidence directory under `artifacts/phase4-mission/` |
| --- | --- |
| Final full unittest suite | **724 PASS**, **0 skipped**, 92.625 s; `/tmp/vaf-agent-final-verified-unit.log` |
| Tool Manager browser -> backend -> Agent -> OS process | PASS; `tool-console-final-tools-browser`; launch/stop/restart, logs, saved Profile, versioned connection metadata, disconnect unknown; 0 JS errors |
| Workspace editor/dependencies/reconnect | PASS; `tool-console-final-workspace-browser`; 2 real fixture processes, save/edit without side effects, reverse cleanup, browser disconnect clears readiness while services stay live |
| Original Mission/Control presentation and HTTP serialization | PASS; `tool-console-final-original-ui-fixed`; original Wait Mission, continuation wire identity, SEND defaults and 4 responsive widths preserved; 0 writer calls |
| Separate backend/Agent processes, crash and backend restart | PASS; `tool-console-final-deployment`; live process survives backend restart, ownership UNKNOWN until pinned reconciliation, manual baseline survives Workspace stop, supervisor SIGKILL and Agent SIGKILL clean children, new boot does not auto-relaunch |
| Coupled Gazebo/JSON Rover Workspace | PASS; `tool-console-final-coupled`; both actually READY, passive unarmed Rover telemetry received, 0 writes, confirmed cleanup |
| Real native Nav2/ROS/RViz functional readiness | PASS **with synthetic input data**; `tool-console-phase6-ros-isolated`; six Nav2 lifecycle nodes active and NavigateToPose endpoint discovered, RViz receives live TF, 0 navigation goals / vehicle writes, confirmed cleanup |
| QGC real visible main window | PASS; `tool-console-phase6-qgc-visible`; mapped **1393×836** window PID belongs to the owned group; fresh XDG settings, dedicated one-way SITL relay; no hardware or Framework motion commands |
| Unified real vehicle + tools + Workspace + running Mission | PASS; `tool-console-final-unified`; signed Rover state and tool readiness share the same Web center; Agent SIGKILL cleans fixture, Wait Mission succeeds, vehicle stays connected/unarmed and deployment/system/Action SEND remain false |
| Fresh wheel deployment from `/tmp` | PASS; `tool-console-final-verified-wheel`; separate clean venv, imports from installed wheel, 3 CLI entries, static/config resources, real backend/Agent/Workspace lifecycle; no source-path import, ROS import or vehicle connection |

Final wheel SHA256:
`16573016df9ab171626cc1349d57f5f473e1c69fda0bf803bc1a041f8cbfdc8f`.
Production tree SHA256 (definition in evidence JSON):
`b4722a880164950cb628ad7c9cd7b8c8be0b8c17e0eb0d62148d356ad1a0cff8`.

### Implemented behavior and interfaces

* `/console` provides three-type Dashboard, existing Vehicle Control link,
  Tool Manager, Workspace editor/presets, logs/diagnostics and Settings.
  Fields unavailable/stale/foreign-clock/disconnected become unknown. Airspeed
  stays unknown because the current projection has no qualified source.
* `app/tools` owns outbound registration/heartbeat, distinct credentials,
  boot/sequence/TTL fences, validated redacted snapshots, idempotent commands,
  trusted manifests, process discovery/ownership and bounded output/resources.
  Supervisor pipe loss plus Linux pidfd/ownership-marker fallback handles crashes.
* `tools.operation`, `tools.configure`, `tools.integration`, `settings.context`
  and `workspace.*` use the existing HTTP authentication/CSRF/Host/Origin/request-ID
  framework. The integration contract is `vaf.tools.integration/1`, explicitly
  `vehicle_authority=false`. No browser argv/Shell/path upload or extra writer.
* Workspace definitions/results/reference ownership persist atomically, required
  dependencies preflight before launch, compatible in-flight starts deduplicate,
  shared/manual services survive other Workspace stops, optional errors degrade,
  stop/cancellation and restart reconciliation preserve unknown outcomes.
* Optional Tool flags now pass through all three existing simulation launchers;
  `--tool-data-dir` persists tool state separately from fresh Mission journals.
  The existing Action/Engine/Vehicle/World/Autonomy/Contracts packages are unchanged
  from the audit baseline. No new Mission Studio, hardware connection or motion
  authority was introduced.

### Final command inventory

All commands below were actually run using `.venv/bin/python -m`; each output
directory was new. Full invocations and generated registries are retained in the
raw evidence. Repeating requires a different `--run-dir`.

```text
unittest discover -s tests -v
tests.tool_agent.tools_browser --run-dir artifacts/phase4-mission/tool-console-final-tools-browser
tests.tool_agent.workspaces_browser --run-dir artifacts/phase4-mission/tool-console-final-workspace-browser
tests.simulation.mission_ui_smoke --run-dir artifacts/phase4-mission/tool-console-final-original-ui-fixed
tests.tool_agent.deployment_smoke --run-dir artifacts/phase4-mission/tool-console-final-deployment
tests.tool_agent.coupled_workspace --registry runtime/tool-agent-dev/registry-coupled-final.json --run-dir artifacts/phase4-mission/tool-console-final-coupled
tests.tool_agent.ros_ready --registry runtime/tool-agent-dev/registry-native-final.json --run-dir artifacts/phase4-mission/tool-console-phase6-ros-isolated
tests.tool_agent.qgc_window --qgc /home/level6/桌面/QGroundControl-x86_64.AppImage --run-dir artifacts/phase4-mission/tool-console-phase6-qgc-visible
tests.tool_agent.vehicle_tools --run-dir artifacts/phase4-mission/tool-console-final-unified
tests.tool_agent.wheel_smoke --run-dir artifacts/phase4-mission/tool-console-final-verified-wheel
```

Physical Rover/Copter/Plane commands and results are recorded in Phases 3–5.
They use only fresh owned loopback simulators and the existing authorization,
native confirmation and physical-stop/flight-continuation checks.

### Failures encountered and corrected

* New venv initially lacked Playwright; installed the repository's test-browser
  extra and passed actual Chrome checks. First no-build-isolation wheel attempt
  lacked setuptools; normal isolated PEP 517 build/install then passed.
* Early native Nav2 prefix lacked controller/bt/etc. binaries; the manifest
  correctly rejected it. Selected the already installed complete isolated prefix.
  Missing TF/map then correctly prevented readiness; later native tests supplied
  clearly marked synthetic data and verified true lifecycle readiness.
* Parallel independent process tests initially used identical command fixtures;
  the external-process guard correctly rejected a second owner. Isolated fixture
  identities instead of relaxing ownership. Readiness assertions now wait for the
  backend heartbeat, not only untransmitted local state.
* The first QGC window check saw Qt's 10×10 bootstrap window. Strengthened it to
  require a mapped main window at least 300×200 and a verified owned PID; rerun
  passed with 1393×836. Bootstrap observation is not used as main-window evidence.
* An original UI fixture intentionally had stale/no Plane world data but expected
  a normal LOITER hint. The test now additionally checks that stale mode/hint is
  unknown; the original continuation/SEND serialization assertions remain intact.
* Final hardening covers redirection credential leakage, malformed/replayed
  snapshots, orphaned result acknowledgements after backend restart, separate
  credentials, private audit rotation/failure admission, supervisor SIGKILL,
  namespaced Nav2 data inputs, and actual active-Mission isolation.

### Mock scope, unverified scopes and known limitations

* Unit fixtures and the editor/browser process fixtures are **not** native
  robotics/flight evidence. Native ROS/Nav2/RViz tests run actual binaries and
  RPCs but use **synthetic map/TF/scan/odom**, not real sensors or qualified
  vehicle localization. They submit no navigation Goal and grant no vehicle lease.
* Ubuntu 22.04/Python 3.10 runtime, another physical Agent host, actual SSH
  forwarding, ARM64 and systemd deployment were not available for this run.
  Agent code/manifest OS policy targets 22.04/24.04; the supplied Nav2 parameters
  were verified on Jazzy. Humble needs a compatible trusted Profile and separate
  validation. Follow deployment instructions on the target host and repeat native
  smoke/lifecycle/reconnect checks before acceptance there.
* Real vehicle Arm/movement, real sensor navigation, qualified flight and hardware
  control were neither attempted nor claimed. HardwareReadOnly and rejection of
  `hardware_controlled` remain unchanged. Telemetry VALID means data quality, not
  arming/flight/navigation readiness.
* QGC main-window launch and the real relay are verified; its internal telemetry
  UI readiness is **not** asserted, so the Tool remains RUNNING/ready=false.
  Connection queries for external programs return metadata and
  `connection_established=false`; existing remote-window focus and arbitrary
  third-party UI automation are unsupported. [Upstream AutoConnect settings](https://raw.githubusercontent.com/mavlink/qgroundcontrol/master/src/Settings/AutoConnect.SettingsGroup.json)
  and its [settings-group compatibility logic](https://raw.githubusercontent.com/mavlink/qgroundcontrol/master/src/Settings/AutoConnectSettings.cc)
  informed the isolated test settings; the user's saved QGC configuration was not
  changed. Reproduce the visible-window test with a known one-way relay to verify
  GUI behavior on another desktop.
* The default empty Gazebo/native SITL profiles are independent; optional
  `rover-coupled` is actually verified. Automatic coupled Tool Profiles for
  Copter/Plane were not added; their existing coupled simulation launchers passed
  physical control tests and now accept Tool channel flags. Tool-launched SITL
  alone does not qualify Framework ownership/signing. QGC, TF, maps and sensors
  must be genuinely configured before a complete preset can be READY.
* Trusted local profiles run as the OS user and are not a sandbox for malicious
  executables. QGC's telemetry-only declaration must refer to a real one-way relay;
  it is not a firewall around manually configured third-party links. Use a dedicated
  least-privilege account and user-service control groups for deployment. Deliberate
  process-group/ownership-marker escape is unsupported; cleanup uncertainty is
  retained, never advertised as confirmed stop.
* Snapshot refresh is authenticated polling (750 ms), matching the original HTTP
  stack; there was no preexisting WebSocket to reuse. Software version fields are
  declared Profile versions or explicitly unverified, never fabricated detections.
  Admission/state/history/log budgets are bounded and documented. Further work can
  add measured version adapters, broader OS/host CI, richer read-only diagnostics
  and verified per-environment profiles without changing the vehicle writer.

## Commits and operator verification

| Stage | Commit |
| --- | --- |
| Phase 0 audit/design | `99dd30d` |
| Phase 1 authenticated Agent/process ownership | `092adfc` |
| Phase 2 standard registry/adapters | `5891f1a` |
| Phase 3 Dashboard/control compatibility | `eeaa3bc` |
| Phase 4 real Tool Manager channel/UI | `93a9bc1` |
| Phase 5 persistent shared Workspaces/coupled Rover | `d4e762c` |
| Phase 6 final integrated qualification/hardening | `17a4940` |

The final report/evidence follow-up is documentation only. All changes are local
commits; no history rewrite or force push. Raw runtime state, credentials, wheel
venvs and large evidence remain ignored; the compact credential-free evidence
index is tracked. All test-owned backend/Agent/supervisor processes exited.

To verify personally: follow the concrete private setup in
[deployment](WEB_TOOL_AGENT_DEPLOYMENT.md), start the backend or the existing
read-only Rover launcher with `--tool-agents`/`--tool-data-dir`, start the matching
Agent in another terminal, open `/console` with the private browser token, and
inspect actual Dashboard/Tool/Workspace states. Stop/retry/reconcile only the
identified owned instances. The tool manifest and Workspace documents specify
which missing dependencies/readiness conditions must remain visible.

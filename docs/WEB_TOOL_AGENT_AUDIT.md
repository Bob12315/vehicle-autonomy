# Web UI & Tool Agent V1 — implementation audit

Audit started 2026-10-28, baseline `a49b8b9`; working tree was clean. The four
repository architecture baselines and AGENTS.md were read before implementation.
This document distinguishes current code from the requested extension.

## Existing implementation and reuse

| Area | Audited implementation | Decision |
| --- | --- | --- |
| Frontend | `app/web/static`, plain HTML/CSS/JS, no npm build; Action Lab `/`, Mission Studio `/studio`, manual control `/control` | Preserve existing routes; add `/console` with six views and link existing control |
| HTTP | `ConsoleServer`, bounded threads/requests, loopback, private bearer, Host/Origin/CSRF, mutation IDs and audit | Reuse HTTP security; outbound Agent HTTP uses separate per-Agent credentials |
| Realtime | HTTP polling, **no existing WebSocket** | Reconnectable authenticated snapshot polling; no new socket framework |
| Vehicle status | `MissionControl._snapshot`, `vehicle_display`, immutable WorldModel and telemetry fields | Add an age-aware dashboard projection; stale values must be null |
| Control | `MissionControl._manual_action`, `_idle`, managed input sessions; server deadman, explicit per-Action SEND | Reuse unchanged authority/Guard/Adapter/Execution chain; no Agent vehicle API |
| Mission/Action | Typed registry, graph runtime, resource journal and restart fences; mature three-vehicle bindings | Keep compatibility; no new Mission Studio |
| MAVLink | Owned SITL manifest, signing, expected vehicle identity, unique writer, telemetry-only QGC mirror | Only operator-provisioned receive-only QGC connection profiles |
| Processes | `SimulationProvisioning`, QGC simulation Session, explicit native navigation groups | Existing purpose-specific ownership cannot safely become a generic remote shell; new bounded supervisor |
| ROS | Explicit external workers/wrappers; local Jazzy extraction and optional Humble environment | No ROS imports in Core/Agent server; read-only CLI health probes in isolated child groups |
| Simulation | `gz` in PATH; three SITL binaries under ignored artifacts; existing simulation fixtures/harnesses | Run available real tests, record exact commands; never substitute historical reports |
| Packaging/tests | Installable seven-package src layout, setuptools, unittest, optional Playwright | Add Agent entry point within app; no eighth core package |

Initial environment: Ubuntu host; `/opt/ros` absent, `ros2` absent from ordinary
PATH, local Jazzy environment present. Presence of files is not installation or
readiness proof. Tool availability is measured later in the test report.
An isolated `.venv` is being installed with the required editable/MAVLink/vision
dependencies. No legacy or independent project is modified.

## New/modified modules

New `app/tools` owns manifests, adapters, local process supervision, outbound
Agent client, backend registry/mailbox, Workspace planning and persistence.
New Web console views use these APIs. Existing Mission HTTP service gets an
optional Tool service attachment; no imports into engine/vehicle control.
Trusted deployment JSON owns executable paths, argv, file paths, probes and
profiles. Browser payloads can select registered IDs and validated context,
never submit commands, environment variables, manifests or filesystem paths.

## Risks and compatibility

* Remote lifecycle commands require per-Agent identity, boot epoch, ordered
  heartbeat and bounded command expiry. Retry cannot duplicate a process.
* A disconnected Agent is unknown, not stopped or healthy; Mission runs
  independently. Agent loss must not revoke a Mission or send vehicle commands.
* Only owned child groups may be stopped. Discovered external programs remain
  observation-only. Parent death and descendant cleanup need actual process tests.
* ROS/Gazebo GUI presence is not connection/readiness. Missing desktop,
  dependencies, lifecycle endpoints and data must be represented separately.
* QGC is a separate control application. The console permits a QGC profile only
  when the trusted Agent deployment explicitly declares a telemetry-only relay;
  existing framework mirror drops inbound commands. This is not a sandbox of QGC.
* Nav2 service management must not activate another MAVLink writer. Its cmd_vel
  stays on an isolated tool namespace and readiness grants no Action authority.
* Workspace services require reference ownership; failure/stop/retry must not kill
  another Workspace's service or silently reuse an incompatible vehicle context.
* Preserve private tokens, SEND defaults, receive-only hardware, UNCONFIRMED
  stopping, Lease/TTL/session/generation fences and original HTTP contracts.

Audit complete before source changes. Actual results and remaining limitations
are maintained in `WEB_TOOL_AGENT_TEST_REPORT.md`.

# Web UI & Tool Agent V1 architecture

The existing Vehicle control chain remains authoritative:

```text
Browser /control -> MissionControl -> ActionRuntime -> Execution
 -> Authority + Safety + dual SEND + Lease/TTL/session/generation -> sole writer

Browser /console -> authenticated backend -> Agent mailbox / Workspace manager
                                ^
                   outbound authenticated HTTP heartbeat
                                |
                    independent Tool Agent (app/tools)
                     -> trusted Manifest + Profile
                     -> owned supervisor -> external software
```

The two paths share vehicle context, not vehicle command ports. Tool readiness
does not grant control authority or imply physical navigation/flight readiness.

## Transport and identity

Reuse stdlib HTTP/JSON and authenticated full snapshot polling. The backend and
Agent listener channel bind loopback. SSH local/reverse forwarding provides
cross-host encryption and host authentication without fixed Agent IPs or root.
Each allowlisted Agent has its own private token, distinct from the browser
token. Agents initiate registration/heartbeats, publish a boot ID and increasing
sequence, and consume idempotent commands pinned to that boot with finite TTL.
Unexpected old boots, stale/replayed sequences and conflicting live registrations
are rejected. Backend restart requires fresh registration and full state sync;
no queued commands are replayed from disk. Agent reconnect preserves owned
processes while the Agent is alive; Agent death cleans its own process groups.

## Registry and process model

Agent-side trusted JSON supplies a versioned Tool Manifest and named profiles.
Adapters inspect executable/file/dependency availability, GUI session, process
ownership and bounded read-only health probes. Standard RViz2, QGC, Gazebo,
Nav2, ROS 2 and SITL entries are shipped; unavailable launch inputs stay missing.
Custom tools register through the same schema with no frontend changes.

Browser operations carry only tool/profile IDs and typed VehicleContext. Each
tool has one active compatible instance per Agent; incompatible context/profile
requires an explicit stop. Start, health and stop have separate state. A private
supervisor owns a new POSIX process group, streams bounded logs, kills descendants
on exit or Agent death, and returns cleanup evidence. Process discovery never
confers ownership. No shell=True, browser argv, path interpolation or root service.

## Workspace model

Versioned saved Workspaces contain vehicle context, named components, Agent,
tool/profile IDs, dependency IDs and optional flags. Validation rejects cycles,
missing dependencies and duplicate incompatible assignments. Launch is async:
preflight all required components, then start in dependency order after readiness.
Reference sets protect compatible services shared by multiple Workspaces. Stop
releases only that Workspace's references; external/manual ownership is preserved.
Failed required components block dependents; optional failure is reported as
degraded. Explicit retry reacquires failed components; no automatic vehicle action.
Saved configurations and bounded run history persist atomically outside packages.
After backend restart, old runs are unknown and require explicit reconciliation;
they are never silently relaunched or stopped.

## UI and deployment boundaries

`/console` provides Dashboard, Vehicle Control link, Tool Manager, Workspaces,
Logs and Settings. Dashboard nulls stale or disconnected measurements and names
the selected vehicle, authority, Mission, health and simulation scope. Original
`/`, `/control`, `/studio` and API routes remain compatible. No map/point-cloud
viewer or new Mission graph editor is added.

Deployment is user-level Ubuntu 22.04/24.04, Python >=3.10. Trusted local profiles
and tokens are configured by the operator, never supplied by the browser. Optional
ROS runs only in launched workers. Native readiness, GUI rendering and third-party
internal UI linkage are verified separately; absent evidence stays unknown.

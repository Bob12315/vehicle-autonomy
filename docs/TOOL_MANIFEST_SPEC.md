# Tool Manifest schema 1

An Agent starts with a trusted local registry JSON: `{"schema":1,"tools":[...]}`.
The browser cannot upload or edit executable profiles. `app/tools/schema.py` is
the executable validation contract. Tool IDs and profile IDs are bounded ASCII
identifiers, unique per Agent. Unknown fields and vehicle-command permissions
are rejected.

Each Tool declares `schema`, `id`, `name`, `type` (gui/service/simulation),
`version` (declared profile version, not an observed software version),
`supported_os`, `dependencies`, `install_detection`, `profiles`,
`stop_strategy=owned_process_group`, `integrations`, `agent_requirements` and
`permissions`. Supported OS entries are `ubuntu-22.04`, `ubuntu-24.04` or `linux`
for a portable custom test tool. Dependency kinds: executable/file/directory/
environment. File/directory paths are absolute trusted deployment inputs.

A named profile contains:

```json
{
  "argv": ["/absolute/executable", "fixed-argument"],
  "env": {},
  "health": {"argv": ["/absolute/read-only-probe"], "contains": ["HEALTHY"], "timeout_s": 2},
  "ready": null,
  "connection": {"kind": "none", "description": "No readiness probe configured"},
  "startup_timeout_s": 20,
  "stop_timeout_s": 3
}
```

Optional `cwd`, `requires`, `observe_only` constrain a profile. Empty argv is
allowed only for an observation-only profile. Probe argv is trusted code, must
be read-only, and runs in a bounded temporary process group. Never put secrets
in argv, errors or process stdout. Environment values and launch argv are not
published to the browser. Logs are bounded but are visible to authenticated
operators; use token files instead of printing credentials.

Connection metadata can additionally declare a trusted `endpoint`, with the same
typed namespace/domain expansion as argv. `/api/tools/integration` takes
`{agent_id,tool_id,profile_id}` through the authenticated operator API and returns
`protocol=vaf.tools.integration/1`, Agent boot, instance, context, connection,
readiness and `vehicle_authority=false`. This lets an existing integration inspect
service availability; it cannot replace the Action/Execution admission path.

Optional `exclusive_ports` contains up to eight `{protocol:"tcp"|"udp",port:N}`
loopback simulator reservations. Busy ports block launch without stopping any
external process; they do not turn an installed program into uninstalled. The
check is repeated before spawn. Default working directories are fresh per Tool
instance, so simulator EEPROM/artifacts never silently cross vehicle profiles.

Optional Tool `process_names` lists exact executable basenames for applications
such as AppImage that re-exec with a different name. Otherwise discovery matches
trusted argv prefixes, not every process sharing an interpreter. Owned process
groups are excluded. Unknown external profile/context is never assumed compatible.

`vehicle-autonomy-tool-registry` generates six standard entries. ROS environment
capture is explicit via `--ros-wrapper`; the Core process never sources ROS.
The default Gazebo profile is an isolated empty lab; native SITL profiles are
separate simulators, **not a coupled vehicle physics environment**. For coupled
ArduPilot/Gazebo control use the existing validated simulation launchers, or
operator-provisioned matching world/FDM/port profiles. The manifest does not
promise automatic third-party UI configuration.

Only `{namespace}` and `{domain_id}` in argv are expanded from validated context.
`ROS_NAMESPACE` and `ROS_DOMAIN_ID` are injected as typed context; there is no
shell, arbitrary expression, browser path, or browser environment expansion.
Profiles are administrator-level trusted programs, not a sandbox for hostile code.
Tools that daemonize/escape the owned process group are unsupported.

Process state, `service_health`, `ready` and `connection` are independent. A live
process with no readiness probe stays RUNNING/ready=false/connection=UNKNOWN.
A failing configured readiness probe times out and cleans the owned group.
Disconnected Agent state is unknown and does not assert the tool has stopped.
External processes are reported with PIDs for observation only, never killed.

QGC requires a trusted connection with `telemetry_only=true` and the corresponding
permission. This declaration must refer to an actual one-way relay (the existing
Framework telemetry mirror is suitable). It is not a software firewall around
QGC's other manually configured connections. RViz connection/readiness refers
only to its configured ROS graph/data checks, not to a qualified vehicle pose.

## Browser operations

`launch`, `open`, `stop`, `restart`, `check`, `connect` take only registered
Agent/Tool/Profile IDs and VehicleContext. `open` can launch an absent GUI on its
Agent desktop; focusing an existing remote window is explicitly unsupported.
An operation's SUCCEEDED result means the lifecycle request was accepted;
observe the Tool's separate running/ready state for actual startup.

`connect` is an observation/connection-metadata query for an external process;
it explicitly returns `connection_established=false`. It does not manipulate a
third-party application's internal UI or acquire that process's stop ownership.

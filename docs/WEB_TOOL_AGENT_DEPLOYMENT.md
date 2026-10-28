# Web console & Tool Agent deployment

Ubuntu 22.04/24.04, user-level Python >=3.10. Native GUI/ROS dependencies must
match the host distribution/architecture. No sudo, package installation, hardware
motion or default vehicle connection is performed by either service.

## Install and prepare

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -e '.[mavlink]' -r requirements-vision.txt
install -d -m 700 runtime/operator runtime/desktop-agent
```

On the backend, create `runtime/operator/agents.json` with **absolute** token
paths (replace the example path with your actual private directory):

```json
{"schema":1,"agents":{"desktop":{"token_file":"/absolute/private/desktop.private"}}}
```

Tokens are generated on first startup as owned 0600 files. Pre-create token
parent directories as 0700. Keep browser and Agent tokens different. Transfer
only that Agent's token to its host using an authenticated secure channel; never
put token contents in command arguments, committed files or URLs.

```bash
.venv/bin/vehicle-autonomy-console --port 8780 \
  --token-file runtime/operator/web.private --data-dir runtime/operator/state \
  --tool-agents runtime/operator/agents.json --tool-port 8791
```

Open `http://127.0.0.1:8780/console`; paste the browser token. With no simulation
arguments the Dashboard accurately has no vehicle and SEND stays off. Original
Action Lab `/`, control `/control`, Mission `/studio` and their APIs are preserved.
This release does not add a Mission editor.

For existing explicitly owned SITL, use the original `--simulation TARGET=MANIFEST`
assembly and its signing/provider registry prerequisites. Add `--allow-send` only
when intentionally authorizing that owned simulation deployment; each control
still requires separate Action SEND. Do not attempt to use a Tool-launched native
SITL as a trusted Framework vehicle without the original ownership/signing setup.

## Configure a host and run its Agent

Generate a **new**, trusted local registry (existing files are never overwritten):

```bash
.venv/bin/vehicle-autonomy-tool-registry \
  --output runtime/desktop-agent/tools.json \
  --ros-wrapper scripts/with_ros2.sh \
  --sitl-dir artifacts/phase2-control/ardupilot-source/build/sitl/bin
```

Omit unavailable options. `--ros-wrapper` explicitly captures only ROS runtime
environment keys from that local script; no ROS is imported into the backend.
For a separately installed environment, source it before generation or use its
trusted wrapper. Set `VAF_ROS2_ROOT` only for the repository's isolated Jazzy
wrapper. Review generated paths and profiles before enabling the Agent.

QGC additionally needs `--qgc /absolute/QGroundControl.AppImage --qgc-relay
/absolute/relay.json`. Relay JSON must contain `telemetry_only:true` and a
description of an **actual** one-way telemetry relay. The existing simulation
launchers' QGC mirror drops all inbound messages and is suitable. Never substitute
a writable AP/GCS endpoint. The Agent does not change QGC's saved internal UI
connections; isolate/review those settings separately. Merely writing this JSON
does not create a relay.

```bash
.venv/bin/vehicle-autonomy-tool-agent --id desktop --name 'Operator desktop' \
  --role desktop --backend http://127.0.0.1:8791 \
  --token-file /absolute/private/desktop.private \
  --registry runtime/desktop-agent/tools.json --data-dir runtime/desktop-agent/state
```

Run GUI Agents from the actual desktop session with its DISPLAY/WAYLAND_DISPLAY
and session credentials. Headless hosts correctly refuse GUI launch. No remote
desktop/window streaming or existing-window focus is promised. Tool Manager can
launch/stop/restart, observe external processes, inspect dependencies/connections,
save Profile selections and show bounded logs/resources. Only system-owned
groups can stop; external instances are observation-only.

## Cross-host transport

Agent always initiates the connection. On the Agent host, create an authenticated
SSH forward to the backend (replace the backend hostname/account):

```bash
ssh -N -L 8791:127.0.0.1:8791 operator@backend-host
```

Then use the same loopback Agent command. No fixed Agent IP or inbound Agent
port is required. Agent identity remains its allowlisted ID/token across network
changes. For a remote browser similarly forward 8780. **Keep the local forwarded
port equal to the backend port** because strict Host/Origin checks intentionally
reject another authority. Do not expose these stdlib HTTP listeners directly to
the network or remove those checks. Production traffic uses SSH encryption.

For persistent deployment use a user-level systemd unit with explicit absolute
ExecStart paths, `NoNewPrivileges=yes`, `KillMode=control-group`,
`TimeoutStopSec=25` and `Restart=on-failure`; load desktop environment only for
Desktop Agents. State/registry/token files belong to the user, not site-packages.
Each running backend/Agent needs a different private state directory.

## Lifecycle and recovery

Agent heartbeats every 0.5 s; backend declares unknown/disconnected after 5 s.
Commands expire after 10 s, bind to Agent boot identity, and are deduplicated.
Tool state separates process, service health and functional readiness. A live GUI
without TF/connection remains RUNNING, not READY. Startup timeout cleans owned
groups; Agent exit/crash closes supervision pipes and cleans descendants. Tools
that deliberately escape their process group/daemonize are unsupported; use
systemd control groups for stronger OS containment.

Backend/SSH loss does not stop a live Agent's tools or affect Mission authority.
No fresh command is accepted for an offline Agent. Reconnection sends a complete
snapshot. Agent restart gets a new boot, does not restore old processes or queued
launches, and is admitted only after the old boot times out. Tokens can be revoked
by removing/rotating the allowlist entry and restarting the listener. State and
audit are private, bounded and separate from the Python packages.

The default Gazebo lab and native SITL profiles are independent. Coupled vehicle
physics, TF/maps/sensors, GUI connection configuration and third-party Action
binding require matching trusted deployment profiles. No launch or Workspace
operation arms/moves a vehicle, imports optional ROS into Core, or creates another
vehicle command writer.

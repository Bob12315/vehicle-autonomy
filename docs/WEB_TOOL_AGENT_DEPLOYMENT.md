# Web console & Tool Agent deployment

Targets Ubuntu 22.04/24.04, user-level Python >=3.10; this run was actually
validated on Ubuntu 24.04.1 / Python 3.12.3. Native GUI/ROS dependencies must
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

For a concrete checkout-local setup (run once; existing configuration is not
overwritten):

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from vehicle_autonomy.app.web.server import load_token
root = Path('runtime/web-tools').resolve()
root.mkdir(parents=True, mode=0o700, exist_ok=True)
load_token(root / 'web.private')
load_token(root / 'desktop.private')
with (root / 'agents.json').open('x') as stream:
    json.dump({'schema': 1, 'agents': {'desktop': {
        'token_file': str(root / 'desktop.private')}}}, stream, indent=2)
print('Private configuration directory:', root)
PY
.venv/bin/vehicle-autonomy-tool-registry --output runtime/web-tools/tools.json \
  --ros-wrapper scripts/with_ros2.sh \
  --sitl-dir artifacts/phase2-control/ardupilot-source/build/sitl/bin \
  --ardupilot-plugin /home/level6/gz_ws/src/ardupilot_gazebo/build/libArduPilotPlugin.so \
  --coupled-rover
```

The dependency paths above are this developer host's existing installations;
replace/omit unavailable options on another host. For its complete Nav2 prefix,
set `VAF_ROS2_ROOT=$PWD/artifacts/phase5-world-navigation/ros2-jazzy/root` for the
registry-generation command. The ordinary local ROS prefix contains only a
subset of Nav2. Software/profiles with missing dependencies stay unavailable.
QGC needs the additional actual relay/profile setup described below.

```bash
.venv/bin/vehicle-autonomy-console --port 8780 \
  --token-file runtime/operator/web.private --data-dir runtime/operator/state \
  --tool-agents runtime/operator/agents.json --tool-port 8791
```

For the concrete configuration above (no vehicle attached):

```bash
.venv/bin/vehicle-autonomy-console --port 8780 \
  --token-file runtime/web-tools/web.private --data-dir runtime/web-tools/operator \
  --tool-agents runtime/web-tools/agents.json --tool-port 8791
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

To use the **same center with an actual owned vehicle** through an existing
launcher (Rover shown; Copter/Plane accept the same optional arguments):

```bash
./scripts/start_rover_sim.sh --headless --read-only \
  --tool-agents runtime/web-tools/agents.json --tool-port 8791 \
  --tool-data-dir runtime/web-tools/persistent-tools
```

Open `http://127.0.0.1:8780/console`, using the **simulation launcher's printed
token-file path**; it provisions its own private Web token. Start the Agent in a
second terminal:

```bash
.venv/bin/vehicle-autonomy-tool-agent --id desktop --role desktop \
  --token-file runtime/web-tools/desktop.private \
  --registry runtime/web-tools/tools.json --data-dir runtime/web-tools/agent-state \
  --backend http://127.0.0.1:8791
```

Do not run another backend on those same ports.
The explicit `--tool-data-dir` persists Workspaces across fresh simulation Mission
journals without weakening their vehicle-identity fences. No arm/motion is sent.

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

For an actual coupled Rover add `--coupled-rover --ardupilot-plugin
/absolute/libArduPilotPlugin.so` and the explicit SITL directory. The generator
creates new deployment world/model files and matching `rover-coupled` Profiles;
Simulation Lab selects them on one Agent. Source models/worlds are never edited.
This prepares Gazebo JSON FDM + native SITL, with port collision checks and fresh
EEPROM directories. Framework vehicle admission and QGC relay remain separate
explicit prerequisites, not inferred from a listening simulator socket.

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
`TimeoutStopSec=45` and `Restart=on-failure`; load desktop environment only for
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

A killed private supervisor is also handled: per-instance inherited ownership
markers and Linux pidfds identify only its actual children, then cleanup is
confirmed before reuse. Unknown cleanup remains UNKNOWN and blocks restart.
Audit write failure blocks new launches; owned shutdown/supervisor cleanup is
independent of a healthy audit stream. Rotation preserves private 0600 files. Distinct per-Agent and Web
credentials are enforced; the Agent refuses HTTP redirects or inherited proxies.

Backend/SSH loss does not stop a live Agent's tools or affect Mission authority.
No fresh command is accepted for an offline Agent. Reconnection sends a complete
snapshot. Agent restart gets a new boot, does not restore old processes or queued
launches, and is admitted only after the old boot times out. Tokens can be revoked
by removing/rotating the allowlist entry and restarting the listener. State and
audit are private, bounded and separate from the Python packages.

Nav2 reads the selected vehicle's namespaced map/odom/scan/TF and exposes its
isolated `/vaf_tools` services. `/api/tools/integration` returns versioned endpoint,
boot, instance and context metadata with `vehicle_authority=false`; it does not
bind a new navigation Action or grant an Execution lease.

The default Gazebo lab and native SITL profiles are independent. Coupled vehicle
physics, TF/maps/sensors, GUI connection configuration and third-party Action
binding require matching trusted deployment profiles. No launch or Workspace
operation arms/moves a vehicle, imports optional ROS into Core, or creates another
vehicle command writer.

## Workspace operations

Open Workspaces -> Create -> load a preset or select registered components.
Select Agent/Tool/Profile, dependencies, optional flag and running/ready threshold,
then save. Launch freezes the saved context. Progress and errors come from Agent
results; retry handles failed components, Stop respects shared/baseline ownership.
Editing a saved definition leaves running instances unchanged. See
[Workspace contract](WORKSPACE_SPEC.md) for recovery, dependency and readiness
semantics. After backend restart, inspect concrete instance IDs and explicitly
resume records or release them without claiming process cleanup.

# Hardware-Ready deployment and diagnostics

2026-10-21. This release provides an **onboard receive-only application**, an
authenticated console and simulation/sensor/LLM validation tools. Physical
vehicle control is intentionally unavailable. The authoritative results and
missing software/hardware gates are in [HARDWARE_READY_AUDIT](HARDWARE_READY_AUDIT.md).

After the user's physical connections, the actual RS16 network/ROS/PCAP chain
and an isolated ARM64 Humble/Nav2/SLAM prefix were installed and tested. The
current configured launcher is `scripts/onboard-connected.sh`; use
[the connection setup](HARDWARE_CONNECTION_SETUP.md) for its state directory,
observed device addresses, limitations and commands. Sections below preserve
the initial empty-source template and initial deployment history.
The revised Web UI now owns mission/status functions; spatial views use
RViz2. See [ROS tool workflow](ROS2_OPERATOR_WORKFLOW.md) for viewer launchers,
local-only DDS scope and the still-unimplemented hardware control adapters.

## Installed board and lifecycle

Authorized board: `pi@192.168.50.2`, NanoPC-T6 / RK3588, aarch64, Ubuntu 22.04,
Python 3.10. The new installation is `/home/pi/vehicle-autonomy/`, outside the
existing CUADC installations. Versioned source archives, offline ARM64 wheels
and a separate `venv --system-site-packages` preserve the system and existing
applications. Passwords and console tokens are never in Git. Deployer checks
existing SSH host keys and records archive/wheel hashes.

```bash
cd /home/pi/vehicle-autonomy/current
export VAF_PYTHON=/home/pi/vehicle-autonomy/venv/bin/python
./scripts/onboard.sh start --llm-config config/llm.server-tunnel.json
./scripts/onboard.sh status
./scripts/onboard.sh stop
```

The stack supervises only its own application and console. Child failure stops
the stack; restart is explicit and always read-only with a new epoch. Logs and
PID/start-time identities are in `~/.local/state/vehicle-autonomy/`. Application
and audit logs rotate at 2 MB with three backups; unexpected child stderr is
limited to 4 MB before stack shutdown. No boot autostart or system services
are installed. Stopping the process does **not** establish physical Stop.

From the PC, expose the console only through SSH:

```bash
ssh -NT -L 127.0.0.1:8765:127.0.0.1:8765 pi@192.168.50.2
# Open http://127.0.0.1:8765
ssh pi@192.168.50.2 'cat ~/.local/state/vehicle-autonomy/token'
```

Paste the private token into the page. It stays in page memory, not a URL or
cookie. The HTTP API requires Bearer authentication; mutations additionally
require a custom CSRF header and matching Host/Origin. Console binds loopback,
has bounded request sizes and workers, and writes operation audits. Browser
HTTP protection relies on the SSH tunnel; no public control listener is used.

`config/deployment/{simulation,hardware-readonly,hardware-controlled}.json`
separate the deployment modes. Both SEND values must be exactly `false`.
The hardware-controlled template is **rejected even with SEND false** until a
separately reviewed control composition and onsite acceptance exist.
Simulation uses the original `app.main run --profile rover_sim` entry and its
existing loopback-only Safety/Execution/writer chain.

## Sensor and telemetry configuration

The hardware-readonly template deliberately leaves unknown sources `null`.
Copy it outside the versioned release before supplying discovered devices:

```json
{"telemetry":{"path":"/dev/serial/by-id/ACTUAL_DISCOVERED_DEVICE","baudrate":115200},
 "camera":{"kind":"v4l2","path":"/dev/videoACTUAL","fps":5},
 "lidar_exchange":"/absolute/private/directory/cloud.json"}
```

Merge these fields into the complete schema; these are examples, not detected
hardware facts. The serial receiver sends no MAVLink heartbeat, stream-rate,
mode, parameter or motor request. It requires an ArduPilot Rover heartbeat and
shows received GPS/EKF/attitude facts with source identity, boot regression,
GPS jump/quality and age diagnostics. Physical source capture time is unknown;
it is never treated as qualified control localization. Missing telemetry rates
must be configured by a human through an established maintenance process.

Camera inventory is read-only. Explicit capture uses a separate bounded worker
and a single latest JPEG. Sensor exposure/capture time, intrinsics/extrinsics and
device-level dropped-frame count remain unknown; displayed drop counts describe
preview processing. Recorded video is labelled `recording`; it is not physical
camera evidence. Late/dead workers cannot supply a fresh preview or stall the
application. Physical camera projection into WorldModel requires real
calibration and the existing perception contract; this release does not invent it.

## Official RS16 adapter

The separately fetched [official rs_driver](https://github.com/RoboSense-LiDAR/rs_driver)
is pinned to `897b14d3bdb6186a75df27ba51b65b5bd5557723`. The build copies the
vendor's BSD license into the output. No SDK source is moved into generic Core.

```bash
./scripts/build_rs16_adapter.sh /official/rs_driver /new/private/build-dir
```

On the board the reviewed checkout is in `vehicle-autonomy/vendor/rs_driver`
and the ARM64 binary in `vehicle-autonomy/rs16-build/rs16_capture`. The adapter
requires the **observed** host address, MSOP/DIFOP ports, a finite duration,
private output path and new epoch:

```text
rs16_capture HOST_IP MSOP_PORT DIFOP_PORT SECONDS /private/cloud.json NEW_EPOCH [PCAP]
```

It only receives SDK packets, requires DIFOP calibration and never configures
the sensor or NIC. No-input exit code is 3, never hardware PASS. PCAP is compiled
only when `pkg-config libpcap` is available; the board build currently disables
PCAP. Official PCAP semantics: [vendor guide](https://github.com/RoboSense-LiDAR/rs_driver/blob/897b14d3bdb6186a75df27ba51b65b5bd5557723/doc/howto/10_how_to_decode_pcap_file.md).
A real recording including required DIFOP packets is still needed for an
end-to-end decode acceptance. Do not manufacture a packet fixture and call it
real hardware evidence.

Optional ROS 2 sidecar, on a configured ROS host:

```bash
./scripts/with_ros2.sh python -m integrations.ros2.rs16_scan \
  --config config/rs16-scan.json --health-file /tmp/rs16-health.json
# Native same-host SDK exchange -> PointCloud2 + LaserScan:
# add --exchange /private/cloud.json
# rosbag replay (recording only): add --replay and play with ros2 bag play BAG --clock
```

Input topic defaults `/rslidar_points`, native-exchange output `/vaf/lidar/points`,
scan `/vaf/lidar/scan`, frame `lidar`. Unknown bins are NaN in ROS and `None`
inside the immutable typed Observation; they are never free space. Configurable
height, explicit lidar-frame body box and ground band filters need installation
measurements. No default lidar-to-base transform is invented. Both raw and scan
capture times retain provenance; stale/future, reordered, empty, oversized,
wrong-frame and wrong-epoch data are rejected. The cloud monitor records gaps.

The initial release did not install ROS. The connected increment now provides
isolated ARM64 Humble, with runtime tests in the connection setup. PC Jazzy 2.8.5 SLAM native libraries
must not be copied to ARM64/Humble. See [official ROS platform information](https://repo.test.ros2.org/en/humble/Installation/Alternatives/Ubuntu-Install-Binary.html).

## Navigation, mapping and collision limits

The existing PC GPS/telemetry ENU navigation and Nav2/map-following regression
remain simulation-only. Hardware read-only diagnostics expose two independently
blocked modes: GPS has no accepted source timing/origin/geofence; LiDAR Map has
no qualified physical map/TF/localization. SLAM candidates remain diagnostic,
never active control. There is no hardware navigation-mode switch or resume.

The new near-field collision monitor supplies conservative stop/slowdown
recommendations and rejects missing forward coverage, stale scans and failed
localization. `deployment.collision_guard.ScanWriteGuard` can be explicitly
injected into the existing simulation writer with an admitted base_link scan
reader; offline writer tests reject sudden obstacles after queue admission and
preserve the original Stop path. It conservatively rejects reverse/turning and
requires upstream guidance to lower speed; it cannot mutate a command or grant
authority. **No default or hardware composition installs this guard, and no live
Nav2 obstacle layer is configured.** Real dynamic avoidance, physical braking, motion-mode
switching and complete scan-to-stop hardware fault injection remain unimplemented
or unqualified. Ordinary GPS is not precise local obstacle-avoidance localization.

The console saves content-addressed adopted maps and exports PGM/YAML. Loading
is a **read-only preview**, never map activation or SLAM relocalization. Map
clicks save draft waypoints only; they cannot execute arbitrary coordinate
motion. Execution accepts explicitly registered missions through Application.
Restart/relocalize/re-anchor and authorize a new task before future mode changes.

## Server LLM

Actual server: `bob@10.10.12.240`, observed llama-server loopback `11436`, observed
model alias `coder390-q6`. Existing server services are unchanged. The configured
adapter uses an authenticated SSH tunnel, not a guessed public API:

```bash
# PC terminal 1:
ssh -NT -L 127.0.0.1:19436:127.0.0.1:11436 bob@10.10.12.240
# PC terminal 2, to let the board reach that private tunnel:
ssh -NT -R 127.0.0.1:19436:127.0.0.1:19436 pi@192.168.50.2
```

These tunnels must remain alive; they are not persistent services. The board
has no observed default route and cannot be assumed to reach the server
directly. `config/llm.server-tunnel.json` records only the observed endpoint/model.
The adapter also supports explicitly configured Ollama chat JSON. API keys, if
required by another deployment, are read from a named environment variable.

LLM output is strict bounded MissionProposal JSON, restricted to registered
missions. No code, raw Effects or MAVLink is accepted. Proposals expire after
60 s, bind session/environment, require human confirmation and cannot replay.
Approval in this release is limited to an authorized simulation Application;
hardware startup is rejected. The hardware console catalog is empty. Model
timeouts run outside the cancellation lock and do not participate in the local
vehicle/safety loop.

## Reproduction and source evidence

```bash
# PC, full framework units (no skipped tests):
python -m unittest discover -s tests -q
# PC, unified mandatory simulation gates (exact original run: isolated checkout of 9750c50):
VAF_SIMULATION_SITL_BIN_DIR=/absolute/reviewed/sitl/bin \
  ./scripts/test_hardware_ready_simulation.sh --allow-send --run-dir /tmp/vaf26-NEW
# Explicit synthetic ROS software test, never a real RS16 claim:
./scripts/with_ros2.sh python -m integrations.ros2.rs16_scan \
  --config config/rs16-scan.json --health-file /tmp/scan-test.json --self-test
# Board, separately declared non-Gazebo deployment unit profile:
PYTHONPATH=. /home/pi/vehicle-autonomy/venv/bin/python scripts/test_onboard_readonly.py \
  --report /tmp/onboard-tests.json
```

The full recursive discovery was also attempted on the initial board release;
it failed in PC-only harness/Gazebo dependencies. That failure is preserved,
not rewritten as PASS. The separate board profile runs all root test modules
except the Gazebo Oracle, with zero skips; PC P26 retains the full simulation
gate. The board does not need to host Gazebo/SITL to run diagnostics.

Additive redeployment from the PC uses existing known SSH host keys and prompts
for a password without storing it:

```bash
python scripts/deploy_readonly.py --host 192.168.50.2 --user pi \
  --wheelhouse artifacts/hardware-ready/wheels --evidence-dir artifacts/hardware-ready/deploy-NEW
```

A deployment updates the new installation's `current` symlink but does not
start processes. Stop the old read-only supervisor, deploy, then explicitly
start the new version. Source commits, archives and wheel hashes are recorded.

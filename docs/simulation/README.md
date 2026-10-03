# Vehicle simulation acceptance

From the framework root, run:

```bash
./scripts/test_simulation_v1.sh
```

This headless local acceptance suite builds both speed-one SITL binaries and
the Gazebo plugin, checks dependencies, prepares checksum-pinned public vision
assets, runs actual CPU YOLOX acceptance and all unit tests. It tests both App
processes, named environments, finite Actions, repeated routes, mission faults,
simulation objects, CUADC business missions, a recorded visual replacement,
Copter full motion/Land, Rover full motion and both physical fault suites. Every
normal command goes through typed Effects, Execution, Safety, both SEND gates,
a scoped lease, the vehicle translator, and the sole MAVLink writer. Gazebo
truth is a read-only test Oracle. The script is the explicit authorization to
send commands to its own localhost simulations. No serial device is opened.

Exit **0** means every selected mandatory gate passed; any failure, timeout,
interruption, missing report, or cleanup failure returns nonzero. Core tests
have no skip/xfail. A failed early gate reports the number of scenarios not run
and preserves its diagnostic logs. The suite does not certify real hardware.

## Environment

- Python 3.12 with pymavlink, pyserial, Gazebo transport13/msgs10 Python bindings.
- Optional vision dependencies in `requirements-vision.txt` are required by the
  full visual suite (tested OpenCV 5.0.0 CPU); no GPU/Torch/RKNN is required.
- ArduPilot source at `/home/level6/ardupilot`, tested `b5fbe26515`, submodules and SITL build dependencies installed.
- Gazebo Sim 8.15.0 and development libraries, `gz`, `cmake`, compiler toolchain.
- Plugin source/models/worlds at `/home/level6/gz_ws/src/ardupilot_gazebo`, tested fork `3ec5142`.

Fresh build outputs live in each suite's `build/` directory, not in the
external build directory. Each default execution builds from empty output.
`--build-dir <directory>` explicitly selects another owned output; an existing
one is configured/checked and incrementally built. The summary records whether
the build directory was initially empty. Waf may update its normal generated
configuration/lock files in its source tree. The suite never runs clean,
deletes an external build, or modifies archived CUADC code.

Gazebo/SITL worlds and state directories are fresh for every scenario. A free
instance in 1..99 supplies matching TCP and JSON ports; each copied model,
world and runtime profile uses those ports. Occupied ports are preserved.
The launcher directly starts the SITL binary, avoiding instance-zero
sim_vehicle process cleanup. The suite does not need a GUI or GPU display.

## Reports and controls

The script prints the run directory. Its `summary.json` includes stage/scenario
counts, exit codes, unit-test counts, core skips (zero), and acceptance paths.
Each scenario retains a `manifest.json`, `summary.json`, runtime events,
telemetry/truth trajectory, Gazebo and SITL logs. Fault runs also retain
original-frame proxy RX/TX logs and separate Runtime process restart reports.
Build logs stay in the suite directory. All artifacts are ignored by Git.

```bash
./scripts/test_simulation_v1.sh --run-dir /absolute/new/run-directory
./scripts/test_simulation_v1.sh --timeout 3600
./scripts/test_simulation_v1.sh --inject-failure  # intentionally exits nonzero
```

Total timeout defaults to 3600 seconds; build and scenario stages also have
bounded deadlines. Ctrl-C/SIGTERM terminates the owned scenario, which attempts
bounded authorized Stop, then cleans its own process groups even after failure.
A fallback targets only live PIDs with recorded start-time identity and PGID.
No unrelated process or occupied listener is killed. Cleanup checks both
released ports and remaining process groups.

## Scope and evidence

See [frozen scope](scope-v1.md), [Phase 3 Copter](phase-3.md),
[Phase 5 Rover](phase-5.md), [Phase 6 faults](phase-6.md), and
[Phase 7 regression](phase-7.md). The original Rover model has two powered
front wheels and two passive rear caster assemblies. No visual/mesh assets
were copied from the official 6WD reference. Physical loss-of-link stop is
**UNCONFIRMED**; later reconnect never restores an old command or authorization.
Only connected stops with new telemetry and stable Gazebo truth are confirmed.

## Autonomy and recorded visual acceptance

The P9–P15/P17 software regression at `artifacts/simulation/suite-3501a226/`
passed all 29 stages and 21 scenarios, including both routes twice, two CUADC
business runs, Rover inspection, object disappearance, stale/cancel/reconnect
and recorded visual substitution. Its initial unit gate ran 173 tests; the
final source/queue/shutdown checks ran 177 with zero failures/errors/skips.
All scenario manifests confirm released ports and no remaining process groups.
The full run reused the owned build from `suite-e8ba09fa/build` (configured
and incrementally rebuilt), so it is not described as an empty-directory build.

```bash
python -m pip install -r requirements-vision.txt
python scripts/prepare_vision_fixture.py
./scripts/test_simulation_v1.sh --build-dir artifacts/simulation/suite-e8ba09fa/build --timeout 3600
```

The asset preparation downloads a public YOLOX ONNX model and bus photograph
only when absent, verifies pinned SHA256 values, then creates a finite virtual
recording/calibration and provenance.json. They stay under ignored artifacts;
missing dependencies/network/assets cause failure, never a core skip. The
photo is a virtual texture, and the bus-to-bucket mapping is a fixture rule.
It does not establish field calibration or competition target recognition.

For additional recorded-camera cancellation and corrupted-input acceptance,
use the same owned build paths:

```bash
export VAF_SIMULATION_SITL_BIN_DIR="$PWD/artifacts/simulation/suite-e8ba09fa/build/ardupilot/sitl/bin"
export VAF_SIMULATION_PLUGIN_DIR="$PWD/artifacts/simulation/suite-e8ba09fa/build/gazebo-plugin"
python -m tests.simulation.vision_faults --allow-send
```

`vision-faults-7c8b79f6` passed both checks without payload release and with
confirmed Stop/revoked SEND, then explicit recovery landed/disarmed. This is
an additional acceptance run outside the 21-scenario summary. The final visual
normal repeat at `autonomy-copter-a584ef0a` also passed. See the
[autonomy completion audit](../autonomy/completion-audit.md) and
[P17 scope/evidence](../autonomy/phase-17.md). P16 hardware remains deferred.

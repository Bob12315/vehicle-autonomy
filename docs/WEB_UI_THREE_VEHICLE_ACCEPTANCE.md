# Three-vehicle Web UI acceptance — 2026-10-28

**PASS for local owned simulations.** Real Chromium operated the real Web UI,
authenticated Tool Agent and signed ArduPilot/Gazebo simulations separately for
Rover, Copter and the twin-Cessna Plane. No hardware was opened or commanded.
Machine-readable summaries and SHA-256 references to local raw evidence are in
[three-vehicle-ui-evidence.json](web-tool-agent/three-vehicle-ui-evidence.json).

## Results

| Vehicle | Browser operations verified | Physical result |
| --- | --- | --- |
| Rover | Modes, Arm/Disarm, held forward/reverse/turn, release to stop, Stop, Goto, ReturnHome | Forward 0.510 m; reverse 0.407 m; turn 0.426 rad. Final home error 0.268 m; disarmed and stationary. |
| Copter | Modes, Arm/Disarm, Takeoff, held forward/yaw, release to hover, Goto, ReturnHome/landing | Takeoff 1.495 m; translation 0.509 m; yaw 0.419 rad. Final home error 0.004 m; landed, disarmed and stationary. |
| Plane | MANUAL, Arm/Disarm, Takeoff, SetGuidedTarget, Loiter, RTL, AutoLand | Climbed 49.053 m; physically turned and approached home within 120 m under RTL. AutoLand completed on the runway, disarmed and stationary; final distance from initial position 78.410 m, cross-track 0.064 m. |

Plane acceptance uses its existing runway tolerance (within 80 m of the initial
home position and 15 m cross-track), not precision landing at home.
Loiter retains flying speed; the test requires more than 7 m/s rather than
treating fixed-wing stop as zero-speed hover. Final landing requires independent
Gazebo ground height within 0.25 m and speed below 1 m/s, plus signed disarmed
telemetry. Rover and Copter release checks require actual linear/yaw stopping
within the established limits: Rover 0.1 m/s and 0.1 rad/s; Copter 0.15 m/s
and 0.15 rad/s.

For **each** vehicle, Tool Manager launched, inspected Connection/Logs, restarted
and stopped the installed native ROS2 graph observer. Readiness required discovery
of its actual namespaced ROS node. Restart required a different live PID and
confirmed exit of the old PID; Stop required process exit. Vehicle IDs/types,
ROS namespaces and separate domains 114/115/116 were checked. Tool operations
created no vehicle actions and left both SEND gates false.

Each UI rejected Arm without individual SEND authorization and emitted no
command result. Authorized operations used the existing Action/Execution/Safety
path. Vehicle verification used read-only HTTP state and an independent Gazebo
pose subscriber; tests never used a vehicle command port or Gazebo publisher.
All three final states were disarmed with both SEND gates false, no JavaScript
errors, no remaining owned simulator process groups, no cleanup errors and
removed temporary Web/signing/Agent credentials. Source input hashes were checked.

## Fix and regression

First connection to a Copter-only backend reproduced an actual UI defect:
selected vehicle `copter`, but Tool Context vehicle/type remained `rover`.
Automatic selection and type-filter changes now bind the tool context to the
selected vehicle, just as explicit selector changes do. A configured ROS
namespace is preserved when selecting the same vehicle. Running tools and
missions retain their existing contexts.

* Full unit suite: **724 PASS**, zero skips, 94.994 seconds.
* Context browser regression: all three type filters, correct context fields,
  widths 1440/1024/390, zero vehicle writer calls and zero JavaScript errors.
* Existing tool browser regression: launch/stop/restart, profile save and
  disconnected/unknown handling; zero vehicle actions. This additional regression
  uses an OS process fixture; native ROS evidence is the three cases above.
* Acceptance harness preparation included an interrupted warmup and an early
  Rover run that attempted to edit the UI's intentionally fixed Goto Z field.
  Those attempts were not counted as passes and cleaned their owned resources.
  The final runs validate the fixed value instead and pass the complete paths.

## Reproduce

Install the repository's simulation/browser prerequisites and generate a trusted
registry with a working native `ros2` profile as described in
[deployment](WEB_TOOL_AGENT_DEPLOYMENT.md). Then run each case serially with a
new output directory; for example:

```bash
.venv/bin/python -m tests.simulation.program_launch --kind rover \
  --tool-registry runtime/web-tools/tools.json \
  --run-dir artifacts/phase4-mission/ui-rover-new
.venv/bin/python -m tests.simulation.program_launch --kind copter \
  --tool-registry runtime/web-tools/tools.json \
  --run-dir artifacts/phase4-mission/ui-copter-new
.venv/bin/python -m tests.simulation.program_launch --kind plane \
  --tool-registry runtime/web-tools/tools.json \
  --run-dir artifacts/phase4-mission/ui-plane-new
.venv/bin/python -m unittest discover -s tests -v
```

The acceptance harness uses the existing one-click scripts and explicitly
authorized owned simulations, a separate authenticated Agent CLI, real UI
buttons/keys and the existing physical checks. It removes its temporary Agent
credential after shutdown. Local raw evidence is under
`artifacts/phase4-mission/web-ui-three-types-20261028-*-final*`; each vehicle has
masked tool/control screenshots and physical state logs.

## Qualification limits

This run qualifies registered tool lifecycle operations and existing vehicle
Actions on this host's local simulations. Native ROS graph observation does not
qualify vehicle sensor fusion, Nav2 vehicle navigation or QGC internal telemetry
readiness; their previous explicit limits remain in the
[V1 report](WEB_TOOL_AGENT_TEST_REPORT.md). Real vehicles remain HardwareReadOnly,
and hardware_controlled remains rejected. Neither real flight nor production
hardware control is claimed.

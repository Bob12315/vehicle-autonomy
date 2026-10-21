# V1 framework boundary

This page describes the **implemented root**. The reusable framework's full
target responsibilities and dependency rules are in [Vehicle Autonomy Framework
V1: target architecture](framework_v1.md).

## Explicit onboard diagnostics and operator console (2026-10-21)

`app.hardware` composes a separate `HardwareReadOnlyRuntime`, bounded sensor
workers and receive-only Rover telemetry. It constructs no VehicleCommandPort,
ControlAuthority grant or MAVLink sender. Unknown serial/camera/lidar sources
remain null; capture time and physical Stop remain unknown. The controlled
hardware profile is rejected before opening devices. Python 3.10 uses an
isolated tomli backport; framework Core and frozen foundation contracts are
unchanged.

`app.web` injects the existing Unix Application client into OperatorService.
The HTTP listener is loopback-only with a private Bearer token, custom CSRF
header, Host/Origin checks, bounded workers/requests, operation audit and
non-evicting mutation IDs. Session-checked start is evaluated inside one
Application event-loop request. Original CLI start semantics remain available.
The console cannot submit Effects or obtain a vehicle writer. Following the
operator's revised workflow, the Web UI owns mission selection, status, camera,
logs and AI proposals; RViz2 owns spatial visualization. The former map/click/
save controls are removed from the Web page. Existing map-preview/draft APIs
remain compatibility use cases and never grant localization or authority.
Read-only RViz profiles publish no navigation goals. Full Nav2 control-candidate
and RViz-goal admission adapters remain unimplemented for hardware; see
[ROS 2 operator workflow](ROS2_OPERATOR_WORKFLOW.md).

LLM adapters return strict MissionProposal JSON, restricted to registered
missions. Approval is finite, human-confirmed, one-shot and session/environment
bound; this release allows execution only through an authorized simulation
Application. Hardware remains read-only. Remote inference does not hold the
operator cancellation lock or participate in the vehicle cycle.

`MissionDesign` extends proposals with up to eight registered mission references.
Application pins session/environment/capability configuration, rechecks admission
on approval, and owns bounded sequential execution. Each child follows the existing
Mission/Action/Effect chain; fresh disarmed stationary observations and released
SEND/Lease authority are required between children. No unqualified localization
candidate is promoted. Only explicit simulation compositions expose this use case.

The explicit `yard` composition adds Schema 2 parameters for registered drive,
turn, circle, wait and named-point visit capabilities. Application resolves the
whole design once against a fresh, session-bound axle pose and known static
scene. The approved preview is immutable; approval expires after 60 seconds and
requires pose continuity. Typed maneuver Actions publish Effects only; the
existing writer has an additional rejection-only path/scene/swept-footprint
guard. This qualified target_rover fixture uses its front axle reference and
cannot be enabled on an unqualified kinematic profile. Default training fences
and Core/contracts are unchanged. This is not live obstacle avoidance or a
hardware-control adapter. See [scenario guide](LLM_TASK_DESIGN.md).

The official pinned rs_driver adapter writes bounded same-host diagnostic
cloud envelopes. An optional ROS sidecar produces PointCloud2/LaserScan and
immutable Observation data with explicit provenance and frame/time checks.
No physical mount transform or hardware clock qualification is inferred.
`ScanWriteGuard` is an explicit rejection-only adapter for the existing writer;
it has offline queue/fault tests, but no default/hardware scan-control or live
Nav2 obstacle-layer composition. Real GPS/map navigation and physical braking
remain unqualified. [Audit](HARDWARE_READY_AUDIT.md) records current failures;
historical P21–P25 PASS does not override the new P26 FAIL.

The root has no automatically opened hardware connection. Its implemented path is:

```text
Application -> Mission compilation -> typed Action runtime -> Effect requests
WorldReader --------------------------------------^

Fake Sensor + Fake Vehicle -> OfflineStateChain -> WorldModel -> WorldReader

Typed Effect -> offline VehicleExecution -> system SEND + Action SEND
             -> ControlAuthority + SafetyPolicy -> FakeVehicleCommandPort

Explicit ArduCopter composition -> VehicleExecution -> ArduPilotCommandPort
                             -> MAVLink codec -> TCP byte transport -> local SITL

Explicit P6 run-sitl -> loopback TCP receive -> WorldModel -> typed Mode Action
                     -> Effect result feedback -> VehicleExecution -> same sole writer

Explicit dual-vehicle SimulationRuntime -> VehicleExecution + Safety/Authority
    -> Copter/Rover translator -> same MAVLink writer -> TCP -> SITL -> Gazebo
Gazebo truth -> read-only test Oracle (no production control input)

Explicit Copter STABILIZE diagnostic -> VehicleExecution -> ArduPilotCommandPort
                                    -> MAVLink codec -> serial byte transport -> USB controller

Explicit bare Copter bench diagnostics -> VehicleExecution -> ArduPilotCommandPort
                                       -> MAVLink codec -> serial byte transport -> USB controller

Explicit Rover HOLD diagnostic -> VehicleExecution -> ArduPilotCommandPort
                              -> MAVLink codec -> serial byte transport -> USB controller
```

`contracts/` contains shared, vehicle independent data and ports, including the
P1 time, geometry, observation, vehicle state, localization, world snapshot,
typed effect, and vehicle command contracts. `core/`
implements Action registration, Mission compilation/runtime, TransformTree,
the P4 offline control boundary, and the older demonstration Execution
gateway. `application/` exposes use cases without a hardware port. `app/`
contains the disconnected status CLI and explicit loopback SITL entries.
`sensors/`, `vehicles/`, `localization/`, and
`world_model/` contain P2 offline fake sources, a pure reported-pose projection,
and a World Model that publishes immutable snapshots. `vehicles/multirotor/`
normalizes received ArduPilot telemetry and translates approved commands;
`protocols/mavlink/` packs/parses messages; `infrastructure/transports/` owns
only TCP/serial byte I/O. The P5 `ArduPilotCommandPort` is the sole writer in
these explicit compositions. It holds the authority lock across the final
fence and transport write, and the session receiver handles heartbeat, ACK and
state observations.
`ArduPilotSession` requires an expected MAVLink vehicle type and ArduPilot
autopilot heartbeat before granting a link session. Separate narrow USB
diagnostics expose only Rover HOLD-to-HOLD or Copter STABILIZE-to-STABILIZE;
neither exposes arm, takeoff, or motion. Separate bare-controller bench
translators limit requests to STABILIZE/ACRO modes or Arm/Disarm/STABILIZE.
`deployment/CopterCycleDriver` connects receive, P4 deadman, and queue drain
when explicitly scheduled by a caller; the CLI does not schedule it.
`deployment/SitlRuntime` is the P6 single-process scheduler for an explicit
`run-sitl` CLI invocation. It validates the loopback-only profile before
connecting, publishes a WorldSnapshot each cycle, runs one unarmed Mode Action,
and maps Effect IDs to command statuses. A final write guard rechecks the
disarmed state and freshness; the SITL translator permits only the configured
mode. The Action sees read-only results and succeeds only after ACK plus a
later heartbeat and a fresh WorldSnapshot reporting the target mode. `status`
still opens no connection; both SEND gates default to false, and `run-sitl`
requires `--allow-send` to authorize one Mission lease.
The separate `run-sitl-arm` entry requires both `--allow-send` and `--allow-arm`
before connecting. Its three-step Mission confirms GUIDED mode, Arm, and
Disarm in order. Each step receives a newly scoped lease. The final SITL
translator accepts only Mode, Arm, and Disarm; a write guard checks the
disarmed target mode before Arm and an armed state before Disarm. On an armed
failure or cancellation, the coordinator attempts one fenced Disarm with a
bounded confirmation wait. Link loss and unknown Arm outcomes are reported
unconfirmed. This is simulation-only evidence, not real vehicle arming or
physical stop validation.

Core never imports a concrete vehicle, protocol, transport, CUADC application,
or `legacy/`. Mission validates registered Actions, typed parameters and vehicle
capabilities; it does not issue commands. Actions receive only a WorldSnapshot
and parameters and emit unapproved Effect requests.
The P1 `VehicleCommandPort` is used by P4/P5 `VehicleExecution`, with either
the fake port or the ArduCopter port injected. The older demonstration gateway
still uses its old Effect submission interface.
P2 state producers and `WorldModel` have no vehicle command port. The World
Model computes freshness from captured/received/published monotonic facts in
one clock domain, omits stale or unknown inputs from the adopted snapshot, and
retains input versions as dependencies. It preserves source frames. The
separate TransformTree resolves explicit static and dynamic frame relations;
the World Model does not implicitly convert them.

P4 `ControlAuthority` defaults both SEND gates to false. The new Execution
boundary requires an explicit `VehicleSafetyPolicy`, one scoped lease, and an
active link session; its fake queue rechecks generations, lease, deadline, and
session immediately before simulated transmission. Continuous commands have
a caller driven deadman and explicit StopMotion request. Accepted, transmitted,
ACK, and observed completion remain distinct; a disconnected stop is
unconfirmed. The root CLI wires no command port or production vehicle link.
P5 maps StopMotion to zero velocity and yaw rate in the active stream frame;
only a later fresh zero-motion state sample marks it complete. Link timeout
creates a new session and fences queued commands; uncertain transport writes
and missing ACKs remain `UNKNOWN`. The local Copter SITL smoke test exercised a
single unarmed GUIDED mode request and ACK. A separate USB Rover controller
diagnostic received HOLD ACK and a later matching heartbeat while disarmed.
A Copter USB controller diagnostic received STABILIZE ACK and a later matching
heartbeat while disarmed. The controller also reports a frame class/type
pre-arm error, so this result is not flight readiness.
The USB state publication uses receive time as a diagnostic proxy; source
capture time is unknown. Those USB diagnostics do not validate real physical stopping, motion or
link-loss behavior. The narrow P6 runtime still uses a loopback receive-time
proxy. The shared simulation runtime separately maps source boot time per
epoch and validates Copter/Rover motion and faults against Gazebo truth;
real-device capture timing and physical stopping remain unvalidated.
Heartbeat-based VehicleHealth does not establish sensor calibration or arming
readiness.
With a temporary Quad X frame configuration, the USB Copter completed a
disarmed STABILIZE/ACRO/STABILIZE round trip. Its pre-arm checks rejected Arm;
an explicit Disarm was confirmed. The original undefined frame configuration
was restored and reboot verified. No physical output or flight was tested.

## Dual-vehicle simulation composition

`deployment/SimulationRuntime` shares Execution, Authority, codec, session and
the sole command port between Copter and Rover. Vehicle differences are the
injected translator, reported-state adapter, profile and explicit safety
policy. Rover projects MAVLink GPS global origin/state into bounded local ENU
and rejects flight effects and sideways/vertical body motion. Root packages
do not import archived modules. No vehicle connection opens on import.

Callers explicitly connect, schedule at 10 Hz and begin a run. Both SEND gates
and lease default disabled; `allow_send` explicitly grants one scoped run.
Source boot timestamps are mapped to host monotonic time only for the pinned
localhost speed-one composition. Repeats/delay preserve sample age; clock
regression/skew, stale state, link loss, missed cycles and uncertain writes
close the link and revoke authority. Reconnect creates a fresh codec/session/
world epoch and requires a new authorized run; no old queue is replayed.

Stop/deadman/cancel/shutdown request zero velocity through the same writer and
require a later state to confirm it. Physical test success additionally needs
fresh independent Gazebo truth under the original speed/time bounds. At link
loss physical Stop is UNCONFIRMED. Takeoff/Land ACK receipts alone do not
complete a physical action; the test scenario verifies height/ground/final
state. This composition certifies no real hardware, server or RKNN backend.

`./scripts/test_simulation_v1.sh` builds in a fresh owned output directory and
runs both vehicles plus faults, with bounded stage deadlines, unique world
names and unused matching ports. It retains process/command/state/truth
manifests and fails on missing evidence or cleanup failure. See
[simulation usage](simulation/README.md) and [completion audit](simulation/completion-audit.md).

## P9 application process

`app.main run` composes a caller-scheduled `SimulationRuntime` and Typed
`MissionRuntime` in one local loop. Unix-domain IPC exposes only status,
registered mission start, cancel and shutdown. The `disarmed_mode` catalog
contains Copter GUIDED and Rover HOLD, and never accepts client-provided
Effects or authorization. Mission envelopes retain identity, scope and deadline
through Execution. Leases belong to individual compiled Actions; idle and
reconnected processes have SEND disabled. Both vehicles passed actual App
subprocess tests and the original physical/fault suite; see
[the P9 audit](autonomy/phase-9.md). No real-device or onboard claim follows.

P10 adds a telemetry-only reported-pose localization projection and bounded
base_link/odom TransformTree to each simulation epoch. Snapshot dependencies
pin the same vehicle source revision; no map/world identity transform is
inferred. Source capture, receive and publish times are logged. Reconnect
discards the old graph and world epoch. See [P10 evidence](autonomy/phase-10.md).

P11 publishes immutable, session-bound Environment references from explicit
training TOML resources. Named points/home/regions declare their odom frame
and source; geofences must match the enforced SafetyPolicy. Config changes
revoke the current task and require a new preflight. Reported local/global
pose can validate the configured origin; missing fix evidence is rejected.
The resource service never sends commands. See [P11](autonomy/phase-11.md).

P12 finite typed Actions and physical result/exit barriers passed both public App processes and the complete regression. See [P12](autonomy/phase-12.md).

## P13–P15 and recorded visual composition

The public App catalog compiles strict named-point routes for both vehicles.
Each Action has its own lease, finite deadline, result feedback and confirmed
Stop barrier; cancellation fences queued requests before the next write.
Already transmitted one-shot side effects cannot be undone. Reconnected
sessions remain read-only until a new explicit task.

Environment references bind to the current world/frame epoch. The explicit
Gazebo object adapter has a separate read-only subscription from the test
Oracle, a whitelist and a content-hashed world-to-odom calibration. SIM/REAL
clock pairs map capture time without extrapolation; duplicates retain their
age and disappearing targets publish unavailable tombstones. WorldModel
adopts only fresh, valid standard observations.

CUADC search/selection/approach Actions use those immutable WorldObjects and
produce typed requests. ReleasePayloadEffect is an independently reviewed
non-vehicle contract; PayloadExecution checks both SEND gates, scoped lease,
session/generations/deadline and explicit PayloadSafety before mutation.
Only its injected SimPayloadPort changes the simulation inventory. A later
independent payload-state observation must agree before COMPLETED. The
vehicle envelope and VehicleExecution reject payload requests. No Servo/PWM
or real payload transport exists in this composition.

`--recorded-vision-config` selects a finite, checksum-pinned image recording
instead of the simulation object adapter. A bounded asynchronous CPU YOLOX
worker produces pixel detections; explicit pinhole/plane calibration is
required to produce located odom observations. Unlocated or ambiguous
detections never become motion targets. Capture/receive/inference times,
source/calibration versions, confidence, drops, exposure provenance and
health remain observable. Late results are invalid; absent targets expire
or publish unavailable tombstones. Vehicle shutdown fences control before
waiting for the sensor worker, including worker-close failures.

P9–P15 and the P17 recorded-image/virtual-calibration software scope passed
actual App/SITL/Gazebo acceptance; see the [autonomy audit](autonomy/completion-audit.md).
The bus-to-bucket fixture mapping verifies adapter substitution only. Physical
camera calibration, competition bucket recognition, RKNN, real payloads and
P16 hardware motion remain unvalidated; hardware work is deferred.

## Optional P18 ROS 2 mapping composition

An explicitly selected Rover simulation can load `--ros2-mapping-config`.
Gazebo lidar and simulation clock cross a one-way `ros_gz_bridge`; a separate
`integrations.ros2.mapping_node` reads only the public Application status use
case to publish telemetry odometry TF and synchronized scans. SLAM Toolbox owns
`map -> odom`; the sidecar owns `odom -> base_link` and the explicit laser mount.
No ROS subscriber can issue a vehicle command. Mission, Effect, authorization,
Safety and the sole MAVLink writer remain the existing execution path.

The sidecar atomically publishes bounded metadata and content-addressed immutable
grids. The ROS-free `mapping` package validates content, source/frame epochs,
versions, original timestamp age and clock domain before WorldModel adopts a
`WorldSnapshot.map` reference and Map dependency. Unavailable maps are removed.
SLAM poses are diagnostic only; existing Actions continue to use telemetry
localization in odom, without silently applying loop-closure corrections.

This is an optional local 2D mapping composition, not hardware clock sync,
Nav2 navigation, active SLAM localization or arbitrary-scene certification.
The P18 baseline has an axis-aligned occupancy-boundary defect. P23 adds an
explicit source/ABI-pinned native repair for SLAM Toolbox 2.8.5; unpatched
compositions retain the limitation. See the [mapping guide](ros2_mapping.md),
[P18 evidence](autonomy/phase-18.md) and [P23 audit](autonomy/phase-23.md).


## P19 read-only Nav2 planning

`app.plan` is an explicit independent read-only composition. It accepts a
content-addressed recorded map, or queries the existing idle Rover App's
public status and P18 MappingInput. The ROS-free `ReadOnlyPlanningService`
pins map content, source/frame epochs and source capture time; verifies
endpoints, full segment/footprint collision and result deadlines; and rechecks
the map before returning an immutable geometric path with executable=false.
The recorded-map mode makes no live freshness claim.

The optional Nav2 adapter owns one private namespace/map/TF and process group
per request. Only native Planner Server with SmacPlanner2D runs. Explicit
start/goal coordinates are converted to a grid-local frame and back; a private
planning anchor satisfies costmap TF without pretending to be a vehicle pose.
Costmap content and geometry are checked against the frozen configuration grid.
Unknown/ambiguous cells are blocked; conservative clearance and an independent
source-grid segment check remain outside the planner.

No VehicleRuntime, navigation Mission/Action, Effect, controller server, MPPI,
or second command writer is created by this composition. Existing vehicle
Application scheduling and safety authority are unchanged. Paths are planning
results, not executable trajectories or an avoidance-driving claim. See the
[planning guide](nav2_planning.md) and [P19 audit](autonomy/phase-19.md).

## P20 explicit Rover path consumption

The optional Application navigation configuration registers one finite
`follow_path` mission: GUIDED, Arm, FollowPath, observed Stop exit, Disarm.
`NavigationSupervisor` admits only fresh live P19 output and rechecks the
original stored content, current adopted map, source/frame identity, time,
start and bound geofence. A plan file is never an authorization grant.

The audited Gazebo chassis has its drive axle 0.25 m ahead of base_link.
Guidance follows this explicit reference with a 0.72 m footprint radius and
at least 0.95 m planned clearance; telemetry/localization contracts and their
base reference are unchanged. A run pins an observed planar map<-odom binding,
revalidates the complete bound path on live map/alignment updates, and rejects
source/epoch changes or excessive alignment displacement. This is not a
permanent static TransformTree relation or a switch to SLAM localization.

`FollowPathAction` reads immutable parameters, WorldSnapshot and a read-only
navigation view, emitting only typed body Twist/Stop Effects. The original
Execution, dual SEND, lease, Safety and sole byte writer remain in control.
An injected rejection-only motion guard at that writer checks the live map,
state age, file SHA, path corridor and short swept footprint; mapping is
polled before queue drain. Stop remains available after a map fault and uses
the existing observed two-second stability/eight-second deadline barrier.
Default compositions install no navigation guard or follow_path mission.

P20 itself supplies no ROS command bridge, automatic replanning/resume,
hardware connection or general vehicle-kinematic support. See the
[tracking guide](rover_path_following.md) and [P20 audit](autonomy/phase-20.md).

## P21–P25 optional goal and business composition

Application owns `GoalNavigation`: a frozen named target, Environment/frame/map
dependencies, finite policy, asynchronous read-only planning job and typed child
Mission. Immutable inputs cross the worker boundary; no vehicle object does.
The native Nav2 group is private, cancellable and joined before terminal cleanup.
Late results cannot restore a cancelled task. The public P19 read-only READY /
SEND-disabled admission rule is unchanged.

Only a current-map path obstruction is recoverable under an explicit bounded
retry policy. The old child completes its observed exit and revokes its run;
a separate typed Stop/Disarm recovery precedes new planning, admission and lease.
Map-source, clock, frame, localization, alignment, safety and cancellation faults
do not become retry permissions. Outer and per-action deadlines remain finite.

Persistent map coordinates require a registered `MapAnchor` tied to Environment,
HOME, vehicle epoch, map publisher generation and observed map<-odom binding.
Restart/reload needs explicit re-registration. The SLAM localization candidate
is diagnostic and never control-eligible; no implicit source switch or fusion
changes the active telemetry localization contract.

Application business recipes sequence independent goal tasks and record stopped,
disarmed inspection checkpoints from valid observations. The business layer has
no vehicle port; failure/cancellation waits for navigation exit and typed cleanup.
Repeated cancellation cannot interrupt that cleanup.

`VehicleNavigationModel` injects versioned reference geometry, footprint,
capabilities and command bounds into planning, admission, guidance, Action and
the rejection-only writer guard. Closed registered presets must match their
Deployment profile. The original front-drive and compact front-drive fixtures
use distinct physical SDFs; no model branch is added to Core or contracts.
Only separately accepted combinations are supported, not arbitrary drivetrains.
Configuration and exact acceptance status: [autonomy guide](rover_autonomy.md)
and [roadmap](autonomy_roadmap.md). Default composition remains unwired.

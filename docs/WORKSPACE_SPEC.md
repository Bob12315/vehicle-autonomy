# Workspace schema 1 and ownership

Workspaces orchestrate registered external software only. They neither create
Missions nor authorize vehicle Arm/motion. `app/tools/workspaces.py` is the
validation/runtime contract. Example:

```json
{
  "schema": 1,
  "id": "rover-navigation",
  "name": "Rover Navigation",
  "context": {
    "vehicle_id": "rover", "vehicle_type": "rover", "environment": "simulation",
    "ros_namespace": "/rover", "ros_domain_id": 91, "mavlink_profile": "monitor"
  },
  "components": [
    {"id":"ros2","agent_id":"onboard","tool_id":"ros2","profile_id":"default",
     "depends_on":[],"optional":false,"wait_for":"ready","timeout_s":120},
    {"id":"nav2","agent_id":"onboard","tool_id":"nav2","profile_id":"default",
     "depends_on":["ros2"],"optional":false,"wait_for":"ready","timeout_s":120},
    {"id":"rviz","agent_id":"desktop","tool_id":"rviz2","profile_id":"default",
     "depends_on":["ros2"],"optional":true,"wait_for":"ready","timeout_s":60}
  ]
}
```

IDs are bounded ASCII identifiers. At most 24 components and 180 s per component.
The validator rejects unknown fields, cycles, missing dependencies, duplicate
IDs and duplicate Agent/Tool assignments. Each Agent currently owns one instance
per Tool ID. Context is typed; `hardware_controlled` is never accepted.

## Preparing and stopping

1. Save a definition (no side effect). Launch freezes that definition and context
   into a distinct run. Editing a saved definition cannot alter an active run.
2. Preflight **every required** Agent, Tool, Profile, dependency, GUI environment
   and compatibility before issuing any launch. Optional failures are recorded.
3. Start after dependency conditions are satisfied; claim durable shared ownership
   before submitting the Agent job. Pending compatible launches share the same job.
4. `wait_for=ready` requires a configured functional probe. `wait_for=running`
   explicitly permits a live process with unknown functionality/connection.
   A run is READY only when all components actually report ready. PREPARED means
   configured conditions passed but some are only running. Optional failure makes
   the run DEGRADED, required failure FAILED. No process-only QGC is called READY.
5. Retry failed/skipped/blocked components explicitly, reusing compatible live
   services. Failed preparation retains ownership until explicit stop; it cannot
   silently tear down a service used by another run or Mission environment.
6. Stop proceeds in reverse dependency order, waiting for dependent release. Only
   the last reference to a Workspace-created service can request its owned stop.
   A manually launched/existing compatible service has baseline ownership and
   survives Workspace stop. External/unidentified programs are observation-only.
   Queued undelivered launches cancel without execution; delivered outcomes and
   cleanup must be confirmed. Unknown/disconnected remains unknown, not stopped.
   Cleanup has a 25 s backend deadline; uncertainty retains references and requires
   an explicit later stop retry. Browser loss clears live readiness displays but
   does not cancel the backend Workspace or its services.

The backend rejects direct Stop/Restart of a Workspace-owned Tool. A manual
Launch of an already shared compatible service adds baseline ownership, so a
later Workspace stop preserves that explicit manual claim.

## Restart and persistence

Private `workspaces.json` atomically stores up to 64 definitions, 128 run results
and reference ownership. History is bounded by admission, not silent deletion of
user records. Backend restart leaves referenced runs UNKNOWN, never auto-starts
or auto-stops remote software, and protects references. Explicit reconciliation:

* `resume`: operator supplies current component instance IDs; Agent boot, profile,
  context and any previously pinned instance must match. Restore records without
  restarting the processes. Invalid/changed identity is rejected.
* `release`: explicitly abandon the records, preserve surviving software as a
  baseline service, mark ABANDONED. This **does not assert cleanup or stop**.

An Agent reboot cannot inherit an old process identity. The operator must inspect
and release unresolved records rather than silently substituting a new instance.
Audit records each request/result. Persistence failure fences new preparation.

## Presets and actual integration boundaries

Rover Navigation: ROS observer -> isolated Nav2, optional RViz2. Requires real
map/TF/sensor/environment configuration; starting processes cannot supply those.
UAV Ground Station: Copter/Plane context + operator-provisioned one-way MAVLink
relay + QGC. QGC's process-only threshold makes it PREPARED until connection is
independently established. No vehicle Action is triggered.
Simulation Lab: Gazebo -> SITL -> QGC, optional RViz2. The shipped headless Gazebo
lab/native SITL profiles are independent smoke environments, **not coupled physics**.
Select matching operator-provisioned world, plugin, FDM/ports and telemetry relay
profiles, or use the existing owned simulation launchers, for coupled vehicle
testing. The UI makes each selected Profile explicit; no third-party internal UI
settings, live map, navigation Action binding or remote window focus is inferred.

With `vehicle-autonomy-tool-registry --coupled-rover --sitl-dir ...
--ardupilot-plugin ...`, matching `rover-coupled` profiles are generated into a
new private deployment resource directory. The preset chooses this pair on the
same Agent. Gazebo's process-running threshold allows the JSON SITL to start;
live world stats then qualify actual Gazebo readiness. Port preflight rejects
collisions without killing external processes. Each Tool instance has its own
fresh working directory, keeping SITL EEPROM/data isolated. This pair does not
provision the original Framework signing/ownership admission or a QGC relay.

## HTTP contracts

Existing bearer/Host/Origin/CSRF/request-ID security applies to all mutations:

* `/api/workspaces/template`: `{template_id, context}` -> editable definition.
* `/api/workspaces/save`: `{spec}` -> validated sorted definition.
* `/api/workspaces/launch`: `{id}` -> frozen run/preflight results.
* `/api/workspaces/stop`, `/retry`: `{run_id}` -> current run.
* `/api/workspaces/reconcile`: `{run_id, decision, instances}` -> reconciled run.
* `/api/console/state` includes definitions, runs, leases, templates and faults.

Agent process state remains the source of truth; HTTP acceptance is not readiness.

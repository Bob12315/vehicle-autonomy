# Development rules

The repository uses a single installable `src/vehicle_autonomy/` layout with
seven core packages: contracts, engine, actions, vehicles, world, autonomy, app.
Read README.md, docs/architecture.md, Vehicle_Autonomy_V1.0.md and
Vehicle_Autonomy_File_Structure_V1.1.md before editing. The two versioned
architecture baselines describe target behavior and file ownership; do not
claim future capabilities are implemented.

Legacy was removed by explicit user request after dependency audit and local
data backup. Historical source remains in Git history. Do not import archived
code or modify independent old projects elsewhere on the host.

The root has no production vehicle connection. Vehicle commands require both
system and Action SEND authorization and an explicit SafetyPolicy. Both SEND
gates default to false. Mission, Action, Web, perception and intelligence must
not call a vehicle command port directly. Keep hardware access behind Execution,
Vehicle, Protocol and Transport boundaries. HardwareReadOnly must remain
receive-only; hardware_controlled is rejected. Preserve Lease, TTL, session and
generation fences, the unique MAVLink writer, and UNCONFIRMED stopping semantics.
Do not claim flight, server or RKNN support from an interface or placeholder.

Install with `python -m pip install -e '.[mavlink]' -r requirements-vision.txt`
in an isolated environment. Run `python -m unittest discover -s tests -v` and
relevant simulation tests for each completed stage, then commit it. Optional
ROS dependencies stay in explicitly launched workers. Generated runtime state,
artifacts and external deployment configuration are not Python packages.

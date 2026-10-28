# Mission Studio B: implementation audit

2026-10-29, baseline `22540c6`. This is the pre-implementation audit, not a
claim that the requested B features already exist. All owned interactive
deployments were gracefully stopped first; Web ports 8780–8782 are closed.
No old Mission data, external CUADC project or unrelated checkout was changed.
Baseline: `.venv/bin/python -m unittest discover -s tests -v` passed all 773
tests in 106.033s (`/tmp/vaf-studio-baseline.log`).

## Actual existing implementation

| Area | Existing source and behavior | Required extension |
|---|---|---|
| Action contracts | `contracts/decision.py`, `engine/action/registry.py`, `actions/catalog.py`: versioned typed parameters, input/output schemas, capabilities, resources, lifecycle and provider bindings | Declarative retry/skip/override eligibility; richer schema UI, no arbitrary executable parameters |
| Mission definition | `contracts/mission.py`, `engine/mission/graph.py`: immutable schema 1 rooted tree with ordered children, 128 nodes, bounded depth and Action budget | Schema 2 editor graph with stable edge IDs, typed bindings, explicit publication/dependencies; retain schema 1 |
| Executor | `engine/mission/graph_runtime.py`: real Sequence, Condition TRUE/FALSE/UNKNOWN, bounded Repeat, Parallel all/any/main, Recovery/Fallback, Event/Reactive, Wait/Timeout | ForEach, SubMission contexts, preserved repeated execution records, safe scheduling pause and debug |
| Blackboard | `BlackboardValue` and `world/model/mission_inputs.py`: frozen values with original time/quality/frame, bounded TTL, restricted world reads and scalar bindings | Declared nested types, scoped writes, collections, provenance/consumers, object/array binding and history |
| Safety | Existing Mission resource permit spans children; Action Runtime owns all effects; UNKNOWN cannot become success or authorize recovery; Plane retained flight continuation is explicit | Reuse every gate. Pause must not freeze or abandon active vehicle control. No separate Studio command path |
| Persistence | `engine/mission/journal.py`: checksummed fsync/atomic durable record, lifetime flock, immutable versions, bounded run/manual ledgers; uncertain restart is UNKNOWN | Separate draft CAS revisions/templates/library; pin B definition and dependencies in existing run journal |
| Web | Vanilla JS/HTML/CSS; existing `/studio` tree editor, schema parameter helpers, polling/history highlighting; shared opaque Cookie/CSRF/Origin login already works | Library-first IDE and shared editor/runner canvas, richer binding/version/debug panels; keep legacy editor route |
| Tests | unittest plus explicitly launched actual Chromium, ROS and owned three-vehicle SITL/Gazebo probes | New contract/runtime/storage/browser tests, actual safe SITL examples, original-suite regression |

The existing tree editor is not an unrestricted DAG executor. Action/Wait leaves
cannot have children, repeated node execution identity is reset, and event
history is a bounded 256-entry deque. A graph picture alone would not supply
ForEach, SubMission, safe debug, immutable draft publication or Blackboard types.
There is no application database/ORM to replace: use the existing durable-file
mechanism and owner locks, with explicit versioning rather than silent overwrite.

## Compatibility decision

Retain schema 1 validator/runtime/API and persisted versions byte-for-byte.
Introduce a versioned schema 2 graph and an authoritative engine compiler into
that same runtime, extending its node/context machinery where required. The B
definition is pinned in the compiled snapshot with source-node mappings. There
is one Action Registry and one side-effect scheduler, not a browser executor or
second app-owned engine. Old definitions can migrate explicitly to a new draft;
the original version remains available. `/studio` becomes Library-first B;
`/studio/legacy` preserves the earlier editor for compatibility acceptance.

## Known environment limits carried forward

Native ROS/Gazebo/ArduPilot tools exist on this PC, but hardware SEND remains
forbidden. Earlier Rover stopping/ReturnHome uncertainty and a native Gazebo -4
exit are retained risks, not fixed by Studio. CUADC payload/target operations are
explicit software simulation only, never real aiming or actuator release. The
30–35 m observation scene is not evidence that the current Copter control profile
permits flight outside its existing bounds. Each actual new SITL pass/failure
will be reported independently from simulated business data and browser fixtures.

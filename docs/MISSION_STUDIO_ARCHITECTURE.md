# Mission Studio B architecture

The audit and [runtime contract](MISSION_GRAPH_RUNTIME_CONTRACT.md) precede
implementation. This document describes intended ownership; the test report
records what actually passed.

- `contracts`: frozen definitions/data contracts, without ROS/device imports.
- `engine/mission`: graph compilation/validation, existing scheduler extensions,
  typed Blackboard scopes, execution identities, safe debug and history.
- `actions`: existing registered vehicle/provider Actions; explicitly registered
  pure software scenario Actions for the CUADC simulation. No new flight algorithm.
- `app/mission_designer`: draft CAS, immutable publications/templates, imports,
  diffs and application use cases using the engine's one validator/runtime.
- `app/web`: authenticated API and Library-first Studio. Existing vanilla JS and
  console theme are retained; common canvas is used by Editor and Runner.
- `simulation`, `tests`, `docs`: non-package scene data, actual evidence and
  independently labelled software fixtures.

Flow: Library/Draft → engine validation/compiler → immutable publication →
existing Mission Runtime → Action Runtime → existing Execution/Safety/Authority
→ Vehicle/Protocol/Transport. Run events, node I/O, scoped Blackboard and Action
evidence return read-only to Runner/History. Future AI submits the same draft
definition with the same revision check; it does not gain another command path.

The original Mission journal is not deleted or silently rewritten. A separate
private durable Studio library stores drafts/publications/templates and references
the existing run ledger. Schema 1 and its legacy editor remain available. All
pages use common login. Tool lifecycle remains with Tool Manager, and maps/point
clouds remain with RViz/QGC. Debug does not promote hardware_readonly to control.

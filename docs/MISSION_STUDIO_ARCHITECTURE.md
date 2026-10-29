# Mission Studio B architecture

The audit and [runtime contract](MISSION_GRAPH_RUNTIME_CONTRACT.md) preceded
implementation. The ownership below is implemented for Studio B. Actual
qualification and explicit limits are in [the test report](MISSION_STUDIO_TEST_REPORT.md).

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

## Implemented modules

`studio_graph.py` is the authoritative schema-2 compiler; `graph_runtime.py`
remains the only Mission scheduler. `studio_state.py` supplies run-local data
and records, and `blackboard.py` implements typed scopes and transactional
parallel merge. The existing ActionRuntime owns every effect, timeout and exit.

`app/mission_designer/studio_library.py` adds a separate owner-locked,
checksummed/fsynced file store, CAS drafts and immutable publications. The
service/extractor/examples modules compose that store with the existing runtime.
The original journal and schema-1 APIs are preserved.

`studio-b.html/js/css`, `studio-canvas.js` and `studio-params.js` provide the new
Library-first `/studio`; `/studio/legacy` retains the original editor. Both
reuse `auth.js` and the console theme. The browser never stores the management
or Agent key. `/api/studio-b/*` uses the existing authorization, CSRF and Origin
checks. Mission startup still rejects an occupied manual reservation/target.

Editor and Runner share the canvas. Node records identify their source Mission
and execution scope so same-named child nodes cannot falsely highlight a parent
node. History seek rebuilds observational state without scheduling anything.

The navigation-goal data adapter reads existing expiring proposals, preserves
their receipt time and epoch, and has no execution method. The `Sim.*` Actions
are opt-in, owned-Copter-only, zero-Effect software scenario implementations.
Standard three-vehicle templates use the real registered vehicle Actions.

## Deliberate V1 limits

No arbitrary back edges, unbounded loops, automatic retry of unconfirmed effects,
cross-checkpoint reconstruction, QGC goal importer or unqualified map transform
is implemented. Generic typed object/array parameters are generated from Action
Schema; complex Blackboard declarations and failure policies retain an advanced
JSON editor. Extraction is limited to closed linear Action/Wait selections.

Takeover releases only confirmed-safe scopes. Interrupted Actions are not
silently reconstructed; retained native Plane flight can remain blocked until
its original safety/continuation contract resolves. Plane graphs with control
Effects reject motion single-step. This is an explicit capability limit, not a
claim that an airborne vehicle can be frozen safely.

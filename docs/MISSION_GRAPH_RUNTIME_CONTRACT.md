# Mission Graph Runtime Contract — B / schema 2

This is the implementation contract selected after the audit. Individual
implemented/validated features are recorded in the final test report; this
contract alone is not evidence that all features exist.

## Identities and frozen execution

`mission_id` identifies a library entry; `revision` is a draft CAS integer;
`version` identifies an immutable publication. A Run has its own run_id,
immutable definition snapshot/hash and pinned Action/SubMission contract versions.
Each execution of a node has a fresh execution_id, input/output snapshots and
iteration/scope identity. Event sequence/identity and original timestamps are
independent of definition and node identity. Editing a draft cannot affect a Run.

The graph includes `schema_version`, `mission_id`, `revision`, `version`, `name`,
`supported_vehicles`, `target`, `nodes`, `edges`, `blackboard`,
`execution_policy`, `resource_requirements`, `failure_policy`,
`sub_mission_references` and `metadata`. Node identities and edge identities are
stable bounded strings. An Action node pins `action_type`,
`action_contract_version`, `parameters`, `input_bindings` and `output_bindings`.

## Structured graph and execution

Schema 2 allows ordinary Start → Action → Action → End sequencing. Condition,
bounded ForEach, Parallel/Join and SubMission have explicit branch/body ports.
No unbounded graph back-edge is allowed. Branch convergence requires a declared
Join, not implicit duplicated execution; orphan/dangling/cyclic/ambiguous edges
are validation errors. The engine compiles this structure into its existing
rooted execution tree and retains source-node mappings. Native context nodes
extend that same runtime for iteration and SubMission; no application invokes a
vehicle port. Schema 1 imports produce a new explicit draft, never mutate old data.

Condition is typed TRUE/FALSE/UNKNOWN. No eval, JS, Python or Shell expression is
accepted. UNKNOWN cannot silently become false or trigger new unsafe effects.
ForEach is sequential, snapshots its validated collection once, bounds item count
and total timeout, gives every iteration independent loop.index/current_item/
iteration_id and execution history. Parallel has bounded branches; All/Any Join
waits for safe cancellation/resource cleanup of remaining work. Static conflicts
and actual runtime resource permits both apply.

Action failure and timeout remain distinct from uncertainty. Retry requires
declared eligibility, a bounded attempt budget and confirmed safe prior exit.
Unknown physical outcomes must not be replayed. Skip and overrides are explicit
published capabilities, never blanket permission to bypass vehicle preflight.
Overrides are separate audited run input and cannot rewrite a published version.

## Typed scoped data

References are explicit scoped paths, such as `mission.selected_targets`,
`loop.current_item`, `node.<node_id>.output.<field>` and declared SubMission ports.
Bindings include provenance and freshness requirements. World/external state is
read-only. Spatial values carry frame/units/time domain/origin and validity;
copying a value cannot refresh its original observation. Large media uses bounded
artifact references, not embedded image/cloud/video bytes. Parallel writes are
isolated and checked before merge; one iteration must not overwrite another's
node execution inputs/results. SubMission versions are pinned, acyclic and have
independent input/output/local scopes.

## Pause, debug and takeover

Pause stops new scheduling only at safe boundaries. Existing Action Runtime
controllers and necessary services continue their own lifecycle; a browser debug
pause must never freeze a running motion controller or stop airborne motors.
Unconfirmed/retained flight scopes cannot be called safely paused. A pending
pause is visible until a safe boundary is reached, and deadlines are not silently
extended. Resume rechecks current session, vehicle state and typed inputs.
Breakpoints/step use the same safe-boundary gate. Cancel requests normal Action
exit and preserves UNKNOWN barriers. Takeover is explicit cancellation and safe
ownership handoff; completion does not automatically resume Mission.

## Persistence and authorization

Draft saves require expected revision. Conflicts return a machine-readable
conflict and preserve the competing draft. Publication is immutable and validates
schema, graph, bindings, vehicle capability, Action versions, provider dependency,
resources and SubMission pins. Run start revalidates dynamic state and uses the
same double SEND/Safety/Lease/TTL/session/generation/unique-writer chain.
Browser APIs use existing shared Cookie/CSRF/Origin auth; Agent credentials are
separate. On restart no old lease, Action controller or authorization resumes.
History is observational replay only, never execution by seeking a timeline.

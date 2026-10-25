# Independent FAIL remediation contracts

These additions repair the four Phase 3 findings. They add no vehicle command
path, lease, Mission orchestration or later-phase capability. The independent
FAIL and the original development report remain historical records.

## Authenticated receive evidence

A fresh owned SITL provisioner creates `action-receive-floor` before the first
Action owner starts. Existing numeric files are not migrated: use a newly
provisioned owned fixture/key. The receiver never initializes a missing file.

The record binds the signing epoch fingerprint and a 48-bit floor, with a
canonical versioned encoding and checksum. Updates write an exclusive private
temporary file, check the complete write, fsync the file, atomically replace
the record, and fsync the directory. The verifier stages MAC/order validation;
only after the necessary reservation is durable does it publish its watermark,
accepted count and return authenticated evidence to Session/World. The existing
reservation bound is 128 timestamp increments, not a packet/request ID.

For every returned timestamp T, durable_floor >= T. Returned timestamps and
the durable floor never decrease in the same epoch. A failed persistence call
poisons that receiver: subsequent calls cannot return evidence. A new owner can
recover a valid previously committed record; it rejects all timestamps through
that conservative floor. A missing, truncated, corrupt, wrong-epoch or invalid
record refuses the old epoch. No fallback to a provisioning timestamp occurs.

This assumes local atomic rename/fsync semantics and a trusted OS owner. It
does not provide protection against malicious same-user code, complete storage
snapshot rollback or lost filesystem durability guarantees. After such loss,
restore no old authentication window: establish a fresh trusted key epoch.
Packet sequence and host receipt time remain insufficient confirmation proof.

## Logical Action outcome and safe resource release

Normal typed vehicle Effects remain behind existing Execution/Authority/Safety
and the single Writer. The existing vehicle driver can independently establish
safe cleanup of those Effects. Query declares no side effects.

An external lifecycle (no vehicle Effect declaration) that raises during exit
or cannot confirm exit before its deadline has an independent uncertainty
latch. Every final/guard reconciliation combines that latch with driver safety;
"no vehicle cleanup" cannot resolve an external operation. Explicit provider
terminal evidence can resolve it. Ordinary FAILED, explicit no-side-effect
admission rejection, and read-only Query cleanup do not all become UNKNOWN.
`ActionAdmissionRejected` is a trusted no-side-effects admission contract.

ROS Action/Service workers distinguish pre-submission failure from potentially
submitted work. The submission flag is set before call_async/send_goal_async,
not after obtaining a handle. Submitted communication/future errors are UNKNOWN.
A known rejected goal, unavailable server before submission or actual terminal
failure remains FAILED. Trigger has no cancellation/status-query protocol:
client cancellation or closure cannot prove service termination. No request is
automatically resubmitted. HTTP recovery only reads an existing job ID.

## Stable external reservations across processes

External deployments reuse one stable private state directory and resource
scope across every application restart/target alias referring to the same
provider/resource. `ExternalActionDriver` accepts `state_dir` and
`resource_scope`; defaults are a stable `VAF_ACTION_RESOURCE_DIR` or
`$XDG_STATE_HOME/vehicle-autonomy/action-resources` (the usual user state path
when XDG_STATE_HOME is absent). These are deployment settings, not Action/API
parameters. Choosing a new directory or scope is not a recovery procedure.

Before the first operation on a genuinely fresh/verified quiescent provider,
trusted deployment code must call `PersistentResources.initialize(directory,
verify_quiescent)`. The bounded read-only verifier must return ActionSafety
with release_safe=true and evidence containing quiescent=true and a nonempty
provider_epoch. This is not a user-supplied force boolean. Test fixtures verify
their newly created empty HTTP server/unique ROS namespace before initializing.
No ordinary Runtime startup, acquire, read or missing-file path initializes a
namespace. An established namespace or its surviving anchor cannot be reset by
this operation. An unconfigured/missing namespace blocks new external effects;
read-only Query remains available.

Before a provider factory is invoked, the reservation is durably committed and
marked ACTIVE. Records include Action/name/version, owner/runtime identity,
PID/start ticks, stable scope, target, resource modes/groups, uncertainty and
the available provider descriptor. HTTP endpoints contain no userinfo/query or
credentials; tokens are never stored. If a job ID is obtained it is recorded;
loss before that point still leaves the prior reservation. A 4096-record and
4 MiB bound rejects new work instead of evicting uncertain owners.

File locking serializes independent applications. New runtime/Action IDs,
target aliases and dead PIDs do not release a reservation. Missing/corrupt
state, lock or namespace/anchor mismatches fail closed. State directory loss
is detected by its adjacent private identity anchor; loss of the entire state
tree still cannot silently initialize because ordinary startup never creates
state. Keep this directory/anchor on durable private storage; do not restore
old snapshots as if they proved current provider quiescence.

## Controlled reconciliation

Use `ActionRuntime.reconcile_external(owner, verifier)` from trusted deployment
recovery, outside the normal control workload. No Web force-release endpoint
is provided. The verifier is bounded, does not resubmit work, and returns typed
ActionSafety plus matching owner/scope/terminal evidence. It must actually
verify the provider's safe terminal state. An old live coordinator cannot be
released by a different coordinator; stop/quiesce it first. PID reuse is checked
with start ticks. The current coordinator can reconcile its terminal UNKNOWN
record, but cannot reconcile an Action that is still running.

`reconcile_api_resource(record, token=...)` queries the recorded existing HTTP
job ID. RUNNING, UNKNOWN, errors or an unknown ID retain the reservation. A
confirmed SUCCEEDED/FAILED/CANCELLED terminal can release it; the old logical
UNKNOWN result remains UNKNOWN, with an explicit new safe reconciliation event.
For an unknown ID or unqueryable Service, a deployment-specific verifier must
establish trusted provider-wide quiescence or the exact invocation's terminal
state. The real ROS test's owned server exposes an invocation marker solely as
an independent oracle; generic Trigger does not gain a status protocol.

Plain `release(owner)` cannot erase retained/active durable work or another
runtime's ownership. Deleting state is never a supported release. When state
is corrupt and safe reconciliation cannot be proved, keep the scope blocked;
restore trustworthy state or explicitly establish a genuinely isolated, trusted
provider epoch and its new deployment storage. Do not reuse a still-running
provider by merely changing directory, target or instance identity.

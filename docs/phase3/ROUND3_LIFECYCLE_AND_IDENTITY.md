# Phase 3 round 3: independent exit and provider identity contracts

This supersedes the two insufficient assumptions identified in the second
independent FAIL. The prior reports, watermark recovery and ROS UNKNOWN result
mapping remain historical/unchanged. No vehicle authorization path is added.

## Independent responsibilities

`ActionSpec.external_lifecycle` is explicit, independent of `effect_types`:

- `typed_only`: all side effects use declared Typed Effects. The standard vehicle
  catalog uses this contract. Independent job creation is rejected before I/O.
- `managed`: external work uses the managed job port/built-in job clients. Its
  terminal proof and the vehicle driver's cleanup proof must **both** be safe.
- `opaque` (default): unknown lifecycle callbacks cannot be discharged by a
  clean vehicle driver. Exception/timeout uncertainty needs trusted reconciliation.

Declaring ArmEffect never proves absence of external work. An instance can have
vehicle and external responsibilities at once; shared claims remain held until
both are safe. Logical UNKNOWN remains UNKNOWN after safe physical reconciliation.

`ActionContext.external_jobs.start(create)` registers custom native/SDK job
factories **before** calling them. Factories that use a provider other than their
driver declare the already verified `resource_store` at registration. Built-in
HTTP, Native and ROS process clients also enroll themselves before creating a
thread/process or submitting work. These clients reject calls outside an active
managed Action callback. The port checks its ACTIVE durable owner/runtime record,
deadline and lifecycle contract. Exit seals ingress permanently, including saved
port references; only existing-job cancellation and read-only reconciliation remain.
One unresolved job per bound exclusive provider resource is permitted.

Terminal callbacks cannot override a running/unknown managed job. Later ticks,
vehicle guard results and successful no-effect cleanup do not discharge it.
Trusted job terminal evidence can restore reuse; exception with an opaque callback
still needs its explicit complete external inventory/terminal proof. Query and
explicit no-side-effect admission rejection do not acquire an eternal hazard.

Action extensions are trusted code, not a Python sandbox. Raw unregistered
network/SDK I/O, detached unmanaged side-effect threads and false terminal results
are prohibited by this extension contract. No claim is made to contain arbitrary
same-process malicious Python. Supported clients enforce registration themselves.

## One local provider registry

Production uses a fixed OS-account registry at the password database home path
`~/.local/state/vehicle-autonomy/provider-registry`, independent of source/wheel
installation, XDG_STATE_HOME, state_dir, target alias, runtime UUID and scope.
There is no constructor/environment option to select another production root.
Trusted deployment code calls `ProviderRegistry.initialize()` once for a truly
fresh deployment. Ordinary application startup never initializes missing state.

The private registry, lock, identity anchor and checksummed bindings are validated
on every ledger transaction. A provider/resource is bound to one ledger and pinned
resource definitions/scope. Its binding commits before ledger creation; a crash
between them blocks the incomplete identity instead of permitting another ledger.
Registry and ledger locks share one fixed lock order across processes. Short writes,
missing/corrupt state, mismatches and invalid permissions block effects. Bounds are
4096 records/4 MiB; unresolved owners are never evicted for capacity.

HTTP job providers expose a read-only `/identity` with `provider_id`,
`provider_epoch`, and `resource_id="jobs"`. `initialize_http_resources` reads it,
then requires a trusted complete inventory/quiescence verifier. The client checks
the actual public identity again **before POST**. Endpoint aliases, new scope,
new ledger and changed caller labels cannot turn the same actual ID into a second
owner. A provider lacking this identity protocol cannot start HTTP jobs through
this interface. Credentials are neither returned nor stored by this protocol.

ROS identity is the canonical local domain/server namespace, pinned by trusted
deployment to its provider epoch. Overlapping namespaces cannot create independent
ledgers. The supported process client verifies the actual installed ROS worker,
arguments and domain rather than accepting a caller's claimed endpoint. Generic
commands are rejected. Native cooperative `ai.inference` work uses one OS-user/boot
identity and fixed local resource; different arbitrary Native labels cannot split
it. NativeJob is not a general remotely authenticated SDK or detached-service API.

Different actual HTTP providers/resources remain independent and may run at once.
This is trusted local coordination, not a distributed lock or remote global
resource authorization system. It assumes an honest provider identity/terminal
contract, a trusted OS owner and local atomic rename/fsync durability. It cannot
defend same-user malicious code/storage rollback or a provider lying about identity.

## Recovery and tests

PID death, rebooting an application, a released flock and an empty client queue
are never remote completion proof. Plain release cannot erase UNKNOWN. Existing
`reconcile_external`/ledger reconciliation require matching owner/scope and trusted
terminal/inventory evidence. HTTP recovery checks provider identity before GET of
the recorded job; no POST is retried and missing Job IDs require complete trusted
inventory. ROS Trigger has no generic cancel/status query; its result-lost case
remains UNKNOWN without an independent same-invocation terminal oracle.

Missing/damaged registry or ledger state must remain blocked. Restore only trusted
durable state and reconcile actual provider inventory; do not delete state, change
directory/scope or initialize another empty namespace as a recovery shortcut.
An actual provider epoch change at a reused endpoint also requires controlled
deployment reconciliation; it does not silently clear the prior epoch's work.

Tests use new isolated directories and patch **only the private registry storage
location**; every application in each fixture shares that same location. The
production root selection, including rejection of environment overrides, has its
own regression. The real Service exception injector replaces only the test worker
executable locator to run the actual ros_worker with a post-start spin_once fault;
identity/ledger checks and DDS stay real. Normal DDS tests use the installed worker
and its unmodified executable/argument validator. No secret material is archived.

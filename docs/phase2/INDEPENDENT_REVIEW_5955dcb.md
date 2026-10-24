# Independent Phase 2 review

**Recommendation: FAIL.** One P1 and two P2 findings remain. This is an independent code/evidence review plus a newly executed unit suite and deterministic signed in-memory boundary probes. It is **not** a new independent execution of the 18 SITL/Gazebo physical scenarios.

Reviewed HEAD: `5955dcb26d2fc712ebb980a04e07e666b0bde4e8`.
Development baseline: `148a224fae4a652b8f250be827d8e79a9e41bbf9`.
Formal regression code: `936f25d55e163be2703a98bcff6cea44a606999f`.
Reviewer writes are confined to this ignored `independent-review/` directory. Production source, tests, configuration and Git are unchanged.

## Findings

### P1 — Cancelling a native flight run can transmit the old queued flight target before recovery

Location: `src/vehicle_autonomy/app/bootstrap/simulation_runtime.py:525-531` (same ordering pattern in Rover recovery at 542-549).

`end_run()` queues a LOITER recovery and invokes `cycle()` while the original run lease, both SEND gates, and original queue remain active. It does not call the existing `cancel_pending_requests()` / `VehicleExecution.cancel_pending()` first. Consequently, the writer drains an already admitted but **not yet transmitted** old request ahead of recovery, after cancellation has begun. Final revocation at 587-589 is too late.

Independent reproduction: create the existing signed Plane fixture at armed LOITER, height 50 m and speed 17 m/s; admit a `FixedWingTargetEffect` without cycling; call `end_run()`. The first transport write is `COMMAND_INT / DO_REPOSITION=192`, followed by the intended `COMMAND_LONG / mode LOITER=12`. Before cancellation there were zero writes. Full decoded output: `boundary_probe.log`, case `cancel_pending_native_target`.

This can change the aircraft's destination during cancellation, and pending same-number mode commands can additionally block recovery pending their ACK/state timeout. The unique writer and SEND checks still run; the defect is that the cancelled intent retains valid authority while recovery drains the queue. Existing physical cancellation scenarios cancel only after their previous command has completed, so their PASS does not exercise this boundary.

Required remediation: fence/cancel all still-ACCEPTED requests belonging to the exiting scope before scheduling recovery, preserving truthful uncertainty for already transmitted one-shot commands. Add deterministic cancellation/shutdown tests for queued native target/mode requests and Rover RTL, then run the relevant owned physical regression.

### P2 — The Action handoff barrier ignores native flight and native RTL activity

Location: `src/vehicle_autonomy/app/bootstrap/simulation_runtime.py:439-453`, in combination with the new native activity latches at 479-485.

`authorize_action()` checks only `VehicleExecution.active_stream_ids()`. Native TAKEOFF/GUIDED/LOITER/RTL/AUTOLAND/DO_REPOSITION and Rover RTL are one-shot commands and never appear in that set. The runtime therefore revokes the old lease and grants the next Action SEND/Lease without any vehicle-specific safe handoff or a check of outstanding native command outcome. This path existed for streamed motion before this change; the new native command support extends it without extending its barrier.

Independent reproduction: transmit a native TAKEOFF from fresh stationary armed ground, with its outcome still `TRANSMITTED`; immediately call `authorize_action('replacement', allow_send=True)`. It succeeds with `_plane_flight_requested=True`, the old TAKEOFF unresolved, and a live new Action lease/system SEND. There are zero recovery or handoff writes. Full output: `boundary_probe.log`, case `native_takeoff_action_handoff`.

The versioned architecture requires safe, vehicle-specific handoff before granting the replacement writer. A fresh stationary ground sample is specifically inadequate in this already transmitted TAKEOFF window. Plane being absent from the business Mission catalog reduces current exposure but does not make the explicit runtime handoff safe; Rover native RTL has the same one-shot versus stream mismatch.

Required remediation: include native activity/outcome in the handoff state machine. Refuse unresolved TAKEOFF handoff, validate an authorized fresh continued-flight handoff for Plane, and require HOLD plus fresh post-confirmation zero motion for Rover where a stopped handoff is intended. Preserve session/TTL/generation fencing.

### P2 — Reconnecting read-only drops unresolved native-flight stopping uncertainty

Location: `src/vehicle_autonomy/app/bootstrap/simulation_runtime.py:208` and `:600`.

`connect()` unconditionally clears both native activity latches. After an unconfirmed native-flight link loss, reconnecting into read-only mode therefore removes the only condition causing `shutdown()` to report the unresolved flight. It does so even after the new session supplies fresh armed, airborne, moving telemetry and no new run has been authorized.

Independent reproduction: complete an armed airborne LOITER request, lose the link, and call `end_run()`; the result correctly is `{'fixed-wing-flight': 'UNCONFIRMED'}`. Reconnect without authorizing a new run, feed fresh height 50 m / speed 17 m/s / armed telemetry, then call `shutdown()`: the result is `{}`, with `_plane_flight_requested=False`. Full output: `boundary_probe.log`, case `read_only_reconnect_loses_flight_uncertainty`.

This does not report `CONFIRMED` or re-enable SEND, but it loses a known unresolved safety outcome solely because the transport epoch changed. The analogous Rover latch is cleared at the same line. The formal Plane reconnect scenario immediately authorizes another run, so it does not check the read-only reconnect/shutdown boundary.

Required remediation: retain unresolved native-flight/recovery uncertainty independently of the command/session epoch, and reconcile it only with qualified new-session physical evidence or an explicit validated handoff. Do not retain old write authority or replay old commands.

## Independently executed checks

- `.venv-migration/bin/python -m unittest discover -s tests -v`: **409 tests, OK, 40.653 s**. Full output: `unit.log`.
- `PYTHONPATH=. .venv-migration/bin/python artifacts/phase2-control/independent-review/boundary_probe.py`: completed successfully; all three above behaviors reproduced using existing signed in-memory telemetry and actual MAVLink encoding. No SITL or hardware was opened. Script and output are retained.
- `PYTHONPATH=. .venv-migration/bin/python artifacts/phase2-control/independent-review/evidence_check.py`: independently recomputed **all 582 indexed file sizes/SHA256 values**, with zero missing/mismatched files. Current source hash equals formal start/end hash: `45347149aa68fd0a752bd67cfb2c59034c62dd228539deed45c82e9c3c824e46`. All three explicitly owned SITL binary hashes match the formal record.
- Independently read all 18 formal scenario summaries/manifests: commits match the frozen code; the listed private state/config resources are absent; recorded cleanup says no remaining owned process groups and released ports; all signing proof files exist. These observations corroborate the records, but do not retroactively prove process/port state at each original teardown.
- Nine protected historical reports/indexes compare byte-for-byte against the development baseline. The development claim that 724 historical raw files were rehashed is present in the indexed historical audit; that entire historical raw-file set was not independently rehashed in this review.
- `git status --short` is empty. The isolated ArduPilot source HEAD is the documented `b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`, with a clean working tree.

## Code and physical evidence assessment

The Plane translator uses native `COMMAND_INT DO_REPOSITION`, geographic latitude/longitude and AMSL altitude, and native TAKEOFF/AUTOLAND modes. The local pinned ArduPilot implementation confirms DO_REPOSITION enters GUIDED and adopts a waypoint, normal NAV_TAKEOFF is the QuadPlane-only command path, AUTOLAND requires flight and captured takeoff direction, and RTL_ALTITUDE uses metres. The new model has free rolling wheels, aerodynamic/propeller simulation and a level runway initial pose; no launch impulse, teleport, or substitute Copter velocity command was found in the reviewed model/scenario. Rover uses native RTL=11 and its AP mode implementation navigates HOME/rally then stops a non-boat.

Formal Plane target evidence has strictly ordered signed ACK < matching target echo < GUIDED heartbeat in both rounds, and production completion is explicitly scoped to **target configuration**, not physical arrival. The contradictory-target invalidation fix is present. Signed receive verification and retained watermark remain in the shared codec/session path. The writer still holds the authority lock through the final SEND/Lease/TTL/session/generation checks and transport call. No second production vehicle writer, hardware-control unlock, signing bypass, or change to the receive-only hardware composition was identified in the reviewed diff. The fixed-wing safety policy rejects Copter streams/zero-stop and unsafe airborne Disarm; its ground/latched-flight exit tests cover several important stale-state cases but not the findings above.

Independently recalculated from retained Plane trajectory rows, rather than accepting summary PASS:

| Measure | Round 1 | Round 2 |
| --- | ---: | ---: |
| Low-height (<1 m) / >8 m/s TAKEOFF samples | 20 | 20 |
| Maximum displacement among those ground-roll samples | 39.279 m | 39.466 m |
| Maximum flight height above baseline | 50.953 m | 50.680 m |
| AUTOLAND <0.25 m and <1 m/s continuous retained interval | 5.006 s | 4.206 s |
| Last retained ground HOME error | 1.911 m | 1.290 m |
| Last retained runway cross-track error | 0.944 m | 0.821 m |
| Last retained armed state | false | false |

The final retained HOME errors above are later, post-command samples, so they differ from the report's earlier landing-threshold instant; both remain comfortably inside the stated 80 m/15 m contract. Flight mode sequences contain TAKEOFF→GUIDED→LOITER→RTL→AUTOLAND. These retained measurements support real wheeled takeoff and landing in the developer-owned Gazebo runs. They are not a claim that this reviewer re-flew them. LOITER/RTL segments remain limited continuation/mode evidence, not a complete orbit/return certification.

The original Rover profile and acceptance-threshold resource files are unchanged in the diff; the new Rover RTL profile retains the original safety limits, effect TTL and lease durations. The harness separately runs both original Rover physical cases, the new native-RTL cases, Copter physical cases, probes and the old fault sets in each round. Two-round 18-scenario results and the indexed raw evidence are internally consistent. No deleted test or relaxed original Rover/Copter physical threshold was found. The new failures above are uncovered lifecycle boundaries despite these preserved regressions.

## Limitations and disposition

No independent SITL/Gazebo launch was needed to establish the deterministic writer/handoff defects. No physical scenario was newly re-executed. Historical MACs cannot be recomputed after legitimate temporary-key destruction; I verified retained signing proof structure and signature ordering, not regenerated historical authentication. No credentials were read or printed. External ArduPilot, production code, tests, configuration, existing evidence and Git were not modified. No perception/AI/next-stage work was started.

Correct the three findings and rerun the relevant full unit/owned simulation gates before re-audit. The development physical evidence remains useful and preserved; it does not supersede the reproduced lifecycle failures.

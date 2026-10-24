# Independent remediation code review — 634c30b

Reviewed HEAD: `634c30b02bc7f7b94030e14c2899f3abd375c716`.
Prior reviewed HEAD: `5955dcb26d2fc712ebb980a04e07e666b0bde4e8`.

**Code-stage result: the three previously reported defects are addressed. No additional P1/P2/P3 finding was identified in this focused remediation review. Overall acceptance/recommendation remains pending independent verification of the completed frozen physical evidence.** This document does not declare the currently running two-round simulation regression passed.

The original independent FAIL report and probes in `../independent-review/` were not changed. Their SHA256 values are recorded in `code-review-metadata.json`. All writes made by this reviewer are confined to this new ignored directory. No extra SITL/Gazebo instance was started; no production source, tracked test, configuration or Git data was modified. No keys were read or printed.

## Assessment of the three fixes

1. **Prior P1, queued native command written during cancellation:** `SimulationRuntime.end_run()` now calls the existing `cancel_pending_requests()` before scheduling native recovery or invoking its writer loop. The existing execution cancellation path acts only on ACCEPTED commands in the current Action/run and leaves transmitted one-shot outcomes intact. A queued Plane target/AUTOLAND and Rover RTL are therefore fenced before LOITER/HOLD recovery. The change reuses the existing command-port cancel contract and retains its final writer authorization checks.
2. **Prior P2, native Action handoff without a barrier:** `authorize_action()` now checks both native activity latches along with active streams, before changing any lease, generation, scope or SEND gate. It conservatively refuses replacement while native motion remains unresolved. This implements rejection, not a newly certified continued-flight handoff. The current Action retains its valid confirmation path after the refusal. An explicitly ended/recovered run remains the supported boundary.
3. **Prior P2, loss of uncertainty on read-only reconnect:** `connect()` no longer clears the native activity latches. It still clears positive session state and all old authority through the existing reconnect path. Read-only shutdown consequently retains UNCONFIRMED without issuing recovery commands. For Plane, the existing fresh VALID stationary disarmed-ground predicate can reconcile the retained hazard; stale ground evidence cannot. This does not transfer an old command or old lease into the new epoch.

The production change is narrowly scoped to ten changed lines in `simulation_runtime.py`. No protocol, signing verifier, writer, Safety limits, hardware composition, or original Rover/Copter physical-threshold file is changed by this remediation commit.

## Independent execution

- `.venv-migration/bin/python -m unittest discover -s tests -v`: **415 tests, OK, 41.836 seconds**. Full output: `unit.log`.
- `PYTHONPATH=. .venv-migration/bin/python artifacts/phase2-control/independent-review-634c30b/boundary_probe.py`: **8 independent signed-memory scenarios passed**. Full code/output: `boundary_probe.py` and `boundary_probe.log`.

The additional reviewer-authored probes cover:

- Plane and Rover handoff refusal before initial command transmission and after signed completion; both `allow_send=False` and `allow_send=True` preserve the entire prior authority scope and produce no writer call.
- Queued Plane geographic target and queued AUTOLAND cancellation: the old request becomes CANCELLED and the sole emitted recovery is mode LOITER=12.
- Retained TAKEOFF uncertainty across a new receive-only session: stale disarmed-ground evidence yields UNCONFIRMED, while qualified fresh stationary disarmed-ground evidence clears the hazard; both cases issue zero new writes and retain disabled SEND/no lease.

The repository's six new boundary tests also passed as part of the full suite. Their assertions meaningfully check decoded wire commands, old-request phase, preserved old confirmation, authority identity/generations, new session identity, and absence of reconnect writes. They cover both Plane and Rover for handoff and negative uncertainty, and both queued target and mode cancellation.

## Physical-test changes reviewed, with results not yet accepted

The formal harness now requires the added Plane queued-cancellation, handoff, and read-only reconnect sections, plus Rover queued cancellation/handoff, to pass. The Plane flight scenario compares actual emitted frames to exactly one native LOITER and verifies the old target is CANCELLED; the Rover scenario similarly demands exactly one HOLD and no queued RTL write. The actual TAKEOFF window scenario verifies handoff refusal before application ACK/state observation and read-only reconnect/shutdown without added writes. These additions preserve the original physical gates and fault-set requirements.

Their construction is appropriate for the reported defects, but the full 18-scenario run is still in progress at this code-review stage. Developer-side earlier targeted PASS and the old 936f25d physical results are not substituted for the new frozen-run evidence. This reviewer has executed memory/unit checks only and has not newly replayed physical flight or driving.

Source hash independently recomputed during this stage: `59907b85b53f6be51175d0c40a9427a6dbd4e5f64f9165ccec7a22eaccdd9085`. `git status --short` remained empty. Completed formal evidence must subsequently match the same source, commit, original thresholds, required scene sections, authentication proof records, and owned cleanup before a final re-audit recommendation is issued.

# Independent final evidence review — Phase 2 remediation

**Recommendation: READY FOR RE-AUDIT.** No unresolved P1/P2/P3 finding was identified in this follow-up code and evidence review. The previous P1 and two P2 findings have targeted code fixes, independently passing memory/unit tests, and corroborating real-simulation records in both frozen rounds. This is not a declaration of hardware readiness or expansion into the next stage.

Tested code: `634c30b02bc7f7b94030e14c2899f3abd375c716`.
Evidence-review starting archive: `800372bde3147ae41bcc4d60dad585b7731159e7`.
Final archive inspected, including explicit old-chart locations: `3067b2153bc1d3e4a76f99b19a706d8978a11184`.
Subsequent changes from the tested commit are documentation only. The current source/input hash independently remains `59907b85b53f6be51175d0c40a9427a6dbd4e5f64f9165ccec7a22eaccdd9085`.

## Scope and actual execution

I independently executed the full **415-test unit suite**, with **OK, 41.836 seconds**, and **8 reviewer-authored signed-memory boundary scenarios**, all passing. Those executions and the focused code findings are preserved in `CODE_REVIEW.md`, `unit.log`, and `boundary_probe.{py,log}` in this directory. The code has not changed since those executions.

For this evidence stage, I independently executed `final_evidence_check.py`, whose complete output is retained in `final_evidence_check.log` and `final_evidence_check.json`, and independently inspected external repository provenance in `external_provenance.json`. The final checker completed successfully with an empty issues list.

The **18 SITL/Gazebo scenarios were executed by the developer**, not newly flown or driven by this reviewer. I reviewed their frozen source, manifests, raw command/state/proxy records and physical trajectories. I did not start another SITL/Gazebo process, connect hardware, modify production code/tests/configuration/Git, read credentials, or print keys. Reviewer writes are confined to this ignored review directory. The original independent FAIL and its probes remain unchanged.

## Evidence integrity and provenance

- All **625 current indexed files** independently match their expected sizes and SHA256 values. The artifact index and `docs/phase2/phase2-evidence.json` are byte-identical.
- The formal summary, **415 tests / zero failures, errors or skips**, 19 stage exit records, two rounds, 18 scenario summaries, and every vehicle's A–F result agree. Both full rounds identify the tested `634c30b` commit and clean source. The independently reproduced per-scenario broader input hash is `b142130cf84677a12ea69259deeb19bef07d380007993a40725976f331965de7` in all 18 manifests; its input set differs from the suite hash by design.
- The suite start/end source hash matches current source. The three explicitly owned SITL binary hashes, runtime plugin-library bytes and manifest-listed parameter-file hashes match. The freshly installed wheel's **190 production Python files** and **9 new resources** independently match current source bytes.
- All **18 manifests / 22 signing epochs** have retained signing-support proofs recording online verification with the production verifier and an independent pymavlink verifier. I independently decoded their retained HEARTBEAT/ACK frames, checked signed wire flags, source `(1,1)`, timestamp fields and strict order. Native target confirmation also has signed ACK < matching target echo < later GUIDED heartbeat in both rounds.
- Temporary keys were legitimately destroyed. I did **not** regenerate historical MACs, and structural decoding of signed frames is not represented as independent MAC verification. The preserved online verification records, source inspection and separately executed signed-memory tests define the authentication evidence available here.
- All 18 formal scenarios record credentials removed, process teardown and released ports; the registered state/private resources are currently absent. An independent current scan of **69 task-owned manifests** found **zero remaining registered state/private resources, zero live processes with matching recorded PID/start identity, and zero listeners/bindings on the audited TCP/UDP ports**. These current checks corroborate retained teardown records; they do not retroactively observe original teardown time.
- The external ArduPilot repository is at the pinned `b5fbe26515eddb9277e1b5e7a4fcf3f37cf449a6`, clean with no untracked files. The Gazebo plugin is at pinned `3ec51428fd43deb7b71137192ba16394b450d78e` and tracked-clean; its seven pre-existing untracked CUADC model/world paths remain present. I do not call the entire plugin directory clean or claim to have removed those user resources.

## Repaired lifecycle boundaries in the physical records

**Old queued work is fenced before recovery.** In each Plane flight run, raw runtime events show `cancelled-queued-target` becoming CANCELLED. Between its admission and run exit, the complete recorded writer list contains exactly **one COMMAND_LONG mode LOITER=12**, with no COMMAND_INT old-target write. Each Rover native-RTL run similarly records the queued RTL becoming CANCELLED, exactly **one mode HOLD=4 recovery frame**, and zero old queued RTL writes. The old transmitted command outcomes remain separate from cancellation.

**Native Action handoff is refused before authorization changes.** Both Plane flight cases, both real TAKEOFF cancellation-window cases and both Rover RTL cases execute the shared assertion checking Action identity, lease, authorization/send generations and both SEND gates before/after refusal. The records say rejection and unchanged authority, without a replacement authorization event. Independently authored memory probes also exercised both SEND choices and both initially queued and completed native activity; refusals leave authority unchanged and normal current-Action confirmation still works. The current implementation conservatively rejects such handoffs; it does not certify an automatic continued-flight Action handoff.

**Read-only reconnect retains negative uncertainty without a new write.** In each separate real TAKEOFF window, the flight controller's accepted mode ACK is observed at the proxy while withheld from the application. The application's old ground sample remains unchanged; the command becomes UNKNOWN and flight stopping remains UNCONFIRMED. Later independent motion is **0.8691 m / 0.8286 m**. Each run's full writer list contains only Arm and one TAKEOFF; there are **zero writes after read-only reconnect**, a distinct new session with armed telemetry, and final shutdown still reports `fixed-wing-flight: UNCONFIRMED`. Independent memory tests additionally cover both vehicles and distinguish fresh disarmed stationary ground from stale ground evidence.

## Independent physical measurements from retained trajectories

The Plane takeoff/landing checks below use Gazebo truth rows rather than mode ACK or summary PASS. Native target position is independently converted from the signed geographic EKF origin to local ENU; its acceptance interval is measured after target confirmation. Turn accumulation includes the physical segment beginning at native-target command admission, matching the scenario's measured interval.

| Retained Plane measurement | Round 1 | Round 2 |
| --- | ---: | ---: |
| TAKEOFF samples below 1 m and above 8 m/s | 20 | 20 |
| Maximum ground-roll displacement among those samples | 39.261 m | 39.354 m |
| Maximum height above initial baseline | 50.616 m | 50.911 m |
| Target within 120 m, altitude error ≤7 m, speed 8–28 m/s continuously | 4.206 s | 4.303 s |
| Accumulated target-flight turn | 1.57659 rad | 1.60578 rad |
| AUTOLAND height <0.25 m / speed <1 m/s continuously | 4.909 s | 4.904 s |
| Last retained ground HOME error | 1.789 m | 1.603 m |
| Last retained runway cross-track error | 0.841 m | 0.864 m |
| Last retained armed state | false | false |

These meet the declared 10 m rolling takeoff, 45 m climb threshold, 90° turn, 3 s target interval and 3 s landing interval, within the runway/HOME and envelope limits. The last retained HOME errors are later than the report's landing-threshold instant (0.901 m / 0.855 m), explaining the difference; both remain inside the original declared 80 m/15 m Plane contract. The `<1 m/s` landing gate is preserved as such, not reinterpreted as exact zero speed. The model, native command translation and local pinned ArduPilot semantics reviewed previously support conventional wheeled TAKEOFF and AUTOLAND; no hand launch, teleport or Copter hover substitute was found.

Rover native RTL cancels during actual translation before arrival, then physically stops and resumes native return. Reported HOME errors are **0.53960 m / 0.53874 m**. Independently differencing retained Gazebo positions over a 0.5 s window yields **2.0028 s / 2.0030 s** continuously within 0.75 m and below 0.10 m/s. Rover trajectory rows preserve host time rather than the original oracle's dense simulation-time samples, so this is corroboration in the qualified speed-one composition, not a reconstruction of every internal oracle sample. The original telemetry and online oracle checks remain recorded separately.

Copter raw observations finish disarmed at HOME errors **0.001885 m / 0.001624 m**, with essentially zero relative landing height. Its retained Goto errors are **0.14974 m / 0.11466 m**, below 0.75 m. Original Rover and Copter scenario thresholds, profiles and telemetry parameters independently compare byte-for-byte against the development baseline. Both original Rover physical cases remain separate from the new RTL fixture. I also independently checked the presence and passing records of all **60 required original fault-case instances** and **28 prior-remediation checks** across two rounds/two original vehicle types.

Mode/target adoption and physical behavior remain distinct throughout this assessment. Plane LOITER/RTL segments are bounded continued-flight/mode checks, not certification of a complete orbit or complete native RTL trajectory. Native fence parameters are verified; fence-breach recovery is not newly certified.

## Preservation of the original failure and evidence

The original FAIL report and probe log still match the SHA256 values recorded during the code review. Nine protected Phase 1 reports/indexes independently compare byte-for-byte with the development baseline.

For the old candidate's **582 indexed contents**, **581 remain at their original paths**. The old index's `docs/phase2/plane-flight-truth.png` path now intentionally displays the repaired runs. Its original **291,880 bytes**, SHA256 `fc0acf370035915ffc8abc3221b7856ae39049c95a2a2bf4b81242439dfdc812`, independently match both `artifacts/phase2-control/final-plane-truth.png` and the separately archived `docs/phase2/plane-flight-truth-936f25d.png`. `docs/phase2/evidence-locations.json` explicitly records this relocation. The original expected hash and original independent FAIL are not rewritten. The earlier zero-mismatch candidate-preservation record predates replacement of the rolling documentation plot and is not represented as a current all-original-path result.

The developer's wider historical audit records 739 non-sensitive historical files. This review independently rehashed the 582 prior-candidate contents and compared the nine protected historical reports; it does not relabel the developer's entire 739-file audit as a new reviewer execution. Destroyed EEPROM/key material was neither read nor restored.

## Final disposition and limits

The three original lifecycle findings are addressed in code and have corroborating frozen two-round real-simulation evidence. No further P1/P2/P3 finding remains from this review. **READY FOR RE-AUDIT** is the appropriate requested recommendation.

This conclusion covers the explicit owned localhost Rover/Copter/Plane simulation composition and the stated native interfaces/measurement contracts. It does not extend to hardware control, end-to-end real-vehicle authentication, complete Plane orbit/RTL/fence-breach certification, general Plane Mission/Web availability, perception/AI, or another development stage. The actual reviewer executions remain the 415-test suite, 8 memory probes and evidence-verification scripts; the physical scenarios remain developer executions independently reviewed from retained evidence.

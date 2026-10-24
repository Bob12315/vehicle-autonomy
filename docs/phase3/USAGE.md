# Standalone Action Lab

This composition only accepts explicitly registered live project-owned SITL
fixtures. It cannot open hardware, serial devices or arbitrary remote MAVLink
endpoints. The normal read-only hardware deployment is unchanged.

In the isolated development environment, launch a new fixture (choose a fresh
run directory, never an existing user directory):

```bash
VAF_SIMULATION_SITL_BIN_DIR="$PWD/artifacts/phase2-control/ardupilot-source/build/sitl/bin" \
  .venv-migration/bin/python -m tests.simulation.action_lab_fixture \
  --kind rover --run-dir artifacts/phase3-actions/manual-rover-UNIQUE
```

In another terminal:

```bash
.venv-migration/bin/python -m vehicle_autonomy.app.web.action_cli \
  --simulation rover=artifacts/phase3-actions/manual-rover-UNIQUE/manifest.json \
  --token-file runtime/action-lab/token --port 8770
```

The installed wheel also provides `vehicle-autonomy-actions`. The example has
deployment SEND disabled. To control that owned fixture, explicitly add
`--allow-send` and separately check SEND on each writing Action in the UI.
Open `http://127.0.0.1:8770`, enter the token from the local private token file
and connect. Never put credentials in URLs, screenshots, reports or logs.

Metadata and fields come from the same Registry as execution. Start with
GetVehicleState; SetMode GUIDED and Arm precede Rover/Copter motion. Plane
Arming uses MANUAL, Takeoff uses the parameter-readback-verified 50 m native
TAKEOFF profile. Plane has no velocity, hover or airborne Disarm Action.

Rover Drive/Turn cancel by zeroing the old stream, then requesting AP HOLD and
observing the existing physical stop barrier. Select SetMode GUIDED again
before the next movement. Copter motion reuses the existing zero/stream stop
barrier. A terminal label alone is never parking proof; inspect `safety` and
the command results. A Query does not revoke a concurrent motion lease.

Successful airborne Plane operations retain the control resource and scope.
Enter the previous successful retained Action ID as `continuation_of` and
explicitly authorize the next Action. This performs the existing bounded
LOITER recovery, old-queue fence, authority revocation and read-only fresh
session before a new grant. Failed/cancelled/UNKNOWN actions cannot continue
this way. Plane cancellation remains UNCONFIRMED while airborne. AutoLand
requires touchdown relative to the signed arming ground reference, low speed,
settling and authenticated disarm; configuration ACK alone is insufficient.

The home reference is captured from authenticated local position on completed
Arm, consistent with the audited owned AP unlocked-home convention. AP can
reset home on a later Arm; the launch origin is not silently reused. It is not
an independent terrain estimate. Gazebo truth verifies physical acceptance.

Every vehicle has its own owner thread; the scheduler is independent of HTTP
connections. Browser refresh/closure does not cancel an Action. Use the same
instance ID to manage it after reconnect. HTTP mutations require Bearer auth,
CSRF header and an idempotency request ID. Instances, feedback, history and
effects are bounded; exhausted record budgets reject new work rather than
evicting a hazardous reservation. Restarting a Lab never resumes old work.

Only one Lab owner may hold a fixture's OS advisory lock. The same signing
epoch also has a durable, non-secret receive floor, persisted before accepting
evidence. A reservation covers at most 128 future signing timestamp increments
to avoid per-packet fsync stalling the unchanged 100 ms safety loop. The live
verifier still checks every MAC and strictly increasing real watermark. A new
process rejects through the reserved floor, potentially losing up to 128 future
timestamp increments; wait for new authenticated data. It never lowers the
floor. Corrupt persistence fails closed. A new owner cannot control an already
armed vehicle whose previous scope may be unresolved; create a new owned
fixture if fresh disarmed stationary ground cannot be established. These
files are not a MAVLink request UUID or an absolute anti-replay claim.

Stop the Lab before stopping the fixture. Only the fixture launcher owns and
destroys its registered temporary SITL state and provisioning files. It does
not touch independent ArduPilot installations. Non-secret logs, floor and
lock files remain as evidence; no EEPROM or temporary key remains.

Formal acceptance (requires Chrome and the isolated `test-browser` extra):

```bash
./scripts/test_phase3_actions.sh --allow-send \
  --sitl-bin-dir artifacts/phase2-control/ardupilot-source/build/sitl/bin \
  --run-dir artifacts/phase3-actions/acceptance-FROZEN-SHA-UNIQUE
```

The code must be committed and clean before this command. It runs two actual
Action/HTTP/Gazebo rounds and the original two-round three-vehicle Phase 1/2
regression, never substitutes unit doubles for vehicle physics, and preserves
failed evidence. See the final report for the actual tested commit and result.

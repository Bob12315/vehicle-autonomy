# Phase 6 fault injection and recovery (2026-10-02)

Status: **all fault gates and both normal regressions passed**.
One-command repeated regression and final completion audit remain open.

## Implementation and boundaries

`tests/simulation/faults.py` transparently forwards original MAVLink frames
through an owned localhost TCP proxy. It can drop telemetry, delay pose frames,
drop command ACKs, and disconnect its own sockets. It constructs no command.
Commands still enter the common SimulationRuntime as typed Effects and pass
Execution, explicit vehicle Safety, both SEND gates, a scoped lease, the
vehicle translator, and the sole writer. Gazebo is a read-only Oracle.

Runtime closes and revokes authority on uncertain transport writes, invalid
source/world timestamps, missed cycles, and clock regression. Command ACK
without a later confirming mode/arm state expires to UNKNOWN. Link reset also
marks ACKNOWLEDGED commands unknown rather than retaining a success claim.
The simulation-only source clock maps SITL boot milliseconds to host monotonic
time per connection. Repeated/delayed messages keep their source age; source
reset requires a new epoch. This composition requires speed-one SITL and fails
closed on excessive clock skew. It is not a hardware clock synchronization
implementation.

`tests/simulation/launch.py` gives every world a unique name, selects an unused
SITL instance and corresponding TCP/JSON ports, and updates model/world/profile
together. It directly launches the SITL binary to avoid sim_vehicle's
instance-zero broad process cleanup. Only recorded owned process groups are
terminated. Fresh SITL state directories, commands, versions, parameters,
PIDs, exit codes and port-release results are retained in a manifest.

## Matrix and evidence

Each deterministic test runs against **both** vehicle profiles, the actual
codec/session/Execution/writer, and an injected byte transport and clock.
`tests/simulation/test_faults.py` covers all 18 required fault rows:

| Plan row | Automated evidence |
| --- | --- |
| Telemetry stale | all RX timeout unit test and physical `long_disconnect` |
| Temporary disconnect | unit test and physical socket cut during motion |
| Long disconnect | heartbeat deadline unit test and physical all-RX drop |
| Reconnect | new epoch, empty old queue, zero TX before new authorization |
| SITL restart | terminate/restart only owned binary; old queued Mode rejected; new authorized Mode/Arm/Disarm |
| Runtime restart | unit instance reset and actual separate process restart, initial SEND false, no lease or TX |
| Duplicate Effect | equal repeated ID writes once; unequal content raises |
| Expired Effect | fake clock admission rejection and zero writes |
| Unauthorized Effect | both gates, missing/wrong lease scope, zero writes; live default gate rejection |
| Cancelled Effect | queued cancellation zero writes; live moving Cancel confirms zero state and truth stop |
| Command timeout | accepted ACK but target state absent expires UNKNOWN |
| ACK timeout | lost Arm ACK unit test no retry; live Mode ACK dropped despite matching state stays UNKNOWN |
| Deadman | one-second deadline, zero writer output, later zero state and stable truth speed |
| State timeout | pose/attitude dropped with heartbeat retained, no new motion |
| Interrupted velocity | uncertain-write and missed-cycle unit tests; physical moving TCP cut |
| Shutdown during motion | normal shutdown and actual SIGTERM to owned moving Runtime; bounded stop and truth |
| Old replay | queued Mode behind a same-command ACK fence rejected on cut, zero replay in new epoch |
| Stale-state motion block | stale/future/wrong-domain state admission and final writer fence |

The replay fixture uses a same-command ACK fence because bytes already buffered
before socket closure can remain readable for one cycle. Initial fixtures
wrongly assumed immediate EOF and allowed the supposedly queued setpoint to
be transmitted before EOF was observed. Both failed reports are retained;
the final fixture verifies a genuinely untransmitted command without changing
the required rejection/zero-replay assertions.

`tests/simulation/test_source_clock.py` also verifies repeated source times,
3.5-second RX delay retaining 3.5-second age, backwards/ahead timestamps and
new-epoch mapping. Existing runtime fake packets now advance their source boot
time with the fake clock, instead of falsely reporting boot time zero forever.
No acceptance threshold or existing assertion was relaxed.

Commands:

```bash
python -m unittest discover -s tests -q
python -m tests.simulation.fault_scenario --kind rover --allow-send
python -m tests.simulation.fault_scenario --kind copter --allow-send
python -m tests.simulation.copter_scenario --allow-send --full
python -m tests.simulation.rover_protocol --allow-send --full
```

Unit suite: **117 tests passed**, zero skips. Rover full physical fault report:
`artifacts/simulation/fault-rover-6e94743f/summary.json`. Deadman transmitted
zero after 1.001 s and stabilized at 0.00204 m/s. Cancel stabilized at
0.000426 m/s. SIGTERM stop was telemetry-confirmed and its stable truth speed
was 0.00229 m/s. All disconnects revoked SEND/lease, renewed session IDs and
sent zero commands before new explicit authorization. Restarted Runtime was
a different PID, with no lease and zero TX. SITL restart accepted only the
new explicit authorized run. Owned ports were released.

Copter full fault report: `artifacts/simulation/fault-copter-c9a6c2cd/summary.json`.
Deadman zero was transmitted after 1.001 s; stable truth speed was 0.00968 m/s.
Cancel stabilized at 0.0205 m/s, normal shutdown at 0.0117 m/s and SIGTERM
at 0.0282 m/s, all below the unchanged 0.15 m/s threshold. Both process
restarts, ACK timeout, stale/delayed telemetry and old queue isolation passed.
Both runs released their owned ports. The transparent proxy unit test verifies
original frame bytes, ACK filtering, delay, and old delayed-frame discard.

Normal regressions passed at `artifacts/simulation/copter-scenario-6748b866/`
and `artifacts/simulation/rover-protocol-2a91d307/`. Copter Goto truth error
was 0.115 m and RTL home error 0.00129 m with ground contact and disarm.
Rover forward/reverse projections were +1.030/-1.028 m; left/right and both
pivots exceeded 45 degrees with the correct sign; Goto truth error was 0.481 m.
All stable stop windows passed and all owned process ports were released.
Dependencies remain ArduPilot `b5fbe26515`, plugin `3ec5142`, Gazebo 8.15.0,
Python 3.12.3, pymavlink 2.4.49 and pyserial 3.5.

## Physical guarantee

Connected Cancel/deadman/shutdown outcomes require both later telemetry and
fresh Gazebo speed below the original threshold for two seconds. At link loss,
software cannot prove that a zero setpoint reached the vehicle; the report
therefore says **UNCONFIRMED** even if ArduPilot independently stops. No real
hardware, serial port or archived CUADC tree is changed. One-command repeated
regression and the final completion audit remain Phases 7 and 8.

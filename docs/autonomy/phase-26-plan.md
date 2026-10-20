# P26 frozen acceptance — Rover Autonomy Simulation V1

2026-10-21. The support scope remains P21–P25's two front-drive simulated
Rovers, telemetry control localization, bounded Nav2 planning/replanning and
recorded/simulated observations. No hardware motion or active SLAM localization.

Mandatory gates: complete root unit suite (zero skips); Copter/Rover base
motion and fault suites; both Application restart/reconnect tests; repeated
Rover route; all 15 integrated navigation/map cases; one continuous Rover
Application for at least 600 seconds and 100 distinct completed disarmed-mode
Missions. This is a ten-minute bounded endurance qualification, not an
hours-long or overnight reliability claim.

Endurance records monotonic duration, task/effect IDs, duplicate request
idempotence, SEND revocation after every task, fresh telemetry and independent
Gazebo truth, process RSS/CPU/threads/FDs, log bytes, final socket/port/process
cleanup. After a 10-task warmup: RSS growth <=32 MiB, FD growth <=4, thread
growth <=2, mean application CPU <=70% of one logical core; application log
<=25 MiB. Limits are frozen before the run. Continuous observations retain
source age. Reaching a finite session request budget requires a read-only
restart and new authorization; historical IDs must never be evicted to permit
replay. Movement cases retain their previously accepted physical bounds.

`scripts/test_hardware_ready_simulation.sh --allow-send` is the reproducible
entry. Stages run sequentially with deadlines, preserve failures and continue
independent cases. Missing dependencies are BLOCKED, executed failures FAIL;
neither qualifies as a complete P26 PASS. Reports retain source commit, dirty
state, input hashes and owned-process manifests. No push or physical device I/O.

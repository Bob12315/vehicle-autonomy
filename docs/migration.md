# Historical application

The former `legacy/cuadc_2026/` tree was removed on 2026-10-23 by explicit
user request after runtime dependency checks and local-data backup. Its 548
tracked files remain available in Git at
`6df9fe91819f430c7a0d8f153ff2b06b86895915`. To inspect a historical file use
`git show 6df9fe9:legacy/cuadc_2026/<path>`. Old archive test commands are
historical evidence, not current checkout instructions.

The old tree included SystemRunner, Action Mission, Web UI, telemetry link,
RKNN, configuration, tests, scripts and historical documentation. No old
business implementation was reintroduced as part of deletion. The current
installable framework has exactly seven core packages under
`src/vehicle_autonomy/`; see the [migration report](ARCHITECTURE_MIGRATION_REPORT.md)
for the file manifest, deletion record, backup location and new commands.

Reuse from Git history still requires dependency and safety review. Hardware
control remains blocked; the readonly composition has no vehicle command port.
Historical PASS evidence does not imply real vehicle or perception readiness.

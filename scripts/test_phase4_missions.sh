#!/usr/bin/env bash
# Own loopback SITL/Gazebo only. All new physical scenes run serially.
set -euo pipefail
vaf_phase4_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
vaf_phase4_python="${VAF_PYTHON:-$vaf_phase4_root/.venv/bin/python}"
cd "$vaf_phase4_root"
exec "$vaf_phase4_python" -m tests.simulation.phase4_harness "$@"

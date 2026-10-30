#!/usr/bin/env bash
# Runs only newly owned loopback simulations, never a hardware connection.
set -euo pipefail
vaf_phase3_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
vaf_phase3_python="${VAF_PYTHON:-$vaf_phase3_root/.venv/bin/python}"
cd "$vaf_phase3_root"
exec "$vaf_phase3_python" -m tests.simulation.phase3_harness "$@"

#!/usr/bin/env bash
set -euo pipefail
VAF_PHASE2_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${VAF_PHASE2_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
cd "${VAF_PHASE2_ROOT}"
exec python -m tests.simulation.phase2_harness "$@"

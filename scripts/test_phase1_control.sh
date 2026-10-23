#!/usr/bin/env bash
set -euo pipefail
VAF_PHASE1_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${VAF_PHASE1_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
cd "${VAF_PHASE1_ROOT}"
exec python -m tests.simulation.phase1_harness "$@"

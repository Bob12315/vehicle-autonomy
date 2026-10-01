#!/usr/bin/env bash
set -euo pipefail
simulation_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$simulation_root"
export PYTHONPATH="$simulation_root${PYTHONPATH:+:$PYTHONPATH}"
exec python -m tests.simulation.harness "$@"

#!/usr/bin/env bash
set -euo pipefail
vaf_center_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$vaf_center_root"
exec "$vaf_center_root/.venv/bin/python" -m tests.simulation.center_suite "$@"

#!/usr/bin/env bash
# Optional ROS environment for an external process; the framework stays ROS-free.
set -euo pipefail
vaf_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
vaf_python="${VAF_PYTHON:-$vaf_root/.venv/bin/python}"
if [[ ! -x "$vaf_python" && -z "${VAF_PYTHON:-}" ]]; then vaf_python=python3; fi
exec "$vaf_python" -m vehicle_autonomy.app.bootstrap.host_environment ros -- "$@"

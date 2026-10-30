#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export VAF_RESOURCE_ROOT="${VAF_RESOURCE_ROOT:-$PWD}"
exec "${VAF_PYTHON:-$PWD/.venv/bin/python}" -m vehicle_autonomy.app.bootstrap.onboard "$@"

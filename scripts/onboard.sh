#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export VAF_RESOURCE_ROOT="${VAF_RESOURCE_ROOT:-$PWD}"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec "${VAF_PYTHON:-python3}" -m vehicle_autonomy.app.bootstrap.onboard "$@"

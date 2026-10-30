#!/usr/bin/env bash
set -euo pipefail
vaf_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
vaf_python="${VAF_PYTHON:-$vaf_root/.venv/bin/python}"
exec "$vaf_python" -m vehicle_autonomy.app.bootstrap.qgc_simulation --allow-send "$@" --kind plane

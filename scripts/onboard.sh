#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${VAF_PYTHON:-python3}" -m deployment.onboard "$@"

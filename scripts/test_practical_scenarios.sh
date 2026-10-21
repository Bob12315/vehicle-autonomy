#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec python -m tests.simulation.practical_suite --allow-send --run-dir "${1:?Provide a NEW evidence directory}" --llm-config "${2:-config/llm.server-tunnel.json}"

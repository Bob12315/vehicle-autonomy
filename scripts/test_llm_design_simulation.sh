#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -lt 1 ]]; then
  echo 'Usage: scripts/test_llm_design_simulation.sh NEW_EVIDENCE_DIRECTORY [LLM_CONFIG]' >&2
  exit 2
fi
python -m tests.simulation.llm_design --allow-send --run-dir "$1" --llm-config "${2:-config/llm.server-tunnel.json}"

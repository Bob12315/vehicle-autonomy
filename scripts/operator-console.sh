#!/usr/bin/env bash
# Independent read-only task/status UI when sensors are absent or maintained.
set -euo pipefail
vaf_install_root="${VAF_INSTALL_ROOT:-$HOME/vehicle-autonomy}"
export VAF_PYTHON="${VAF_PYTHON:-$vaf_install_root/venv/bin/python}"
cd "$vaf_install_root/current"
exec ./scripts/onboard.sh "$@" \
  --state-dir "$HOME/.local/state/vehicle-autonomy-connected" \
  --config "$vaf_install_root/config/hardware-readonly.json" \
  --llm-config config/llm.server-tunnel.json

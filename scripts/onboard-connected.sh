#!/usr/bin/env bash
# Uses only explicit, locally discovered receiver config outside the release.
set -euo pipefail
vaf_install_root="${VAF_INSTALL_ROOT:-$HOME/vehicle-autonomy}"
export VAF_PYTHON="${VAF_PYTHON:-$vaf_install_root/venv/bin/python}"
cd "$vaf_install_root/current"
exec ./scripts/onboard.sh "$@" \
  --state-dir "$HOME/.local/state/vehicle-autonomy-connected" \
  --config "$vaf_install_root/config/hardware-readonly.json" \
  --rs16-config "$vaf_install_root/config/rs16.json" --ros2-humble \
  --llm-config config/llm.server-tunnel.json

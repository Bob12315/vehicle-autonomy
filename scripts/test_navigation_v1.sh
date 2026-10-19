#!/usr/bin/env bash
# Owned localhost SITL/Gazebo only. No physical device entry.
set -euo pipefail
cd "$(dirname "$0")/.."
NAVIGATION_RUN_DIR="${1:-$PWD/artifacts/simulation/navigation-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$NAVIGATION_RUN_DIR"
python -m unittest discover -s tests -q
for navigation_case in tracking cancel map_loss plan_change timeout; do
    python -m tests.simulation.path_following --allow-send --case "$navigation_case" \
        --run-dir "$NAVIGATION_RUN_DIR/$navigation_case"
done
python - "$NAVIGATION_RUN_DIR" <<'PY'
import json
from pathlib import Path
import sys
directory=Path(sys.argv[1])
cases={name:json.loads((directory/name/'summary.json').read_text())
       for name in ('tracking','cancel','map_loss','plan_change','timeout')}
summary={'passed':all(value['passed'] for value in cases.values()),'cases':cases}
(directory/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps({'directory':str(directory),'passed':summary['passed'],'cases':list(cases)}))
PY

#!/usr/bin/env bash
# Sequential, owned localhost simulation only; no physical device entry.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" != "--allow-send" ]]; then
    echo 'Usage: scripts/test_autonomy_navigation.sh --allow-send [absolute-new-run-directory]' >&2
    exit 2
fi
AUTONOMY_RUN_DIR="${2:-$PWD/artifacts/simulation/autonomy-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$AUTONOMY_RUN_DIR"
AUTONOMY_RUN_DIR="$(realpath "$AUTONOMY_RUN_DIR")"
python -m unittest discover -s tests -q 2>&1 | tee "$AUTONOMY_RUN_DIR/unit.log"
./scripts/with_ros2.sh python -m integrations.ros2.build_slam_boundary \
    --output-dir "$AUTONOMY_RUN_DIR/boundary" > "$AUTONOMY_RUN_DIR/native-build.json"
python - "$AUTONOMY_RUN_DIR" <<'PY'
import json
from pathlib import Path
import subprocess
import sys

directory=Path(sys.argv[1]);library=directory/'boundary/libvaf_slam_boundary.so'
cases=[]
for yaw in ('0.0','0.15'):
    cases.append(('map-'+yaw,'tests.simulation.map_reliability',['--yaw',yaw,'--boundary-library',str(library)]))
for case in ('tracking','planning_cancel','unreachable','replan','blocked','replan_cancel',
             'map_goal','business_inspect','business_cancel','business_loss'):
    flags=['--allow-send','--case',case]
    if case=='map_goal':flags+=['--room-yaw','0','--boundary-library',str(library)]
    cases.append(('front-'+case,'tests.simulation.goal_navigation',flags))
for case in ('tracking','cancel','map_loss'):
    cases.append(('compact-'+case,'tests.simulation.goal_navigation',
                  ['--allow-send','--case',case,'--navigation-model','compact_rover_front_axle_v1']))
results={}
for name,module,flags in cases:
    with (directory/(name+'.log')).open('w') as output:
        code=subprocess.run([sys.executable,'-m',module,*flags,'--run-dir',str(directory/name)],
                            stdout=output,stderr=subprocess.STDOUT).returncode
    summary=directory/name/'summary.json'
    results[name]=json.loads(summary.read_text()) if summary.exists() else {'passed':False,'error':'no summary'}
    passed=code==0 and results[name].get('passed') is True
    aggregate={'passed':passed and len(results)==len(cases),'expected_cases':len(cases),'cases':results}
    (directory/'summary.json').write_text(json.dumps(aggregate,indent=2)+'\n')
    print(json.dumps({'case':name,'passed':passed}),flush=True)
    if not passed:raise SystemExit(1)
PY

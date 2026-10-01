#!/usr/bin/env bash
set -euo pipefail

# A separately started localhost ArduCopter SITL must listen on TCP 5760.
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
profile="${1:-$repo_dir/runtime/sitl_arm.toml}"
sitl_version="${2:-unreported}"
log_file="$(mktemp)"
trap 'rm -f "$log_file"' EXIT

cd "$repo_dir"
python -m app.main run-sitl-arm --config "$profile" --allow-send --allow-arm \
  --sitl-version "$sitl_version" | tee "$log_file"
python - "$log_file" <<'PY'
import json
import sys

events = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
results = [event for event in events if event.get("event") == "effect_result"]
ids = list(dict.fromkeys(event["effect_id"] for event in results))
required = ["REQUESTED", "ACCEPTED", "TRANSMITTED", "ACKNOWLEDGED", "COMPLETED"]
assert len(ids) == 3, ids
for effect_id in ids:
    phases = [event["phase"] for event in results if event["effect_id"] == effect_id]
    assert phases == required, (effect_id, phases)
final = events[-1]["final"]
assert final["status"] == "SUCCEEDED", final
assert final["armed"] is False, final
assert final["disarm_cleanup"] == "CONFIRMED", final
assert len(final["effects"]) == 3, final
print("PASS: SITL mode, arm and disarm each completed after ACK and later state")
PY

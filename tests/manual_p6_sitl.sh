#!/usr/bin/env bash
set -euo pipefail

# Start a local ArduCopter SITL TCP 5760 endpoint separately before this check.
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
profile="${1:-$repo_dir/runtime/sitl.toml}"
sitl_version="${2:-unreported}"
log_file="$(mktemp)"
trap 'rm -f "$log_file"' EXIT

cd "$repo_dir"
python -m app.main run-sitl --config "$profile" --allow-send --sitl-version "$sitl_version" | tee "$log_file"
python - "$log_file" <<'PY'
import json
import sys

events = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
phases = [item["phase"] for item in events if item.get("event") == "effect_result"]
required = ["REQUESTED", "ACCEPTED", "TRANSMITTED", "ACKNOWLEDGED", "COMPLETED"]
assert phases == required, phases
final = events[-1]["final"]
assert final["status"] == "SUCCEEDED", final
assert final["vehicle_quality"] == "VALID", final
assert final["freshness"]["vehicle"] == "FRESH", final
assert final["snapshot_version"] > 1, final
assert len(final["effects"]) == 1, final
print("PASS: one disarmed SITL mode Effect completed after ACK and later state")
PY

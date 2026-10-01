"""Hardware disconnected status entry point for the new framework."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Vehicle Autonomy Framework")
    parser.add_argument("command", choices=("status", "run-sitl"))
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "runtime" / "sitl.toml"))
    parser.add_argument("--allow-send", action="store_true")
    parser.add_argument("--sitl-version", help="operator reported local SITL binary version for the run log")
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps({
            "framework": "v1", "vehicle_connection": "unwired",
            "mission_scheduler": "unwired", "send_commands": False,
        }, sort_keys=True))
        return 0
    from deployment.sitl_runtime import run_sitl
    from runtime.sitl import SitlProfile
    profile = SitlProfile.load(args.config)
    result = run_sitl(profile, allow_send=args.allow_send, sitl_version=args.sitl_version,
                      event_sink=lambda event: print(json.dumps(event, sort_keys=True), flush=True))
    print(json.dumps({"final": result}, sort_keys=True))
    return 0 if result["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

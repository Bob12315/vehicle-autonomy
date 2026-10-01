"""Hardware disconnected status entry point for the new framework."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Vehicle Autonomy Framework")
    parser.add_argument("command", choices=("status", "run-sitl", "run-sitl-arm"))
    parser.add_argument("--config")
    parser.add_argument("--allow-send", action="store_true")
    parser.add_argument("--allow-arm", action="store_true", help="permit a disarmed localhost SITL arm cycle")
    parser.add_argument("--sitl-version", help="operator reported local SITL binary version for the run log")
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps({
            "framework": "v1", "vehicle_connection": "unwired",
            "mission_scheduler": "unwired", "send_commands": False,
        }, sort_keys=True))
        return 0
    if args.allow_arm and args.command != "run-sitl-arm":
        parser.error("--allow-arm applies only to run-sitl-arm")
    if args.command == "run-sitl-arm" and not (args.allow_send and args.allow_arm):
        parser.error("run-sitl-arm requires both --allow-send and --allow-arm")
    from deployment.sitl_runtime import run_sitl
    from runtime.sitl import SitlProfile
    config = args.config or str(Path(__file__).resolve().parents[1] / "runtime" /
                                ("sitl_arm.toml" if args.command == "run-sitl-arm" else "sitl.toml"))
    profile = SitlProfile.load(config)
    result = run_sitl(profile, allow_send=args.allow_send, sitl_version=args.sitl_version,
                      arm_then_disarm=args.command == "run-sitl-arm", allow_arm=args.allow_arm,
                      event_sink=lambda event: print(json.dumps(event, sort_keys=True), flush=True))
    print(json.dumps({"final": result}, sort_keys=True))
    return 0 if result["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

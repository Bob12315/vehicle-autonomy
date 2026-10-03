"""Hardware disconnected status entry point for the new framework."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Vehicle Autonomy Framework")
    parser.add_argument("command", choices=("status", "run-sitl", "run-sitl-arm", "run", "ctl"))
    parser.add_argument("operation", nargs="?", choices=("status", "start", "cancel", "shutdown"))
    parser.add_argument("--profile", choices=("copter_sim", "rover_sim"))
    parser.add_argument("--control-socket")
    parser.add_argument("--mission")
    parser.add_argument("--request-id")
    parser.add_argument("--config")
    parser.add_argument("--sim-sensor-config")
    parser.add_argument("--recorded-vision-config")
    parser.add_argument("--sim-payload",action="store_true")
    parser.add_argument("--allow-send", action="store_true")
    parser.add_argument("--allow-arm", action="store_true", help="permit a disarmed localhost SITL arm cycle")
    parser.add_argument("--sitl-version", help="operator reported local SITL binary version for the run log")
    args = parser.parse_intermixed_args()
    if args.command in ("run", "ctl"):
        if not args.profile or args.allow_arm:
            parser.error("run/ctl requires --profile and does not accept --allow-arm")
        from app.control import request, run_application, socket_path
        from runtime.application_profile import load_profile
        try:
            path = args.control_socket or socket_path(args.profile)
            if args.command == "run":
                if args.operation or args.mission or args.request_id:
                    parser.error("run takes no control operation")
                return run_application(load_profile(args.profile, args.config), profile_name=args.profile,
                                       allow_send=args.allow_send, path=path, sensor_config=args.sim_sensor_config, vision_config=args.recorded_vision_config, sim_payload=args.sim_payload)
            if not args.operation or args.allow_send or args.config or args.sim_sensor_config or args.recorded_vision_config or args.sim_payload:
                parser.error("ctl requires an operation and cannot configure SEND or vehicle")
            if (args.operation == "start") != (args.mission is not None):
                parser.error("only start requires --mission")
            response = request(path, args.operation, {"mission": args.mission} if args.mission else {},
                               request_id=args.request_id)
            print(json.dumps(response, sort_keys=True))
            return 0 if response["ok"] else 1
        except (OSError, ValueError, RuntimeError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
            return 1
    if args.sim_sensor_config or args.recorded_vision_config or args.sim_payload:
        parser.error("simulation sensor applies only to explicit run")
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

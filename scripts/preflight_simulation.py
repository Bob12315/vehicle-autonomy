"""Read-only host checks before starting an owned simulation run."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ARDUPILOT = Path("/home/level6/ardupilot")
GAZEBO_PLUGIN = Path("/home/level6/gz_ws/src/ardupilot_gazebo")


def command_output(*args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return result.returncode, (result.stdout + result.stderr).strip()


def free_port(port: int, kind: int) -> bool:
    with socket.socket(socket.AF_INET, kind) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase0", action="store_true", help="allow the still missing target Rover model")
    args = parser.parse_args()
    checks: dict[str, object] = {}
    for name in ("gz", "ss", "python"):
        checks[f"tool_{name}"] = shutil.which(name) is not None
    for name in ("pymavlink", "pyserial"):
        try:
            checks[f"python_{name}"] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            checks[f"python_{name}"] = None
    files = {
        "copter_binary": ARDUPILOT / "build/sitl/bin/arducopter",
        "rover_binary": ARDUPILOT / "build/sitl/bin/ardurover",
        "gazebo_plugin": GAZEBO_PLUGIN / "build/libArduPilotPlugin.so",
        "copter_world": GAZEBO_PLUGIN / "worlds/iris_runway.sdf",
        "rover_world": ROOT / "simulation/worlds/rover_runway.sdf",
        "copter_telemetry_params": ROOT / "simulation/params/copter_telemetry.parm",
    }
    for name, path in files.items():
        checks[name] = path.is_file()
    code, version = command_output("gz", "sim", "--version")
    checks["gazebo_version"] = version if code == 0 else None
    code, deps = command_output("ldd", str(files["gazebo_plugin"])) if files["gazebo_plugin"].is_file() else (1, "missing plugin")
    checks["plugin_dependencies"] = code == 0 and "not found" not in deps
    for port in (5760, 5762):
        checks[f"tcp_{port}_free"] = free_port(port, socket.SOCK_STREAM)
    checks["udp_9002_free"] = free_port(9002, socket.SOCK_DGRAM)
    required = {"tool_gz", "tool_ss", "tool_python", "python_pymavlink", "python_pyserial",
                "copter_binary", "rover_binary", "gazebo_plugin", "copter_world",
                "copter_telemetry_params", "gazebo_version", "plugin_dependencies",
                "tcp_5760_free", "tcp_5762_free", "udp_9002_free"}
    if not args.phase0:
        required.add("rover_world")
    passed = all(bool(checks[name]) for name in required)
    print(json.dumps({"passed": passed, "phase0": args.phase0, "checks": checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

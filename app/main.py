"""Hardware disconnected status entry point for the new framework."""

from __future__ import annotations

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser(description="Vehicle Autonomy Framework")
    parser.add_argument("command", choices=("status",))
    parser.parse_args()
    print(json.dumps({
        "framework": "v1",
        "vehicle_connection": "unwired",
        "mission_scheduler": "unwired",
        "send_commands": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

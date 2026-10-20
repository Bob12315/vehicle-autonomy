"""Explicit hardware-read-only daemon; no arm/send/control flags exist."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import time

from app.control import ControlServer, socket_path
from application.runtime_service import RuntimeService
from deployment.hardware_profile import load_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/deployment/hardware-readonly.json')
    parser.add_argument('--control-socket')
    parser.add_argument('--log-dir', default='artifacts/hardware-ready/onboard')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    profile = load_profile(args.config)
    if args.check:
        print(json.dumps({'valid': True, 'mode': profile['mode'], 'system_send': False, 'action_send': False}))
        return 0
    if profile['mode'] != 'hardware_readonly':
        parser.error('Simulation uses the existing app.main run --profile rover_sim entry')
    from deployment.hardware_runtime import HardwareReadOnlyRuntime
    runtime = HardwareReadOnlyRuntime(profile, args.log_dir)
    server = None
    previous = {}
    try:
        server = ControlServer(args.control_socket or socket_path('hardware_readonly'), RuntimeService(runtime))
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda *_: runtime.request_shutdown())
        while not runtime.stopping:
            started = time.monotonic()
            runtime.cycle()
            server.poll()
            time.sleep(max(0, profile['period_s'] - (time.monotonic() - started)))
        until = time.monotonic() + .2
        while server.clients and time.monotonic() < until:
            server.poll()
            time.sleep(.005)
    finally:
        if server:
            server.close()
        runtime.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

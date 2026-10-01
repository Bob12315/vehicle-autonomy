"""Owned process used to verify SIGTERM motion cleanup and restart defaults."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import signal
import time

from contracts.core.geometry import Twist3, Vector3
from contracts.effects.vehicle import TwistTargetEffect
from deployment.simulation_runtime import SimulationRuntime
from runtime.simulation_profile import SimulationProfile
from tests.simulation.launch import ROOT
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator
from vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', required=True, choices=('copter', 'rover'))
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--allow-send', action='store_true')
    args = parser.parse_args()
    stopping = False
    def stop(signum, frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    profile = replace(SimulationProfile.load(ROOT / f'simulation/profiles/{args.kind}.toml'), port=args.port)
    translator = (ArduRoverCommandTranslator if args.kind == 'rover' else ArduPilotCommandTranslator)(mode_ids=profile.mode_ids)
    events = []
    runtime = SimulationRuntime(profile, translator=translator, event_sink=events.append)
    report = {'passed': False, 'initial_send': runtime.authority.system_send,
              'initial_lease': runtime.authority.lease, 'kind': args.kind}
    def save():
        args.report.write_text(json.dumps({**report, 'events': events}, indent=2))
    try:
        runtime.connect()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not stopping:
            start = time.monotonic()
            result = runtime.cycle()
            if result.fault:
                raise RuntimeError(result.fault)
            if result.vehicle_fresh:
                break
            time.sleep(max(0, .1 - (time.monotonic() - start)))
        else:
            raise TimeoutError('worker fresh state unavailable')
        runtime.begin_run(allow_send=args.allow_send)
        report['ready'] = True
        report['session_id'] = runtime.session_id
        save()
        if args.allow_send:
            deadline = time.monotonic() + 20
            refresh = 0
            count = 0
            while not stopping and time.monotonic() < deadline:
                start = time.monotonic()
                if start >= refresh:
                    count += 1
                    admission = runtime.submit_effect(TwistTargetEffect('base_link',
                        Twist3(Vector3(.3, 0, 0), Vector3(0, 0, 0)), 'signal-motion'),
                        effect_id=f'signal-motion-{count}')
                    if admission.reason:
                        raise RuntimeError(admission.reason)
                    refresh = start + .3
                result = runtime.cycle()
                if result.fault:
                    raise RuntimeError(result.fault)
                time.sleep(max(0, .1 - (time.monotonic() - start)))
            if not stopping:
                raise TimeoutError('expected SIGTERM not received')
            report['signal_received'] = True
        else:
            for _ in range(3):
                start = time.monotonic()
                result = runtime.cycle()
                if result.fault:
                    raise RuntimeError(result.fault)
                time.sleep(max(0, .1 - (time.monotonic() - start)))
        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        report['stops'] = runtime.shutdown()
        report['final_send'] = runtime.authority.system_send
        report['final_lease'] = runtime.authority.lease
        if args.allow_send and report['stops'] != {'signal-motion': 'CONFIRMED'}:
            report['passed'] = False
            report['error'] = 'SIGTERM motion stop not confirmed'
        save()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Unified, failure-preserving P26 regression with explicit simulation SEND."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sys

from tests.simulation.harness import StageRunner
from tests.simulation.launch import ROOT, output


def cases(library):
    result = [
        ('rover_application', 'tests.simulation.application_process', ['--kind', 'rover']),
        ('copter_application', 'tests.simulation.application_process', ['--kind', 'copter']),
        ('rover_base', 'tests.simulation.rover_protocol', ['--allow-send', '--full']),
        ('copter_base', 'tests.simulation.copter_scenario', ['--allow-send', '--full']),
        ('rover_faults', 'tests.simulation.fault_scenario', ['--kind', 'rover', '--allow-send']),
        ('copter_faults', 'tests.simulation.fault_scenario', ['--kind', 'copter', '--allow-send']),
        ('rover_repeat_route', 'tests.simulation.autonomy_process',
         ['--kind', 'rover', '--allow-send', '--mission', 'basic_route', '--repeats', '2']),
        ('rover_endurance', 'tests.simulation.endurance', ['--allow-send']),
    ]
    for yaw in ('0.0', '0.15'):
        result.append(('map_' + yaw, 'tests.simulation.map_reliability',
                       ['--yaw', yaw, '--boundary-library', str(library)]))
    for case in ('tracking', 'planning_cancel', 'unreachable', 'replan', 'blocked',
                 'replan_cancel', 'map_goal', 'business_inspect', 'business_cancel', 'business_loss'):
        flags = ['--allow-send', '--case', case]
        if case == 'map_goal':
            flags += ['--room-yaw', '0', '--boundary-library', str(library)]
        result.append(('front_' + case, 'tests.simulation.goal_navigation', flags))
    for case in ('tracking', 'cancel', 'map_loss'):
        result.append(('compact_' + case, 'tests.simulation.goal_navigation',
            ['--allow-send', '--case', case, '--navigation-model', 'compact_rover_front_axle_v1']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-send', action='store_true')
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    if not args.allow_send:
        parser.error('explicit localhost simulation SEND required')
    directory = args.run_dir.resolve()
    if len(os.fsencode(str(directory / '00/app.sock'))) >= 108:
        parser.error('use a shorter run directory for Unix sockets')
    directory.mkdir(parents=True, exist_ok=False)
    runner = StageRunner(directory, total_timeout=7200)
    library = directory / 'boundary/libvaf_slam_boundary.so'
    matrix = cases(library)
    report = {'passed': False, 'started_at': datetime.now(timezone.utc).isoformat(),
              'source_commit': output(['git', 'rev-parse', 'HEAD']),
              'source_dirty': bool(output(['git', 'status', '--porcelain'])),
              'expected_cases': len(matrix), 'core_skipped': 0, 'cases': []}
    inputs = {}
    for package in ('contracts', 'core', 'deployment', 'runtime', 'application', 'applications',
                    'actions', 'app', 'vehicles', 'protocols', 'simulation', 'tests', 'scripts'):
        for path in sorted((ROOT / package).rglob('*')):
            if path.is_file() and '__pycache__' not in str(path) and path.suffix in (
                    '.py', '.toml', '.json', '.sdf', '.sh', '.parm'):
                inputs[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    report['input_hashes'] = inputs

    def save():
        (directory / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')

    def interrupted(signum, _):
        raise InterruptedError(f'P26 signal {signum}')

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    try:
        preflight = runner.run_stage('preflight', [sys.executable, 'scripts/preflight_simulation.py', '--isolated'])
        unit = runner.run_stage('unit', [sys.executable, '-m', 'tests.simulation.harness',
                                      '--unit-report', str(directory / 'unit.json')], timeout=120)
        native = runner.run_stage('native', ['./scripts/with_ros2.sh', sys.executable,
            '-m', 'integrations.ros2.build_slam_boundary', '--output-dir', str(library.parent)], timeout=120)
        report['preflight'] = preflight['passed']
        report['unit'] = json.loads((directory / 'unit.json').read_text()) if (directory / 'unit.json').exists() else {}
        report['native'] = native['passed']
        save()
        for index, (name, module, flags) in enumerate(matrix):
            stage_dir = directory / f'{index:02d}'
            if not preflight['passed'] or (index >= 8 and not native['passed']):
                report['cases'].append({'name': name, 'status': 'BLOCKED', 'reason': 'dependency preflight'})
                save()
                continue
            print(f'[{name}] starting', flush=True)
            stage = runner.run_stage(name, [sys.executable, '-m', module, *flags,
                '--run-dir', str(stage_dir)], timeout=1000 if name == 'rover_endurance' else 420,
                stage_dir=stage_dir)
            summary_path, manifest_path = stage_dir / 'summary.json', stage_dir / 'manifest.json'
            summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
            passed = bool(stage['passed'] and summary.get('passed') and manifest.get('ports_released')
                          and manifest.get('remaining_process_groups') == []
                          and not any(key.endswith('_error') for key in summary))
            report['cases'].append({'name': name, 'status': 'PASS' if passed else 'FAIL',
                'summary': str(summary_path), 'manifest': str(manifest_path),
                'error': summary.get('error'),
                'summary_sha256': hashlib.sha256(summary_path.read_bytes()).hexdigest() if summary_path.exists() else None})
            save()
            print(f'[{name}] {report["cases"][-1]["status"]}', flush=True)
        report['passed'] = (unit['passed'] and report['unit'].get('passed') is True
                            and native['passed'] and len(report['cases']) == len(matrix)
                            and all(case['status'] == 'PASS' for case in report['cases']))
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if runner.current is not None:
            runner.stop(runner.current)
        report['ended_at'] = datetime.now(timezone.utc).isoformat()
        report['not_run'] = len(matrix) - len(report['cases'])
        save()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""One-command, bounded, owned-process dual-vehicle acceptance suite."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from uuid import uuid4
from tests.simulation.launch import ARDUPILOT, PLUGIN, ROOT, output


def stamp():
    return datetime.now(timezone.utc).isoformat()


class StageRunner:
    def __init__(self, run_dir: Path, *, total_timeout=2400, env=None):
        self.run_dir = run_dir
        self.deadline = time.monotonic() + total_timeout
        self.env = dict(os.environ if env is None else env)
        self.records = []
        self.current = None

    def stop(self, process):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)

    def cleanup_manifest(self, stage_dir):
        """Fallback only for still-live groups matching an owned launch record."""
        manifest = stage_dir / 'manifest.json'
        if not manifest.exists():
            return
        for record in reversed(json.loads(manifest.read_text()).get('processes', [])):
            stat = Path(f"/proc/{record['pid']}/stat")
            if not stat.exists():
                continue
            try:
                ticks = stat.read_text().rsplit(')', 1)[1].split()[19]
                if ticks != record.get('start_ticks') or os.getpgid(record['pid']) != record['pgid']:
                    continue
                os.killpg(record['pgid'], signal.SIGTERM)
            except (ProcessLookupError, FileNotFoundError):
                pass

    def run_stage(self, name, command, *, timeout=300, cwd=ROOT, stage_dir=None):
        record = {'name': name, 'command': command, 'started_at': stamp(), 'timeout_s': timeout,
                  'log': str(self.run_dir / f'{name}.log'), 'passed': False}
        self.records.append(record)
        process = None
        try:
            with Path(record['log']).open('w') as logfile:
                process = subprocess.Popen(command, cwd=cwd, env=self.env, stdout=logfile,
                    stderr=subprocess.STDOUT, start_new_session=True)
                self.current = process
                record['pid'] = record['pgid'] = process.pid
                deadline = min(self.deadline, time.monotonic() + timeout)
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        record['error'] = 'timeout'
                        break
                    time.sleep(.1)
                if 'error' not in record:
                    record['passed'] = process.returncode == 0
                    if not record['passed']:
                        record['error'] = 'nonzero_exit'
        except BaseException as exc:
            record['error'] = f'{type(exc).__name__}: {exc}'
            if isinstance(exc, (KeyboardInterrupt, InterruptedError)):
                raise
        finally:
            if process is not None:
                self.stop(process)
                record['exit_code'] = process.returncode
            self.current = None
            if stage_dir is not None:
                self.cleanup_manifest(stage_dir)
            record['ended_at'] = stamp()
            (self.run_dir / 'stages.json').write_text(json.dumps(self.records, indent=2))
        return record


class JsonUnitResult(unittest.TextTestResult):
    pass


def unit_suite(report_path):
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=1, resultclass=JsonUnitResult).run(suite)
    report = {'passed': result.wasSuccessful() and not result.skipped, 'tests': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped)}
    report_path.write_text(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--build-dir', type=Path)
    parser.add_argument('--timeout', type=float, default=2400)
    parser.add_argument('--inject-failure', action='store_true', help='verify nonzero result before vehicles launch')
    parser.add_argument('--unit-report', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.unit_report:
        return unit_suite(args.unit_report)
    run_dir = (args.run_dir or ROOT / 'artifacts/simulation' / f'suite-{uuid4().hex[:8]}').resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    build_dir = args.build_dir.resolve() if args.build_dir else run_dir / 'build'
    binary_dir = build_dir / 'ardupilot/sitl/bin'
    plugin_dir = build_dir / 'gazebo-plugin'
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT)
    env['VAF_SIMULATION_SITL_BIN_DIR'] = str(binary_dir)
    env['VAF_SIMULATION_PLUGIN_DIR'] = str(plugin_dir)
    runner = StageRunner(run_dir, total_timeout=args.timeout, env=env)
    summary = {'passed': False, 'run_dir': str(run_dir),
               'started_at': stamp(), 'core_skipped': 0, 'expected_scenarios': 9,
               'scenarios': [], 'framework_sha': output(['git', 'rev-parse', 'HEAD']),
               'ardupilot_sha': output(['git', 'rev-parse', 'HEAD'], ARDUPILOT),
               'plugin_sha': output(['git', 'rev-parse', 'HEAD'], PLUGIN), 'build_dir': str(build_dir),
               'initially_empty_build': not build_dir.exists() or not any(build_dir.iterdir())}
    def interrupted(signum, frame):
        raise InterruptedError(f'harness signal {signum}')
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    try:
        # Configure/build in our own output directory; no external build is deleted.
        commands = [
            ('configure_sitl', [str(ARDUPILOT / 'waf'), 'configure', '--board', 'sitl', '--out', str(build_dir / 'ardupilot')], ARDUPILOT, 120),
            ('build_sitl', [str(ARDUPILOT / 'waf'), 'copter', 'rover', '--out', str(build_dir / 'ardupilot'), '-j8'], ARDUPILOT, 1200),
            ('configure_plugin', ['cmake', '-S', str(PLUGIN), '-B', str(plugin_dir)], ROOT, 120),
            ('build_plugin', ['cmake', '--build', str(plugin_dir), '-j8'], ROOT, 300),
            ('preflight', [sys.executable, str(ROOT / 'scripts/preflight_simulation.py'), '--isolated'], ROOT, 30),
            ('unit', [sys.executable, '-m', 'tests.simulation.harness', '--unit-report', str(run_dir / 'unit.json')], ROOT, 60),
        ]
        if args.inject_failure:
            commands = [('injected_failure', [sys.executable, '-c', 'raise SystemExit(7)'], ROOT, 10)]
        for name, command, cwd, timeout in commands:
            print(f'[{name}] starting', flush=True)
            if not runner.run_stage(name, command, cwd=cwd, timeout=timeout)['passed']:
                raise RuntimeError(f'{name} failed; see {run_dir / (name + ".log")}')
            print(f'[{name}] PASS', flush=True)
        if args.inject_failure:
            raise AssertionError('failure injection unexpectedly succeeded')
        scenarios = [
            ('copter_application', 'tests.simulation.application_process', ['--kind', 'copter']),
            ('rover_application', 'tests.simulation.application_process', ['--kind', 'rover']),
            ('copter_environment', 'tests.simulation.environment_probe', ['--kind', 'copter', '--allow-send']),
            ('rover_environment', 'tests.simulation.environment_probe', ['--kind', 'rover', '--allow-send']),
            ('copter_full', 'tests.simulation.copter_scenario', ['--allow-send', '--full']),
            ('copter_land', 'tests.simulation.copter_scenario', ['--allow-send']),
            ('rover_full', 'tests.simulation.rover_protocol', ['--allow-send', '--full']),
            ('copter_faults', 'tests.simulation.fault_scenario', ['--kind', 'copter', '--allow-send']),
            ('rover_faults', 'tests.simulation.fault_scenario', ['--kind', 'rover', '--allow-send']),
        ]
        for name, module, flags in scenarios:
            stage_dir = run_dir / name
            print(f'[{name}] starting', flush=True)
            record = runner.run_stage(name, [sys.executable, '-m', module, *flags, '--run-dir', str(stage_dir)],
                                      timeout=360, stage_dir=stage_dir)
            report = json.loads((stage_dir / 'summary.json').read_text()) if (stage_dir / 'summary.json').exists() else {}
            manifest = json.loads((stage_dir / 'manifest.json').read_text()) if (stage_dir / 'manifest.json').exists() else {}
            valid = (record['passed'] and report.get('passed') and manifest.get('ports_released')
                     and manifest.get('remaining_process_groups') == []
                     and not any(key.endswith('_error') for key in report))
            summary['scenarios'].append({'name': name, 'passed': bool(valid), 'report': str(stage_dir / 'summary.json'),
                                         'manifest': str(stage_dir / 'manifest.json')})
            if not valid:
                raise RuntimeError(f'{name} acceptance or cleanup failed')
            print(f'[{name}] PASS', flush=True)
        summary['unit'] = json.loads((run_dir / 'unit.json').read_text())
        summary['passed'] = len(summary['scenarios']) == summary['expected_scenarios'] and summary['unit']['passed']
    except Exception as exc:
        summary['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if runner.current is not None:
            runner.stop(runner.current)
        summary['stages'] = runner.records
        summary['failed_stages'] = sum(not record['passed'] for record in runner.records)
        summary['failed_scenarios'] = sum(not record['passed'] for record in summary['scenarios'])
        summary['not_run_scenarios'] = summary['expected_scenarios'] - len(summary['scenarios'])
        summary['ended_at'] = stamp()
        (run_dir / 'summary.json').write_text(json.dumps(summary, indent=2))
        print(json.dumps({key: summary[key] for key in ('passed', 'run_dir', 'failed_stages', 'failed_scenarios', 'not_run_scenarios', 'core_skipped')}), flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

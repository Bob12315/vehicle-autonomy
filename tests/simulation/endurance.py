"""Bounded real localhost SITL endurance; never opens a physical device."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from app.control import request
from tests.simulation.launch import OwnedSimulation, install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle


def resources(pid):
    root = Path('/proc') / str(pid)
    fields = root.joinpath('stat').read_text().rsplit(')', 1)[1].split()
    status = dict(line.split(':', 1) for line in root.joinpath('status').read_text().splitlines())
    return {'rss_bytes': int(status['VmRSS'].split()[0]) * 1024,
            'fds': len(list(root.joinpath('fd').iterdir())),
            'threads': int(status['Threads']),
            'cpu_seconds': (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK')}


def run(directory, duration_s=600, repeats=100):
    directory.mkdir(parents=True, exist_ok=False)
    owned = OwnedSimulation(directory, 'rover')
    report = {'passed': False, 'duration_required_s': duration_s, 'missions_required': repeats,
              'tasks': [], 'samples': [], 'scope': 'localhost disarmed repeated Missions'}
    endpoint = directory / 'app.sock'
    try:
        owned.start()
        oracle = GazeboTruthOracle(owned.world, owned.model)
        config = directory / 'profile.toml'
        config.write_text(Path('simulation/profiles/rover.toml').read_text().replace(
            'port = 5760', f'port = {owned.port}'))
        app = owned.start_process('endurance-app', [sys.executable, '-m', 'app.main', 'run',
            '--profile', 'rover_sim', '--config', str(config), '--control-socket', str(endpoint), '--allow-send'])

        def state():
            owned.assert_alive()
            value = request(endpoint, 'status')
            if not value['ok']:
                raise AssertionError(value)
            return value['result']

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if endpoint.exists() and state()['state'] == 'READY':
                break
            time.sleep(.2)
        else:
            raise TimeoutError('SITL application readiness')
        oracle.wait_new(after_host_ns=time.monotonic_ns(), timeout_s=3)
        started = time.monotonic()
        initial = resources(app.pid)
        baseline = None
        identities = set()
        effects = set()
        next_task = started
        while time.monotonic() - started < duration_s or len(identities) < repeats:
            if time.monotonic() - started > duration_s + 180:
                raise TimeoutError('endurance completion deadline')
            current = state()
            if current['state'] != 'READY' or current['vehicle']['armed']:
                raise AssertionError('endurance lost fresh disarmed READY')
            if time.monotonic() >= next_task and len(identities) < repeats:
                index = len(identities)
                rid = f'endurance-{index}'
                first = request(endpoint, 'start', {'mission': 'disarmed_mode'}, request_id=rid)
                duplicate = request(endpoint, 'start', {'mission': 'disarmed_mode'}, request_id=rid)
                assert first['ok'] and duplicate == first, (first, duplicate)
                task_id = first['result']['task_id']
                assert task_id not in identities
                until = time.monotonic() + 20
                while time.monotonic() < until:
                    current = state()
                    if current['task']['status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
                        break
                    time.sleep(.1)
                task = current['task']
                assert task['status'] == 'SUCCEEDED' and task['task_id'] == task_id, task
                assert not current['system_send'] and not current['action_send']
                assert task['effects'] and all(v['phase'] == 'COMPLETED' for v in task['effects'].values())
                assert not effects.intersection(task['effects'])
                effects.update(task['effects'])
                identities.add(task_id)
                report['tasks'].append({'id': task_id, 'effects': list(task['effects']),
                                        'elapsed_s': time.monotonic() - started})
                if len(identities) == 10:
                    baseline = resources(app.pid)
                next_task = started + len(identities) * duration_s / repeats
            sample = resources(app.pid)
            sample['elapsed_s'] = time.monotonic() - started
            sample['log_bytes'] = (directory / 'endurance-app.log').stat().st_size
            sample['world_age_ns'] = current['world_age_ns']
            truth = oracle.latest()
            assert truth is not None and time.monotonic_ns() - truth.host_received_ns < 2_000_000_000
            assert current['world_age_ns'] < owned.profile.safety.max_snapshot_age_ns
            assert current['localization'] is not None
            assert sample['log_bytes'] <= 25 * 1024 * 1024
            if baseline:
                assert sample['rss_bytes'] - baseline['rss_bytes'] <= 32 * 1024 * 1024, sample
                assert sample['fds'] - baseline['fds'] <= 4, sample
                assert sample['threads'] - baseline['threads'] <= 2, sample
            report['samples'].append(sample)
            time.sleep(.5)
        elapsed = time.monotonic() - started
        cpu_fraction = (resources(app.pid)['cpu_seconds'] - initial['cpu_seconds']) / elapsed
        assert cpu_fraction <= .70, cpu_fraction
        report.update(elapsed_s=elapsed, cpu_fraction_one_core=cpu_fraction,
                      distinct_effects=len(effects), warmup_resources=baseline)
        assert request(endpoint, 'shutdown')['ok']
        assert app.wait(timeout=8) == 0 and not endpoint.exists()
        owned.stop_process(app)
        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        try:
            owned.close()
        except Exception as exc:
            report.update(passed=False, cleanup_error=str(exc))
        (directory / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-send', action='store_true')
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    if not args.allow_send:
        parser.error('explicit localhost simulation SEND required')
    install_signal_cleanup()
    result = run(args.run_dir.resolve())
    print(json.dumps({k: v for k, v in result.items() if k not in ('tasks', 'samples')}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

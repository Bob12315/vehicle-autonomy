"""Recorded visual input cancellation/corruption through the public App process."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from app.control import request
from tests.simulation.launch import ROOT, OwnedSimulation, install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle


def run(directory, recording):
    directory.mkdir(parents=True, exist_ok=False)
    owned = OwnedSimulation(directory, 'copter')
    endpoint = directory / 'app.sock'
    report = {'passed': False, 'checks': {}, 'source': 'recorded_virtual_camera'}
    evidence = (directory / 'status.jsonl').open('w')
    try:
        # Copy only public, checksum-pinned fixture assets into this owned run.
        document = json.loads(recording.read_text())
        image = directory / 'recorded-image.jpg'
        first = recording.parent / document['frames'][0]['path']
        image.write_bytes(first.read_bytes())
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        assert all(frame['sha256'] == digest for frame in document['frames'])
        for frame in document['frames']:
            frame['path'] = image.name
        document['model'] = str((recording.parent / document['model']).resolve())
        document['calibration'] = str((recording.parent / document['calibration']).resolve())
        document['source'] += '; owned input-corruption/cancellation acceptance'
        local_recording = directory / 'recording.json'
        local_recording.write_text(json.dumps(document, indent=2))
        owned.start()
        oracle = GazeboTruthOracle(owned.world, owned.model)
        config = directory / 'profile.toml'
        config.write_text((ROOT / 'simulation/profiles/copter.toml').read_text().replace(
            'port = 5760', f'port = {owned.port}'))
        app = owned.start_process('application', [sys.executable, '-m', 'app.main', 'run',
            '--profile', 'copter_sim', '--config', str(config), '--control-socket', str(endpoint),
            '--allow-send', '--recorded-vision-config', str(local_recording), '--sim-payload'])

        def status():
            owned.assert_alive()
            state = request(endpoint, 'status')['result']
            truth = oracle.latest()
            if state['task'] is not None and (truth is None or
                    time.monotonic_ns() - truth.host_received_ns > 1_000_000_000):
                raise RuntimeError('independent physical oracle stale')
            evidence.write(json.dumps({'host_ns': time.monotonic_ns(), 'status': state,
                'truth': None if truth is None else [truth.x_m, truth.y_m, truth.z_m],
                'speed': oracle.recent_speed_mps()}) + '\n')
            evidence.flush()
            return state

        def wait(predicate, timeout):
            until = time.monotonic() + timeout
            while time.monotonic() < until:
                if endpoint.exists():
                    state = status()
                    if predicate(state):
                        return state
                time.sleep(.1)
            raise TimeoutError('public state deadline')

        def ctl(operation, *flags):
            result = subprocess.run([sys.executable, '-m', 'app.main', 'ctl', '--profile',
                'copter_sim', '--control-socket', str(endpoint), operation, *flags],
                capture_output=True, text=True, timeout=4)
            response = json.loads(result.stdout)
            if result.returncode or not response['ok']:
                raise RuntimeError(response)
            return response['result']

        def approaching(state):
            task = state['task']
            return task['step'] == 'approach_release' and any(
                value and value['phase'] == 'TRANSMITTED' and
                task['requests'][key]['effect_type'] == 'PoseTargetEffect' and
                ':approach_release:' in task['requests'][key]['action_id']
                for key, value in task['effects'].items())

        def stopped(state):
            task = state['task']
            assert not state['system_send'] and not state['action_send']
            assert not state['payload']['released']
            speed = oracle.recent_speed_mps()
            assert speed is not None and speed <= .15, speed
            assert any(value and value['phase'] == 'COMPLETED' and
                task['requests'][key]['effect_type'] == 'StopMotionEffect' and
                ':approach_release:' in task['requests'][key]['action_id']
                for key, value in task['effects'].items())

        wait(lambda s: s['state'] == 'READY' and s['environment']['origin_verified'] and
            s['motion_warmup_remaining_ns'] == 0 and
            any(o['producer'].startswith('vision.recorded:') for o in s['objects']), 75)
        ctl('start', '--mission', 'cuadc_demo')
        wait(approaching, 70)
        ctl('cancel')
        cancelled = wait(lambda s: s['task']['status'] == 'CANCELLED', 10)
        stopped(cancelled)
        report['checks']['visual_cancel_confirmed_no_release'] = True
        ctl('start', '--mission', 'safe_recovery')
        wait(lambda s: s['task']['status'] == 'SUCCEEDED', 40)
        ctl('start', '--mission', 'cuadc_demo')
        wait(approaching, 70)
        # Atomic replacement changes only a run-owned file, never source/public assets.
        corrupt = directory / 'corrupt-image.jpg'
        corrupt.write_bytes(b'deliberately corrupted recorded camera input')
        corrupt.replace(image)
        failed = wait(lambda s: s['task']['status'] == 'FAILED', 10)
        assert failed['task']['error'] == 'target_lost_or_expired', failed['task']['error']
        assert 'recording image hash mismatch' in failed['sensor']['error']
        assert not any(o['producer'].startswith('vision.recorded:') for o in failed['objects'])
        stopped(failed)
        report['checks']['corrupt_visual_input_expired_stopped_no_release'] = True
        ctl('start', '--mission', 'safe_recovery')
        final = wait(lambda s: s['task']['status'] == 'SUCCEEDED', 40)
        assert not final['vehicle']['armed']
        ctl('shutdown')
        assert app.wait(timeout=8) == 0 and not endpoint.exists()
        owned.stop_process(app)
        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        try:
            owned.close()
        except Exception as exc:
            report['cleanup_error'] = str(exc)
            report['passed'] = False
        evidence.close()
        (directory / 'summary.json').write_text(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--recording', type=Path, default=ROOT / 'artifacts/simulation/vision-assets/recording.json')
    parser.add_argument('--allow-send', action='store_true')
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    if not args.allow_send:
        parser.error('--allow-send required for owned localhost simulation')
    install_signal_cleanup()
    result = run(args.run_dir or ROOT / 'artifacts/simulation' / f'vision-faults-{uuid4().hex[:8]}', args.recording)
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Real QGC-wire launch checks: receive telemetry and request parameters only.

No arming, mode changes, parameter writes or motion commands. Uses fresh
non-QGC UDP ports and stops only this test's launcher/process groups.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

from pymavlink import mavutil


ROOT = Path(__file__).resolve().parents[2]


def run(kind, directory, *, gui=False):
    port = {'rover': 14661, 'copter': 14662, 'plane': 14663}[kind]
    system = {'rover': 1, 'copter': 2, 'plane': 3}[kind]
    vehicle_type = {'rover': 10, 'copter': 2, 'plane': 1}[kind]
    # No reuse flags: a running GCS/test must never silently share this port.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(('127.0.0.1', port))
    gcs = mavutil.mavlink_connection(f'udpin:127.0.0.1:{port}', source_system=255)
    result = dict(kind=kind, gui=gui, passed=False, requested_parameters={}, armed=False)
    log_path = directory.parent / (directory.name + '-launcher.log')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [str(ROOT / f'scripts/start_{kind}_sim.sh'), '--qgc-port', str(port),
               '--run-dir', str(directory)]
    if not gui:
        command.append('--headless')
    with log_path.open('w') as log:
        launcher = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                    cwd='/tmp', start_new_session=True)
        try:
            until = time.monotonic() + 75
            seen = set()
            pending = ['MAV_SYSID'] + (['SERVO3_FUNCTION', 'SERVO6_FUNCTION'] if kind == 'plane' else [])
            requested_at = 0
            heartbeat = None
            while time.monotonic() < until:
                if launcher.poll() is not None:
                    raise AssertionError('Launcher exited; see ' + str(log_path))
                message = gcs.recv_match(blocking=True, timeout=.5)
                if message is not None and message.get_srcSystem() == system:
                    name = message.get_type()
                    seen.add(name)
                    if name == 'HEARTBEAT':
                        heartbeat = message
                        assert message.type == vehicle_type, (kind, message.type)
                        assert not message.base_mode & 128, 'unexpected armed simulation'
                    elif name == 'PARAM_VALUE':
                        param = message.param_id
                        if isinstance(param, bytes):
                            param = param.decode().rstrip('\0')
                        if param in pending:
                            result['requested_parameters'][param] = message.param_value
                            pending.remove(param)
                if heartbeat is not None and pending and time.monotonic() - requested_at > 1:
                    gcs.mav.param_request_read_send(system, 1, pending[0].encode(), -1)
                    requested_at = time.monotonic()
                if not pending and {'HEARTBEAT', 'ATTITUDE', 'GLOBAL_POSITION_INT'} <= seen:
                    break
            else:
                raise AssertionError('Missing bidirectional telemetry/parameters: ' + str((seen, pending)))
            assert result['requested_parameters']['MAV_SYSID'] == system
            if kind == 'plane':
                assert result['requested_parameters']['SERVO3_FUNCTION'] == 73
                assert result['requested_parameters']['SERVO6_FUNCTION'] == 74
            manifest = json.loads((directory / 'session.json').read_text())
            for source, expected in manifest['inputs_sha256'].items():
                from vehicle_autonomy.app.bootstrap.qgc_simulation import digest
                assert digest(Path(source)) == expected, 'external source was modified'
            if gui:
                assert any(p['name'] == 'gui' for p in manifest['processes'])
                time.sleep(3)
                assert launcher.poll() is None, 'GUI startup failed'
            duplicate = subprocess.run(command, cwd='/tmp', capture_output=True,
                                       text=True, timeout=8)
            assert duplicate.returncode == 1 and launcher.poll() is None, 'duplicate disturbed owner'
            result['duplicate_rejected_without_stopping_owner'] = True
            for name in ['gazebo'] + (['gui'] if gui else []):
                content = (directory / (name + '.log')).read_text(errors='replace').lower()
                for error in ('failed to load system plugin', 'error while loading the library',
                              'unable to find uri', 'unable to find file'):
                    assert error not in content, 'Gazebo resource/plugin failure: ' + error
            result.update(message_types=sorted(seen), heartbeat_type=heartbeat.type,
                          model=manifest['model'], source_model=manifest['source_model'],
                          original_inputs_unchanged=True, gazebo_resource_errors=False)
        except Exception as exc:
            result['error'] = type(exc).__name__ + ': ' + str(exc)
        finally:
            if launcher.poll() is None:
                os.kill(launcher.pid, signal.SIGTERM)
            try:
                launcher.wait(timeout=35)
            except subprocess.TimeoutExpired:
                result['cleanup_error'] = 'launcher did not finish owned cleanup'
            gcs.close()
            if (directory / 'session.json').exists():
                manifest = json.loads((directory / 'session.json').read_text())
                result['remaining_process_groups'] = manifest.get('remaining_process_groups')
                result['cleanup_errors'] = manifest.get('cleanup_errors')
                result['launcher_exit'] = launcher.returncode
                result['passed'] = ('error' not in result and 'cleanup_error' not in result
                                    and launcher.returncode == 0
                                    and result['remaining_process_groups'] == []
                                    and result['cleanup_errors'] == [])
    directory.parent.joinpath(directory.name + '-result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('rover', 'copter', 'plane'), required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--gui', action='store_true')
    args = parser.parse_args()
    outcome = run(args.kind, args.run_dir.resolve(), gui=args.gui)
    print(json.dumps(outcome))
    raise SystemExit(0 if outcome['passed'] else 1)

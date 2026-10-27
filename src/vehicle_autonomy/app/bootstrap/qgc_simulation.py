"""Explicit local Gazebo/SITL sessions controlled by the operator's QGC.

This launcher creates no framework Runtime, Action, authority or command port.
SITL's native UDP serial endpoint is the only ground-station connection. It
never arms, starts a mission, writes parameters over MAVLink or opens hardware.
External model/ArduPilot/plugin trees are read-only inputs; all generated
models, parameters, EEPROM, logs and process records belong to a fresh run.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

from vehicle_autonomy._resources import resource_root


@dataclass(frozen=True)
class Model:
    kind: str
    name: str
    binary: Path
    model: Path
    world: Path
    parameters: tuple[Path, ...]
    plugin_root: Path
    twin_root: Path | None
    instance: int
    system_id: int

    @property
    def fdm_port(self):
        return 9002 + 10 * self.instance


def resolve_model(root, kind, ardupilot, plugin_root, twin_root):
    """Select actual models, never the framework's older Plane fixture."""
    instance, system_id = {'rover': (11, 1), 'copter': (12, 2), 'plane': (13, 3)}[kind]
    defaults = ardupilot / 'Tools/autotest/default_params'
    if kind == 'plane':
        name = 'twin_cessna'
        model = twin_root / 'models/twin_cessna/model.sdf'
        world = twin_root / 'worlds/twin_runway.sdf'
        parameters = (ardupilot / 'Tools/autotest/models/plane.parm', twin_root / 'config/twin.parm')
    elif kind == 'copter':
        name = 'iris_with_gimbal'
        model = plugin_root / 'models/iris_with_gimbal/model.sdf'
        world = plugin_root / 'worlds/iris_runway.sdf'
        parameters = (defaults / 'copter.parm', defaults / 'gazebo-iris.parm',
                      root / 'simulation/params/copter_telemetry.parm')
    else:
        name = 'target_rover'
        model = root / 'simulation/models/target_rover/model.sdf'
        world = root / 'simulation/worlds/rover_runway.sdf'
        parameters = (defaults / 'rover.parm', defaults / 'rover-skid.parm',
                      root / 'simulation/params/rover_telemetry.parm',
                      root / 'simulation/params/rover_phase2_rtl.parm')
    binary = ardupilot / 'build/sitl/bin' / {
        'rover': 'ardurover', 'copter': 'arducopter', 'plane': 'arduplane'}[kind]
    return Model(kind, name, binary, model, world, parameters, plugin_root,
                 twin_root if kind == 'plane' else None, instance, system_id)


def digest(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def preflight(model, headless):
    if shutil.which('gz') is None:
        raise ValueError('gz not found; configure the installed Gazebo environment first')
    if not headless and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        raise ValueError('No desktop available; use --headless or run in a desktop terminal')
    inputs = [model.binary, model.model, model.world, *model.parameters,
              model.plugin_root / 'build/libArduPilotPlugin.so']
    if model.twin_root:
        for command in ('cmake', 'c++'):
            if shutil.which(command) is None:
                raise ValueError(f'{command} required to build the fixed-wing payload plugin locally')
        inputs.extend([model.twin_root / 'plugins/CMakeLists.txt',
                       model.twin_root / 'plugins/TwinPayload.cc'])
    for path in inputs:
        if not path.is_file():
            raise ValueError('Required input missing: ' + str(path))
    if not os.access(model.binary, os.X_OK):
        raise ValueError('SITL binary is not executable: ' + str(model.binary))
    for port in (model.fdm_port, 5501 + 10 * model.instance):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError as exc:
                raise ValueError(f'Simulation UDP port {port} is busy; no process was stopped') from exc
    return {str(path): digest(path) for path in inputs}


def prepare(model, directory, world_name):
    """Change only the owned copy's FDM endpoint and world/include identity."""
    tree = ET.parse(model.model)
    plugins = tree.findall('.//plugin[@name="ArduPilotPlugin"]')
    if len(plugins) != 1:
        raise ValueError('Exactly one ArduPilotPlugin required in selected model')
    plugins[0].find('fdm_port_in').text = str(model.fdm_port)
    plugins[0].find('fdm_addr').text = '127.0.0.1'
    model_path = directory / 'model.sdf'
    tree.write(model_path, encoding='utf-8', xml_declaration=True)
    world = ET.parse(model.world)
    world.find('world').set('name', world_name)
    includes = [uri for uri in world.findall('.//include/uri')
                if uri.text == 'model://' + model.name]
    if len(includes) != 1:
        raise ValueError('Selected world must include the chosen model exactly once')
    includes[0].text = str(model_path)
    world_path = directory / 'world.sdf'
    world.write(world_path, encoding='utf-8', xml_declaration=True)
    params = []
    for i, source in enumerate(model.parameters):
        copy = directory / f'defaults-{i}-{source.name}'
        shutil.copyfile(source, copy)
        params.append(copy)
    return world_path, params


def environment(root, model, partition):
    env = dict(os.environ, GZ_IP='127.0.0.1', GZ_PARTITION=partition)
    resources = [root / 'simulation/models', model.plugin_root / 'models',
                 model.plugin_root / 'worlds']
    plugins = [model.plugin_root / 'build']
    if model.twin_root:
        resources[:0] = [model.twin_root / 'models', model.twin_root / 'worlds']
        plugins.insert(0, model.twin_root / 'plugins/build')
    for key, paths in [('GZ_SIM_RESOURCE_PATH', resources), ('GZ_SIM_SYSTEM_PLUGIN_PATH', plugins)]:
        env[key] = ':'.join([*(str(p) for p in paths), env.get(key, '')])
    return env


class Session:
    def __init__(self, directory, env, manifest):
        self.directory, self.env, self.manifest = directory, env, manifest
        self.processes = []
        self.save()

    def save(self):
        (self.directory / 'session.json').write_text(json.dumps(self.manifest, indent=2) + '\n')

    def start(self, name, command, cwd=None, *, transient=False):
        log = (self.directory / (name + '.log')).open('w')
        try:
            process = subprocess.Popen(command, cwd=cwd or self.directory, env=self.env,
                                       stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        except BaseException:
            log.close()
            raise
        record = dict(name=name, pid=process.pid, pgid=process.pid, command=command, transient=transient,
                      start_ticks=Path(f'/proc/{process.pid}/stat').read_text().rsplit(')', 1)[1].split()[19])
        self.processes.append((process, log, record))
        self.manifest['processes'].append(record)
        self.save()
        return process

    def build_payload(self, source):
        """Rebuild in this run, never reuse or modify an external ABI binary."""
        build = self.directory / 'twin-payload-build'
        for name, command in [
            ('payload-configure', ['cmake', '-S', str(source), '-B', str(build)]),
            ('payload-build', ['cmake', '--build', str(build), '-j2']),
        ]:
            process = self.start(name, command, transient=True)
            try:
                code = process.wait(timeout=120)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(name + ' timed out; see run log') from exc
            if code:
                raise RuntimeError(name + ' failed; see run log')
        library = build / 'libTwinPayload.so'
        if not library.is_file():
            raise ValueError('Local payload plugin build did not produce its library')
        self.env['GZ_SIM_SYSTEM_PLUGIN_PATH'] = str(build) + ':' + self.env['GZ_SIM_SYSTEM_PLUGIN_PATH']
        self.manifest['payload_plugin'] = dict(path=str(library), sha256=digest(library),
                                              source=str(source))
        self.save()

    def close(self):
        errors = []
        for process, log, record in reversed(self.processes):
            try:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                # The gz wrapper can exit before its server/GUI descendants.
                # Finish this owned group before releasing the vehicle lock.
                end = time.monotonic() + 3
                while time.monotonic() < end:
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(.05)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                record['exit_code'] = process.returncode
            except Exception as exc:
                errors.append(type(exc).__name__)
            finally:
                log.close()
        remaining = []
        for process, _, _ in self.processes:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                continue
            remaining.append(process.pid)
        if remaining:
            errors.append('remaining_process_groups')
        self.manifest.update(ready=False, ended_at=datetime.now(timezone.utc).isoformat(),
                             remaining_process_groups=remaining, cleanup_errors=errors)
        self.save()
        if errors:
            raise RuntimeError('Owned process cleanup failed: ' + ', '.join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('rover', 'copter', 'plane'), required=True)
    parser.add_argument('--headless', action='store_true', help='Do not open the Gazebo GUI')
    parser.add_argument('--check', action='store_true', help='Validate local inputs without starting anything')
    parser.add_argument('--qgc-port', type=int, default=14550, help='QGC UDP listener on 127.0.0.1')
    parser.add_argument('--duration', type=float, help='Optional finite smoke-test duration in seconds')
    parser.add_argument('--run-dir', type=Path, help='Fresh output directory; never reuse EEPROM/state')
    parser.add_argument('--ardupilot-root', type=Path)
    parser.add_argument('--plugin-root', type=Path, default=Path.home() / 'gz_ws/src/ardupilot_gazebo')
    parser.add_argument('--twin-root', type=Path, default=Path.home() / 'twin-fixedwing')
    args = parser.parse_args()
    if not 1024 <= args.qgc_port <= 65535:
        parser.error('--qgc-port must be within 1024..65535')
    if args.duration is not None and not 1 <= args.duration <= 86400:
        parser.error('--duration must be within 1..86400 seconds')
    root = resource_root()
    ardupilot = args.ardupilot_root or root / 'artifacts/phase2-control/ardupilot-source'
    if args.ardupilot_root is None and not ardupilot.is_dir():
        ardupilot = Path.home() / 'ardupilot'
    model = resolve_model(root, args.kind, ardupilot.expanduser().resolve(),
                          args.plugin_root.expanduser().resolve(), args.twin_root.expanduser().resolve())
    session = None
    lock = None
    try:
        inputs = preflight(model, args.headless or args.check)
        if args.check:
            print(json.dumps(dict(kind=model.kind, model=model.name, valid=True,
                                  source_model=str(model.model), qgc=f'127.0.0.1:{args.qgc_port}')))
            return 0
        lock_root = root / 'runtime/qgc-simulation'
        lock_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = (lock_root / (args.kind + '.lock')).open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('This vehicle launcher is already running; no process was stopped') from exc
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        directory = (args.run_dir or root / f'artifacts/simulation/qgc-{args.kind}-{stamp}-{uuid4().hex[:6]}').resolve()
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        world_name = f'qgc_{args.kind}_{uuid4().hex[:12]}'
        world_path, params = prepare(model, directory, world_name)
        partition = 'vaf_' + world_name
        env = environment(root, model, partition)
        manifest = dict(kind=model.kind, model=model.name, source_model=str(model.model),
                        source_world=str(model.world), inputs_sha256=inputs,
                        world=world_name, partition=partition, fdm_port=model.fdm_port,
                        instance=model.instance, system_id=model.system_id,
                        qgc_host='127.0.0.1', qgc_port=args.qgc_port, framework_runtime=False,
                        phase5=False, automatic_commands=False, ready=False, processes=[],
                        started_at=datetime.now(timezone.utc).isoformat())
        session = Session(directory, env, manifest)

        def stop(signum, frame):
            raise KeyboardInterrupt

        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            if model.twin_root:
                print('Building the fixed-wing payload plugin in this run directory...', flush=True)
                session.build_payload(model.twin_root / 'plugins')
            server = ['gz', 'sim', '-s', '-r', '-v3']
            if model.twin_root:
                server.append('--headless-rendering')
            session.start('gazebo', server + [str(world_path)])
            aircraft = directory / 'aircraft'
            aircraft.mkdir(mode=0o700)
            session.start('sitl', [str(model.binary), '--model', 'JSON', '--speedup', '1',
                                  '--home=-35.363262,149.165237,584,90',
                                  '--defaults', ','.join(map(str, params)),
                                  '--sim-address=127.0.0.1', f'-I{model.instance}',
                                  '--sysid', str(model.system_id),
                                  '--serial0', f'udpclient:127.0.0.1:{args.qgc_port}',
                                  '--serial1', 'none', '--serial2', 'none'], cwd=aircraft)
            if not args.headless:
                session.start('gui', ['gz', 'sim', '-g', '-v3'])
            session.manifest['ready'] = True
            session.save()
            print(f'{model.kind}: {model.name}; QGC UDP 127.0.0.1:{args.qgc_port}; system ID {model.system_id}', flush=True)
            print(f'Logs/state: {directory}', flush=True)
            print('Waiting for QGC. Allow sensor/EKF initialization; use QGC to operate. Ctrl+C stops this session.', flush=True)
            started = time.monotonic()
            while args.duration is None or time.monotonic() - started < args.duration:
                for process, _, record in session.processes:
                    if process.poll() is not None:
                        if record['transient'] and process.returncode == 0:
                            continue
                        if record['name'] == 'gui' and process.returncode == 0:
                            return 0
                        raise RuntimeError(f"{record['name']} exited {process.returncode}; see {directory}")
                time.sleep(.2)
        except KeyboardInterrupt:
            pass
        finally:
            # A second interrupt must not abandon the children during cleanup.
            for sig in previous:
                signal.signal(sig, signal.SIG_IGN)
            try:
                session.close()
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
        return 0
    except (OSError, ValueError, RuntimeError, ET.ParseError) as exc:
        print(f'Simulation launch failed: {exc}', flush=True)
        return 1
    finally:
        if lock is not None:
            lock.close()


if __name__ == '__main__':
    raise SystemExit(main())

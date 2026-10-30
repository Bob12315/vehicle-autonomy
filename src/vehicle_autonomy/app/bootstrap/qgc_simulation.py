"""One owned local Gazebo/SITL and the current Phase 4 Web application.

Web Actions retain the sole vehicle writer; QGC receives telemetry only.
--qgc-only explicitly selects the former standalone ground-station mode.
Startup never arms, starts a mission, sends motion or opens hardware.
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
import sys
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.simulation_credentials import OwnedCredentials
from vehicle_autonomy.app.bootstrap.simulation_provisioning import SimulationProvisioning


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


class Session(SimulationProvisioning):
    def __init__(self, directory, env, manifest):
        self.directory, self.env, self.manifest = directory, env, manifest
        if env.get('VAF_CONTROL_CENTER_SESSION'):manifest['control_center_session']=env['VAF_CONTROL_CENTER_SESSION']
        self.run_dir = directory
        self.system_id = manifest['system_id']
        self.port = 5760 + 10 * manifest['instance']
        self.credentials = OwnedCredentials(directory, manifest) if manifest['framework_runtime'] else None
        self.processes = []
        self.save()

    def save(self):
        (self.directory / 'session.json').write_text(json.dumps(self.manifest, indent=2) + '\n')
        if self.manifest['framework_runtime']:
            owned = dict(self.manifest, processes=[p for p in self.manifest['processes']
                                                   if p['name'] in ('sitl', 'gazebo')])
            (self.directory / 'manifest.json').write_text(json.dumps(owned, indent=2) + '\n')

    _save = save

    def assert_alive(self):
        owned = [(p, r) for p, _, r in self.processes if r['name'] in ('sitl', 'gazebo')]
        if {r['name'] for _, r in owned} != {'sitl', 'gazebo'}:
            raise RuntimeError('one live owned simulation required')
        for process, record in owned:
            if process.poll() is not None or os.getpgid(process.pid) != record['pgid']:
                raise RuntimeError('owned simulation ended')

    def start(self, name, command, cwd=None, *, transient=False, pass_fds=()):
        log = (self.directory / (name + '.log')).open('w')
        try:
            process = subprocess.Popen(command, cwd=cwd or self.directory, env=self.env,
                                       stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True, pass_fds=pass_fds)
        except BaseException:
            log.close()
            raise
        record = dict(name=name, pid=process.pid, pgid=process.pid, command=command, transient=transient,
                      cwd=str(cwd or self.directory), exit_code=None,
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
                    process.wait(timeout=40 if record['name'] == 'application' else 8)
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
        if self.credentials is not None and not errors:
            try:
                self.credentials.destroy()
                self.signing_key = self.receive_signing = self._setup_protocol = None
            except Exception as exc:
                errors.append('credential_cleanup:' + type(exc).__name__)
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
    parser.add_argument('--qgc-only', action='store_true', help='standalone QGC control, without the Web application')
    parser.add_argument('--read-only', action='store_true', help='start Web with deployment SEND disabled')
    parser.add_argument('--allow-send', action='store_true', help='authorize this local simulation deployment; each Action still needs its own SEND')
    parser.add_argument('--web-port', type=int, help='loopback Web port; defaults: Rover 8780, Copter 8781, Plane 8782')
    parser.add_argument('--tool-agents',type=Path,help='optional trusted Agent allowlist for the same Web control center')
    parser.add_argument('--visualization-token-file',type=Path,help='optional independent narrow visualization feed credential')
    parser.add_argument('--source-time-sync',action='store_true',help='enable existing signed read-only source clock synchronization for concurrent desktop visualization')
    parser.add_argument('--studio-demo',action='store_true',help='offer the software-only Mission Studio scenario; no automatic mission execution')
    parser.add_argument('--tool-port',type=int,default=8791,help='optional loopback Agent listener port')
    parser.add_argument('--tool-data-dir',type=Path,help='optional persistent Tool/Workspace state separate from this fresh simulation journal')
    parser.add_argument('--duration', type=float, help='Optional finite smoke-test duration in seconds')
    parser.add_argument('--run-dir', type=Path, help='Fresh output directory; never reuse EEPROM/state')
    parser.add_argument('--ardupilot-root', type=Path)
    parser.add_argument('--plugin-root', type=Path, default=Path.home() / 'gz_ws/src/ardupilot_gazebo')
    parser.add_argument('--twin-root', type=Path, default=Path.home() / 'twin-fixedwing')
    args = parser.parse_args()
    if args.qgc_only and args.read_only:
        parser.error('--read-only belongs to Web mode; --qgc-only explicitly enables independent QGC control')
    if args.qgc_only and args.studio_demo:parser.error('Mission Studio scenarios require the Framework Web runtime')
    if args.qgc_only and (args.source_time_sync or args.visualization_token_file):parser.error('Framework source clock/visualization options do not apply to independent QGC mode')
    if args.qgc_only and (args.tool_agents or args.tool_data_dir):parser.error('Tool service belongs to the Web control center')
    if not 1024<=args.tool_port<=65535:parser.error('Tool port must be within 1024..65535')
    if not 1024 <= args.qgc_port <= 65535:
        parser.error('--qgc-port must be within 1024..65535')
    web_port = args.web_port if args.web_port is not None else {'rover': 8780, 'copter': 8781, 'plane': 8782}[args.kind]
    if not 1024 <= web_port <= 65535:
        parser.error('--web-port must be within 1024..65535')
    if args.tool_agents and args.tool_port==web_port:parser.error('Web and Agent listeners require distinct ports')
    if args.duration is not None and not 1 <= args.duration <= 86400:
        parser.error('--duration must be within 1..86400 seconds')
    root = resource_root()
    ardupilot = args.ardupilot_root or root / 'artifacts/phase2-control/ardupilot-source'
    if args.ardupilot_root is None and not ardupilot.is_dir():
        ardupilot = Path.home() / 'ardupilot'
    model = resolve_model(root, args.kind, ardupilot.expanduser().resolve(),
                          args.plugin_root.expanduser().resolve(), args.twin_root.expanduser().resolve())
    if not args.qgc_only and model.kind == 'plane':
        from dataclasses import replace
        model = replace(model, parameters=(*model.parameters, root / 'simulation/params/twin_plane_control.parm'))
    session = None
    lock = None
    try:
        inputs = preflight(model, args.headless or args.check)
        if not args.qgc_only:
            for port in (web_port, 5760 + 10 * model.instance):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe.bind(('127.0.0.1', port))
        if args.check:
            print(json.dumps(dict(kind=model.kind, model=model.name, valid=True,
                                  source_model=str(model.model), qgc=f'127.0.0.1:{args.qgc_port}',
                                  framework_runtime=not args.qgc_only, phase5=False,
                                  web=None if args.qgc_only else f'http://127.0.0.1:{web_port}/control')))
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
                        qgc_host='127.0.0.1', qgc_port=args.qgc_port, framework_runtime=not args.qgc_only,
                        qgc_role='control' if args.qgc_only else 'telemetry_only',
                        ports={'tcp': 5760 + 10 * model.instance},
                        binary_path=str(model.binary), binary_sha256=inputs[str(model.binary)],
                        phase5=False, automatic_motion=False, ready=False, processes=[],
                        setup_protocol='none' if args.qgc_only else 'fresh signing and read-only protocol queries',
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
            if session.credentials is not None:
                aircraft = session.credentials.create_state('')
                session.save()
            else:
                aircraft = directory / 'aircraft'
                aircraft.mkdir(mode=0o700)
            session.start('sitl', [str(model.binary), '--model', 'JSON', '--speedup', '1',
                                  '--home=-35.363262,149.165237,584,90',
                                  '--defaults', ','.join(map(str, params)),
                                  '--sim-address=127.0.0.1', f'-I{model.instance}',
                                  '--sysid', str(model.system_id),
                                  '--serial0', f'udpclient:127.0.0.1:{args.qgc_port}' if args.qgc_only else 'tcp:0',
                                  '--serial1', 'none', '--serial2', 'none'], cwd=aircraft)
            if not args.headless:
                session.start('gui', ['gz', 'sim', '-g', '-v3'])
            if not args.qgc_only:
                print('Preparing authenticated telemetry for the Web application...', flush=True)
                deadline = time.monotonic() + 25
                while True:
                    session.assert_alive()
                    try:
                        with socket.create_connection(('127.0.0.1', session.port), timeout=.2):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise RuntimeError('SITL TCP endpoint did not start')
                        time.sleep(.2)
                session.provision_receive_signing('')
                if args.source_time_sync:session.verify_parameters({'SERIAL0_BAUD':115.},'phase5_clock_uart_baud')
                if model.kind == 'rover':
                    session.verify_parameters(dict(RTL_SPEED=.5, WP_SPEED=.5, WP_RADIUS=.2,
                                                   WP_PIVOT_ANGLE=45, WP_PIVOT_RATE=30), 'rover_parameter_readback')
                elif model.kind == 'plane':
                    session.verify_parameters(dict(SERVO3_FUNCTION=73, SERVO6_FUNCTION=74,
                        SERVO3_MIN=1000, SERVO3_MAX=2000, SERVO3_TRIM=1000,
                        SERVO6_MIN=1000, SERVO6_MAX=2000, SERVO6_TRIM=1000,
                        AIRSPEED_CRUISE=12, AIRSPEED_MIN=7, AIRSPEED_MAX=20,
                        FENCE_ENABLE=1, FENCE_RADIUS=2000, FENCE_ALT_MAX=150, RTL_ALTITUDE=50), 'plane_parameter_readback')
                command = [sys.executable, '-m', 'vehicle_autonomy.app.web.mission_cli',
                    '--simulation', f'{model.kind}={directory / "manifest.json"}',
                    '--port', str(web_port), '--data-dir', str(directory / 'application'),
                    '--token-file', str(directory / 'web-token.private'),
                    '--qgc-monitor-port', str(args.qgc_port)]
                if args.tool_agents:command+=['--tool-agents',str(args.tool_agents.expanduser().resolve()),'--tool-port',str(args.tool_port)]
                if args.visualization_token_file:command+=['--visualization-token-file',str(args.visualization_token_file.expanduser().resolve())]
                if args.source_time_sync:command+=['--source-time-sync']
                if args.studio_demo:command+=['--studio-demo']
                if args.tool_data_dir:command+=['--tool-data-dir',str(args.tool_data_dir.expanduser().resolve())]
                import secrets
                token_path = directory / 'web-token.private'
                with os.fdopen(os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as token:
                    session.credentials.register_private(token_path.name, token.fileno())
                    session.save()
                    token.write(secrets.token_urlsafe(32) + '\n')
                if args.allow_send and not args.read_only:
                    command.append('--allow-send')
                from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry
                registry = ProviderRegistry()
                if not registry.root.exists() and not registry.anchor().path.exists():
                    command.append('--initialize-provider-registry')
                application = session.start('application', command)
                import urllib.request
                deadline = time.monotonic() + 30
                while True:
                    session.assert_alive()
                    if application.poll() is not None:
                        raise RuntimeError('Web application exited; see application.log')
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{web_port}/control', timeout=.5) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise RuntimeError('Web application did not become available; see application.log')
                        time.sleep(.2)
                session.manifest.update(web_url=f'http://127.0.0.1:{web_port}/control',
                    token_file=str(directory / 'web-token.private'), deployment_send=args.allow_send and not args.read_only)
            session.manifest['ready'] = True
            session.save()
            print(f'{model.kind}: {model.name}; QGC UDP 127.0.0.1:{args.qgc_port}; system ID {model.system_id}', flush=True)
            print(f'Logs/state: {directory}', flush=True)
            if args.qgc_only:
                print('Waiting for QGC. Allow sensor/EKF initialization; use QGC to operate. Ctrl+C stops this session.', flush=True)
            else:
                print(f'Web: {session.manifest["web_url"]}', flush=True)
                print(f'Access token file: {directory / "web-token.private"} (paste into Web; never published)', flush=True)
                print('Wait for fresh EKF/state, then authorize each Web Action. QGC is telemetry-only. Ctrl+C closes this session.', flush=True)
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

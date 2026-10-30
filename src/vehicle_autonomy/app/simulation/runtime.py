"""Owned Gazebo/SITL bootstrap using the existing provisioning and Driver.

The lifecycle owner can start/stop its processes, but every vehicle command
still crosses VehicleActionDriver -> SimulationRuntime -> Execution. Optional
dependencies load only when starting an explicitly requested local session.
"""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import xml.etree.ElementTree as ET

from vehicle_autonomy.app.bootstrap.qgc_simulation import (
    Session, environment, preflight, prepare, resolve_model,
)
from .faults import SoftwareFaultLink
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from vehicle_autonomy.app.bootstrap.paths import RuntimePaths


def stamp():
    return datetime.now(timezone.utc).isoformat()


def number(text, name):
    match = re.search(r'\b' + re.escape(name) + r':\s*([-+0-9.eE]+)', text)
    return None if match is None else float(match.group(1))


def duration(text, name):
    match = re.search(r'\b' + re.escape(name) + r'\s*\{([^}]*)\}', text, re.S)
    if match is None:
        return None
    return (number(match[1], 'sec') or 0) + (number(match[1], 'nsec') or 0) / 1e9


class LocalRuntime:
    def __init__(self, root, directory, scene_id, vehicle, *, ardupilot_root=None,
                 plugin_root=None, twin_root=None, allow_send=False, seed=0,
                 extra_plugin_paths=()):
        self.root, self.directory = Path(root), Path(directory)
        self.scene_id, self.vehicle = scene_id, vehicle
        self.host = HostEnvironment(self.root)
        self.ardupilot_root = self.host.path('ardupilot_root', ardupilot_root)
        self.plugin_root = self.host.path('gazebo_plugin_root', plugin_root)
        self.twin_root = self.host.path('fixedwing_root', twin_root)
        self.allow_send, self.seed = allow_send, seed
        self.extra_plugin_paths=tuple(Path(path) for path in extra_plugin_paths)
        self.world = 'vaf_' + directory.name.replace('-', '_')
        self.partition = self.world
        self.session = self.driver = self.proof = self.link = self.lock = None
        self.model = None
        self.started = None
        self.target = 'simulation-' + directory.name
        self.last_cpu = None

    def _allocate(self, kind):
        # The common root lock also isolates launchers with different data dirs.
        locks = RuntimePaths(self.root).slot('state', 'simulation-center-locks')
        locks.mkdir(parents=True, exist_ok=True, mode=0o700)
        for instance in range(40, 72):
            lock = (locks / f'instance-{instance}.lock').open('a')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                for port, transport in ((5760 + 10*instance, socket.SOCK_STREAM),
                                        (9002 + 10*instance, socket.SOCK_DGRAM),
                                        (5501 + 10*instance, socket.SOCK_DGRAM)):
                    with socket.socket(socket.AF_INET, transport) as probe:
                        probe.bind(('127.0.0.1', port))
                self.lock = lock
                return instance
            except (BlockingIOError, OSError):
                lock.close()
        raise ValueError('BLOCKED: no isolated SITL instance ports available')

    def _base_env(self):
        env = dict(self.host.process_environment(), GZ_IP='127.0.0.1', GZ_PARTITION=self.partition)
        env['GZ_SIM_RESOURCE_PATH'] = ':'.join(map(str, (
            self.root/'simulation/models', self.host.path('legacy_assets'),
            self.host.path('legacy_assets')/'adapter_models',
            self.plugin_root/'models', self.twin_root/'models',
        ))) + ':' + env.get('GZ_SIM_RESOURCE_PATH', '')
        env['GZ_SIM_SYSTEM_PLUGIN_PATH'] = ':'.join(map(str, (
            *self.extra_plugin_paths,self.plugin_root/'build',
        ))) + ':' + env.get('GZ_SIM_SYSTEM_PLUGIN_PATH','')
        return env

    def start(self, world_path, cancelled=lambda: False):
        if not self.host.available('gazebo'):
            raise ValueError('BLOCKED: Gazebo gz executable is missing')
        self.started = time.monotonic()
        tree = ET.parse(world_path)
        world = tree.getroot().find('world')
        if world is None:
            raise ValueError('one SDF world required')
        world.set('name', self.world)
        for filename, name in (
            ('gz-sim-imu-system', 'Imu'), ('gz-sim-navsat-system', 'NavSat'),
            ('gz-sim-user-commands-system', 'UserCommands'),
            ('gz-sim-scene-broadcaster-system', 'SceneBroadcaster'),
        ):
            if world.find(f"plugin[@name='gz::sim::systems::{name}']") is None:
                ET.SubElement(world, 'plugin', filename=filename, name='gz::sim::systems::'+name)
        manifest = dict(framework_runtime=False, kind='world', world=self.world,
                        partition=self.partition, processes=[], started_at=stamp(), ready=False,
                        system_id=0, instance=0)
        env = self._base_env()
        if self.vehicle != 'none':
            instance = self._allocate(self.vehicle)
            self.model = resolve_model(self.root, self.vehicle, self.ardupilot_root,
                                       self.plugin_root, self.twin_root)
            self.model = replace(self.model, instance=instance, system_id=instance+1)
            if self.vehicle == 'plane':
                self.model = replace(self.model, parameters=(*self.model.parameters,
                    self.root/'simulation/params/twin_plane_control.parm'))
            try:
                inputs = preflight(self.model, True)
            except ValueError as exc:
                raise ValueError('BLOCKED: '+str(exc)) from exc
            # Preserve the actual proven model's spawn/heading, while the
            # generated scenario owns only its environment and mission regions.
            original = ET.parse(self.model.world)
            include = next((i for i in original.findall('.//include')
                            if i.findtext('uri') == 'model://'+self.model.name), None)
            if include is None:
                raise ValueError('owned source world model include missing')
            world.append(include)
            tree.write(world_path, encoding='utf-8', xml_declaration=True)
            self.model = replace(self.model, world=Path(world_path))
            owned_world, params = prepare(self.model, self.directory, self.world)
            env = environment(self.root, self.model, self.partition)
            env['GZ_SIM_SYSTEM_PLUGIN_PATH']=':'.join(map(str,self.extra_plugin_paths))+':'+env.get('GZ_SIM_SYSTEM_PLUGIN_PATH','')
            manifest.update(kind=self.vehicle, model=self.model.name,
                framework_runtime=True, instance=instance, system_id=self.model.system_id,
                ports={'tcp':5760+10*instance}, fdm_port=self.model.fdm_port,
                binary_path=str(self.model.binary), binary_sha256=inputs[str(self.model.binary)],
                inputs_sha256=inputs, automatic_motion=False, deployment_send=self.allow_send)
            world_path = owned_world
        else:
            tree.write(world_path, encoding='utf-8', xml_declaration=True)
        self.session = Session(self.directory, env, manifest)
        if self.model and self.model.twin_root:
            self.session.build_payload(self.model.twin_root/'plugins')
        if cancelled():
            raise InterruptedError('session cancelled during preparation')
        self.session.start('gazebo', [self.host.executable('gazebo') or 'gz','sim','-s','-r','--headless-rendering','-v3', str(world_path)])
        if self.model:
            aircraft = self.session.credentials.create_state('')
            self.session.save()
            self.session.start('sitl', [str(self.model.binary), '--model','JSON','--speedup','1',
                '--home=-35.363262,149.165237,584,90', '--defaults',','.join(map(str,params)),
                '--sim-address=127.0.0.1', f'-I{self.model.instance}',
                '--sysid',str(self.model.system_id), '--serial0','tcp:0',
                '--serial1','none','--serial2','none'], cwd=aircraft)
            deadline = time.monotonic()+30
            while time.monotonic()<deadline:
                if cancelled():
                    raise InterruptedError('session cancelled during SITL startup')
                self.session.assert_alive()
                try:
                    with socket.create_connection(('127.0.0.1',self.session.port),timeout=.2):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise TimeoutError('owned SITL TCP startup timeout')
            self.session.provision_receive_signing('')
            if self.vehicle == 'rover':
                self.session.verify_parameters(dict(RTL_SPEED=.5,WP_SPEED=.5,WP_RADIUS=.2,
                    WP_PIVOT_ANGLE=45,WP_PIVOT_RATE=30),'rover_parameter_readback')
            from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation
            from vehicle_autonomy.app.bootstrap.action_driver import VehicleActionDriver
            from vehicle_autonomy.app.bootstrap.simulation_profile import SimulationProfile
            from vehicle_autonomy.vehicles.ardupilot.commands import ArduPilotCommandTranslator
            from vehicle_autonomy.vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
            from vehicle_autonomy.vehicles.plane.ardupilot_commands import ArduPlaneCommandTranslator
            from vehicle_autonomy.vehicles.ardupilot.transports.bytes import TcpByteTransport
            self.proof = OwnedActionSimulation(self.directory/'manifest.json')
            key = 'rover_phase2' if self.vehicle=='rover' else self.vehicle
            profile = replace(SimulationProfile.load(self.root/f'simulation/profiles/{key}.toml'),
                              port=self.session.port, vehicle_id=self.target)
            translator = {'rover':ArduRoverCommandTranslator,'copter':ArduPilotCommandTranslator,
                          'plane':ArduPlaneCommandTranslator}[self.vehicle](mode_ids=profile.mode_ids)
            def factory(host,port,*,timeout_s):
                self.link = SoftwareFaultLink(TcpByteTransport.connect(host,port,timeout_s=timeout_s),seed=self.seed)
                return self.link
            self.driver = VehicleActionDriver(self.target,profile,translator,self.proof,
                                             allow_send=self.allow_send,transport_factory=factory)
        self.session.manifest['ready'] = True
        self.session.save()

    def alive(self):
        if self.session is None:
            return False
        for process, _, record in self.session.processes:
            if not record.get('transient') and process.poll() is not None:
                raise RuntimeError(record['name']+' process exited '+str(process.returncode))
        return True

    def sample(self):
        if not self.alive():
            raise RuntimeError('owned simulation is not running')
        result = subprocess.run([self.host.executable('gazebo') or 'gz','topic','-e','-t','/stats','-n','1'],
            env=self.session.env,capture_output=True,text=True,timeout=4)
        stats = result.stdout
        sim = duration(stats,'sim_time')
        metrics = dict(sim_seconds=sim,wall_seconds=time.monotonic()-self.started,
                       rtf=number(stats,'real_time_factor'),cpu_percent=None,rss_mib=None,gpu=None)
        sessions=[self.session,*[c.session for c in getattr(self,'vehicles',{}).values() if c.session is not None]]
        processes = [p for session in sessions for p,_,r in session.processes if not r.get('transient')]
        # /proc is sampled for every descendant: gz's wrapper itself uses
        # negligible CPU and would misrepresent the actual server workload.
        groups = {p.pid for p in processes}
        cpu_ticks = rss_pages = 0
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                if int(fields[2]) not in groups:
                    continue
                cpu_ticks += int(fields[11])+int(fields[12])
                rss_pages += int(fields[21])
            except (OSError, ValueError, IndexError):
                continue
        now=time.monotonic()
        if self.last_cpu:
            elapsed=now-self.last_cpu[0]
            metrics['cpu_percent']=max(0,(cpu_ticks-self.last_cpu[1])/os.sysconf('SC_CLK_TCK')/elapsed*100)
        self.last_cpu=(now,cpu_ticks)
        metrics['rss_mib']=rss_pages*os.sysconf('SC_PAGE_SIZE')/1024**2
        errors=[]
        for name in ('gazebo', 'sitl'):
            path=self.directory/(name+'.log')
            if path.exists():
                text=path.read_text(errors='replace')[-262144:]
                errors.extend(line for line in text.splitlines() if '[Err]' in line or
                              'Failed to load system plugin' in line or 'Unable to find uri' in line)
        return dict(timestamp=stamp(),metrics=metrics,stats_raw=stats,error_lines=errors[:20])

    def truth(self):
        if self.model is None:
            return None
        try:
            reply=subprocess.run([self.host.executable('gazebo') or 'gz','topic','-e','-t',f'/world/{self.world}/pose/info','-n','1'],
                env=self.session.env,capture_output=True,text=True,timeout=3)
        except subprocess.TimeoutExpired:
            return None
        # Preserve raw ground-truth transport evidence; do not turn an
        # unmatched nested-link pose into the vehicle's reported position.
        raw=reply.stdout
        match=re.search(r'name:\s*"'+re.escape(self.model.name)+r'".*?position\s*\{([^}]*)\}',raw,re.S)
        if match is None:
            return None
        return dict(source='gazebo_pose_info',model=self.model.name,world=self.world,
                    simulation_seconds=duration(raw,'stamp'),
                    position={axis:number(match[1],axis) or 0 for axis in ('x','y','z')},
                    received_at=stamp())

    def control(self, operation):
        if operation not in ('pause','resume','reset'):
            raise ValueError('unsupported world operation')
        request = {'pause':'pause: true','resume':'pause: false',
                   'reset':'reset: {all: true}'}[operation]
        reply=subprocess.run([self.host.executable('gazebo') or 'gz','service','-s',f'/world/{self.world}/control',
            '--reqtype','gz.msgs.WorldControl','--reptype','gz.msgs.Boolean',
            '--timeout','3000','--req',request], env=self.session.env,
            capture_output=True,text=True,timeout=5)
        if reply.returncode or 'data: true' not in reply.stdout:
            raise RuntimeError('Gazebo world control was not confirmed')

    def close(self):
        errors=[]
        if self.driver is not None:
            try:self.driver.close()
            except Exception as exc:errors.append('driver:'+type(exc).__name__)
        elif self.proof is not None:
            self.proof.close()
        if self.session is not None:
            try:self.session.close()
            except Exception as exc:errors.append('processes:'+str(exc))
            if self.model is not None:
                released=True
                for port,transport in ((self.session.port,socket.SOCK_STREAM),
                    (self.model.fdm_port,socket.SOCK_DGRAM),
                    (5501+10*self.model.instance,socket.SOCK_DGRAM)):
                    try:
                        with socket.socket(socket.AF_INET,transport) as probe:
                            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                            probe.bind(('127.0.0.1',port))
                    except OSError:
                        released=False
                self.session.manifest['ports_released']=released
                self.session.save()
                if not released:errors.append('owned_ports_not_released')
        if self.lock is not None:
            self.lock.close();self.lock=None
        if errors:
            raise RuntimeError('owned cleanup incomplete: '+','.join(errors))

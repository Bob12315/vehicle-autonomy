"""One owned Gazebo World with independently provisioned fixed vehicle instances.

A child owns only its SITL. Its signed admission proof references the World
process as a read-only lifetime dependency, never as a child shutdown target.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
from vehicle_autonomy.app.bootstrap.paths import RuntimePaths
import re
import shutil
import socket
import subprocess
import time
from types import SimpleNamespace
from uuid import uuid4
from functools import wraps
from threading import RLock
import xml.etree.ElementTree as ET

from vehicle_autonomy.app.bootstrap.qgc_simulation import Session
from .runtime import LocalRuntime as WorldMetrics, stamp, duration, number
from .vehicles import VehicleRegistry
from .spawner import PortLease
from .faults import SoftwareFaultLink


class VehicleSession(Session):
    def __init__(self, directory, env, manifest, world_session):
        self.world_session = world_session
        super().__init__(directory, env, manifest)

    def assert_alive(self):
        records = [(p, r) for p, _, r in self.processes if r['name'] == 'sitl']
        if len(records) != 1:
            raise RuntimeError('one owned SITL required')
        for process, record in (*records, *[(p, r) for p, _, r in self.world_session.processes if r['name']=='gazebo']):
            if process.poll() is not None:
                raise RuntimeError('owned World or SITL ended')


class VehicleInstance:
    def __init__(self, owner, specification):
        self.owner = owner
        self.specification = deepcopy(specification)
        self.vehicle = specification['kind']
        self.family = owner.library.get(self.vehicle)['family']
        self.id = 'vehicle-' + uuid4().hex
        self.slot_id = specification['slot_id']
        self.directory = owner.directory / self.id
        self.directory.mkdir(mode=0o700)
        self.target = 'simulation-' + uuid4().hex
        self.world, self.partition = owner.world, owner.partition
        self.driver = self.proof = self.link = self.session = self.lease = None
        self.model = None
        self.spawn = specification['spawn']
        self.state = 'PREPARING'
        self.stages = dict(world_loaded=False, entity_spawned=False, plugin_connected=False,
                           sitl_running=False, framework_controlled=False)
        self.prepared = None
        self.removed = False
        self.entity_requested = False
        self.closed = False
        self.error = None
        self.camera_sources = {}
        self.camera_assembly = None
        self.mid360 = None
        self.mid360_assembly = None

    def view(self):
        p = self.prepared or {}
        result = dict(id=self.id, vehicle_id=self.id, slot_id=self.slot_id, kind=self.vehicle,
            target=self.target, state=self.state, error=self.error, stages=dict(self.stages), spawn=self.spawn,
            definition_version=p.get('version'), fingerprint=p.get('fingerprint'),
            model_hash=p.get('model_hash'), parameters_hash=p.get('parameters_hash'), sensor_hash=p.get('sensor_hash'),
            entity_name=p.get('entity_name'), system_id=p.get('system_id'), ports=p.get('ports'),
            logs={'sitl':str(self.directory.relative_to(self.owner.directory)/'sitl.log')},
            ground_truth=self.owner._truths.get(self.id),
            parameter_readback=None if self.session is None else self.session.manifest.get('fixed_parameters_readback'),
            sensor_activation={'imu':'Gazebo Imu system','gps':'Gazebo NavSat system',
                'rendering':{'assembly':self.camera_assembly, 'cameras':{k:v.health() for k,v in self.camera_sources.items()}},
                'mid360':self.mid360.snapshot() if self.mid360 else {'enabled':False}})
        if self.driver:
            info, world = self.driver.read_view()
            from vehicle_autonomy.contracts.core.serialization import to_json_value
            result['vehicle_status'] = info
            result['estimated_vehicle'] = None if world is None else to_json_value(world.vehicle)
            result['software_link'] = self.link.diagnostics() if self.link else None
        return result

    def start(self, cancelled):
        o = self.owner
        self.lease = PortLease.acquire(RuntimePaths(o.root).slot('state', 'simulation-center-locks'))
        entity = 'vaf_' + self.id.replace('-', '_')
        p = self.prepared = o.library.prepare(self.vehicle,self.directory,entity_name=entity,
            instance=self.lease.instance,system_id=self.lease.system_id)
        from .camera_assembly import assemble
        self.camera_assembly = assemble(o.root, self.directory, p, o.world,
            disable_zoom=bool(self.specification.get('sensors',{}).get('mid360')))
        if self.specification.get('sensors', {}).get('mid360'):
            from .mid360_assembly import assemble as assemble_mid360
            self.mid360_assembly = assemble_mid360(o.root, self.directory, p, o.world)
        self.model = SimpleNamespace(name=entity, system_id=self.lease.system_id,
            instance=self.lease.instance, fdm_port=self.lease.fdm_port, binary=p['binary'])
        env = dict(o.session.env)
        # All resource folders are fixed vehicle-library snapshots prepared
        # before Gazebo launch. No live World/model source mutation is needed.
        manifest = dict(framework_runtime=True,kind=self.family,world=o.world,partition=o.partition,
            model=entity,instance=self.lease.instance,system_id=self.lease.system_id,
            ports={'tcp':self.lease.tcp_port},fdm_port=self.lease.fdm_port,
            binary_path=str(p['binary']),binary_sha256=hashlib.sha256(Path(p['binary']).read_bytes()).hexdigest(),
            processes=[dict(next(r for r in o.session.manifest['processes'] if r['name']=='gazebo'),borrowed_world_dependency=True)],
            automatic_motion=False,deployment_send=o.allow_send,started_at=stamp(),ready=False,
            fixed_vehicle={key:p[key] for key in ('version','fingerprint','model_hash','parameters_hash','sensor_hash')})
        if self.vehicle == 'copter_rescue':
            manifest['rescue_2026'] = dict(definition_id=self.vehicle, fingerprint=p['fingerprint'])
        self.session = VehicleSession(self.directory,env,manifest,o.session)
        self.session.qgc_monitor_port=o.qgc_monitor_port
        if cancelled(): raise InterruptedError('vehicle start cancelled')
        self.stages['world_loaded'] = True
        o.notify(self)
        s=self.spawn
        yaw=math.radians(s['heading_deg'])
        request=(f'sdf_filename: {json.dumps(str(p["model_path"]))} name: {json.dumps(entity)} '
            f'allow_renaming: false pose {{position {{x:{s["x"]} y:{s["y"]} z:{s["z"]}}} '
            f'orientation {{z:{math.sin(yaw/2)} w:{math.cos(yaw/2)}}}}}')
        o.service('create','gz.msgs.EntityFactory',request)
        self.entity_requested=True
        o.notify(self)
        aircraft=self.session.credentials.create_state('')
        self.session.save()
        geo=o.geographic_reference
        # Gazebo ENU yaw zero is geographic east (AP heading 90 degrees).
        heading=(90-s['heading_deg'])%360
        home=f'{geo["latitude_deg"]},{geo["longitude_deg"]},{geo.get("elevation_m",geo.get("elevation",584))},{heading}'
        self.session.start('sitl',[str(p['binary']),'--model','JSON','--speedup','1',
            '--home='+home,'--defaults',','.join(map(str,p['parameters'])),
            '--sim-address=127.0.0.1',f'-I{self.lease.instance}','--sysid',str(self.lease.system_id),
            '--serial0','tcp:0','--serial1','none','--serial2','none'],cwd=aircraft)
        deadline=time.monotonic()+35
        while time.monotonic()<deadline:
            if cancelled(): raise InterruptedError('SITL start cancelled')
            self.session.assert_alive()
            try:
                with socket.create_connection(('127.0.0.1',self.session.port),timeout=.2): break
            except OSError: time.sleep(.1)
        else: raise TimeoutError('SITL listener startup timeout')
        self.stages['sitl_running']=True
        o.notify(self)
        self.session.provision_receive_signing('')
        if self.family=='rover':
            self.session.verify_parameters(dict(RTL_SPEED=.5,WP_SPEED=.5,WP_RADIUS=.2,
                WP_PIVOT_ANGLE=45,WP_PIVOT_RATE=30),'rover_parameter_readback')
        expected={'rover':dict(RTL_SPEED=.5,WP_SPEED=.5,WP_RADIUS=.2),
            'copter':dict(RTL_ALT_M=2,RTL_ALT_FINAL_M=0,MAV1_POSITION=10,MAV1_EXTRA1=10),
            'plane':dict(TKOFF_ALT=50,TKOFF_DIST=300,WP_LOITER_RAD=80,RTL_ALTITUDE=50,
                FENCE_ENABLE=1,FENCE_RADIUS=2000,FENCE_ALT_MAX=150)}[self.family]
        if self.vehicle=='copter_rescue':expected.update(MAV1_POSITION=20,MAV1_EXTRA1=30)
        self.session.verify_parameters(expected,'fixed_parameters_readback')
        self.session.verify_parameters({'SERIAL0_BAUD':115.},'phase5_clock_uart_baud')
        from vehicle_autonomy.app.bootstrap.simulation_profile import SimulationProfile
        from .driver_worker import ProcessVehicleDriver
        profile=replace(SimulationProfile.load(p['profile_path']),port=self.session.port,vehicle_id=self.target)
        self.driver=ProcessVehicleDriver(self.target,profile,self.session,model_kind=self.family,
            seed=o.seed,allow_send=o.allow_send)
        self.proof=self.driver.ownership
        self.link=self.driver.link
        from vehicle_autonomy.world.sensors.camera.live import CameraSource
        for camera in self.camera_assembly['cameras']:
            self.camera_sources[camera['slot']] = CameraSource(dict(kind='gazebo', topic=camera['topic'], world=o.world, fps=10),
                owner=self.session, name='camera-'+camera['slot'])
        if self.vehicle=='copter_rescue':
            from vehicle_autonomy.world.sensors.camera.processed import DetectionPreviewSource
            profile=json.loads((o.root/'configs/perception/rescue_2026_pt.json').read_text())
            original=self.camera_sources['gimbal-camera']
            self.camera_sources['yolo']=DetectionPreviewSource(self.directory/'rescue-inference',original,
                self.driver.snapshot,lambda:self.driver.info().get('rescue_perception'),
                model_sha256=profile['model_sha256'],source=f'/vaf/camera/{o.world}/{entity}/gimbal-camera/image',
                display_name='YOLO 识别画面（增稳）',image_domain='virtual_nadir')
            self.camera_sources['stabilized']=DetectionPreviewSource(self.directory/'rescue-inference',original,
                self.driver.snapshot,lambda:self.driver.info().get('rescue_perception'),
                model_sha256=profile['model_sha256'],source=f'/vaf/camera/{o.world}/{entity}/gimbal-camera/image',
                kind='stabilized',filename='stabilized.packet',display_name='增稳画面',image_domain='virtual_nadir')
        self.session.manifest['camera_assembly'] = self.camera_assembly
        if self.mid360_assembly:
            from .mid360_tools import Mid360Tools
            self.mid360 = Mid360Tools(self, self.mid360_assembly)
            self.mid360.start()
            self.session.manifest['mid360_assembly'] = self.mid360_assembly
        self.session.manifest['ready']=True
        self.session.save()
        self.state='STARTING'
        o.notify(self)

    def alive(self):
        if self.closed: return False
        if self.session: self.session.assert_alive()
        return True

    def close(self, *, world_ending=False):
        if self.closed: return
        errors=[]
        driver_errors=[]
        if self.driver:
            try:self.driver.close()
            except Exception as exc:driver_errors.append('driver: '+str(exc))
        elif self.proof:self.proof.close()
        if self.mid360:
            # Retain World/SITL ownership if any sensor/tool descendant cannot
            # be confirmed gone; never release ports/domains beneath it.
            self.mid360.close()
        for source in self.camera_sources.values():
            try:source.close()
            except Exception as exc:errors.append("camera: "+str(exc))
        # Lock-step physics waits on this SITL: remove the model while its FDM
        # is still answering. Killing SITL first would freeze the other models.
        if self.entity_requested and not self.removed:
            try:
                self.owner.service('remove','gz.msgs.Entity',f'name:{json.dumps(self.model.name)} type:MODEL')
                self.owner.confirm_absent(self.model.name)
                self.removed=True
            except Exception as exc:
                if not world_ending: raise RuntimeError('entity removal unconfirmed; SITL retained: '+str(exc)) from exc
                errors.append('entity remove: '+str(exc))
        process_error=None
        if self.session:
            try:self.session.close()
            except Exception as exc:process_error=exc
        resources_gone=(self.session is None or (all(p.poll() is not None for p,_,_ in self.session.processes)
                and not self.session.manifest.get('remaining_process_groups') and self.session.manifest.get('credentials_removed')))
        if self.lease and resources_gone:
            released=True
            ports=[(self.lease.tcp_port,socket.SOCK_STREAM),(self.lease.fdm_port,socket.SOCK_DGRAM),
                (self.lease.udp_port,socket.SOCK_DGRAM),
                (5762+10*self.lease.instance,socket.SOCK_STREAM),(5763+10*self.lease.instance,socket.SOCK_STREAM)]
            for port,transport in ports:
                try:
                    with socket.socket(socket.AF_INET,transport) as probe:
                        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                        probe.bind(('127.0.0.1',port))
                except OSError:released=False
            if self.session:
                self.session.manifest.update(ports_released=released,entity_removed=self.removed)
                try:self.session.save()
                except Exception as exc:process_error=process_error or exc
            if released:self.lease.release()
            else:process_error=process_error or RuntimeError('owned instance ports remain occupied')
        if process_error:raise process_error
        self.closed=not driver_errors
        self.state='FAILED' if driver_errors else 'FINISHED'
        self.stages['framework_controlled']=False
        if driver_errors or errors and not world_ending:raise RuntimeError('; '.join(driver_errors+errors))


def synchronized(function):
    @wraps(function)
    def call(self,*args,**kwargs):
        with self._state_lock:return function(self,*args,**kwargs)
    return call


class LocalRuntime(WorldMetrics):
    def __init__(self,*args,vehicles=(),geographic_reference=None,progress=None,qgc_monitor_port=None,**kwargs):
        self._state_lock=RLock()
        self.qgc_monitor_port=qgc_monitor_port
        super().__init__(*args,**kwargs)
        self.library=VehicleRegistry(self.root,ardupilot_root=self.ardupilot_root,
            plugin_root=self.plugin_root,twin_root=self.twin_root)
        self.progress=progress
        self.specifications=list(vehicles)
        self.vehicles={}
        self.retired=[]
        self.geographic_reference=geographic_reference or dict(latitude_deg=-35.363262,
            longitude_deg=149.165237,elevation_m=584)
        self._world_stopping=False
        self._library_resources=[]
        self._truths={}

    @synchronized
    def start(self,world_path,cancelled=lambda:False):
        if not self.host.available('gazebo'):raise ValueError('BLOCKED: Gazebo unavailable')
        self.started=time.monotonic()
        tree=ET.parse(world_path)
        world=tree.getroot().find('world')
        world.set('name',self.world)
        for filename,name in [('gz-sim-physics-system','Physics'),('gz-sim-imu-system','Imu'),
                ('gz-sim-navsat-system','NavSat'),('gz-sim-user-commands-system','UserCommands'),
                ('gz-sim-scene-broadcaster-system','SceneBroadcaster'),('gz-sim-sensors-system','Sensors')]:
            if world.find(f"plugin[@name='gz::sim::systems::{name}']") is None:
                ET.SubElement(world,'plugin',filename=filename,name='gz::sim::systems::'+name)
        sensors=world.find("plugin[@name='gz::sim::systems::Sensors']")
        if sensors.find('render_engine') is None:ET.SubElement(sensors,'render_engine').text='ogre2'
        tree.write(world_path,encoding='utf-8',xml_declaration=True)
        env=self._base_env()
        # Fixed resource roots are independent of the selected World. Dynamic
        # additions use the same immutable library and never restart peers.
        for definition in self.library.list_vehicles():
            if definition['status']=='READY':
                self._library_resources.extend(definition['resource_paths'])
        env['GZ_SIM_RESOURCE_PATH']=':'.join(map(str,self._library_resources))+':'+env['GZ_SIM_RESOURCE_PATH']
        manifest=dict(framework_runtime=False,kind='world',world=self.world,partition=self.partition,
            processes=[],started_at=stamp(),ready=False,system_id=0,instance=0)
        self.session=Session(self.directory,env,manifest)
        # Plane's fixed source payload is compiled once into this owned World,
        # since Gazebo loads shared libraries in its process environment.
        if self.library.get('plane')['status']=='READY':
            self.session.build_payload(self.twin_root/'plugins')
        if cancelled():raise InterruptedError('World preparation cancelled')
        self.session.start('gazebo',[self.host.executable('gazebo') or 'gz','sim','-s','-r','--headless-rendering','-v3',str(world_path)])
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if cancelled():raise InterruptedError('World startup cancelled')
            self.alive()
            reply=subprocess.run([self.host.executable('gazebo') or 'gz','service','-l'],env=self.session.env,capture_output=True,text=True,timeout=4)
            if f'/world/{self.world}/create' in reply.stdout:break
            time.sleep(.2)
        else:raise TimeoutError('World entity service unavailable')
        for specification in self.specifications:self.add(specification,cancelled)
        self.session.manifest['ready']=True
        self.session.save()

    @synchronized
    def add(self,specification,cancelled=lambda:False):
        child=VehicleInstance(self,specification)
        self.vehicles[child.id]=child
        self.notify(child)
        try:child.start(cancelled)
        except BaseException as exc:
            child.error=type(exc).__name__+': '+str(exc)
            try:
                child.close()
                child.state='FAILED'
                self.retired.append(child.view())
                del self.vehicles[child.id]
                self._aliases()
            except Exception:
                # An unremoved lockstep model remains an owned dependency.
                # Main health supervision retires the World, never abandons it.
                child.state='FAILED'
            raise
        self._aliases()
        return child

    def notify(self,child):
        callback=getattr(self,'progress',None)
        if callback:callback(child.view())

    def _aliases(self):
        child=next(iter(self.vehicles.values()),None)
        for name in ('driver','proof','link','model'):
            setattr(self,name,getattr(child,name) if child else None)
        self.target=child.target if child else 'simulation-'+self.directory.name

    @synchronized
    def remove(self,identifier):
        child=self.vehicles[identifier]
        child.close()
        self.retired.append(child.view())
        del self.vehicles[identifier]
        self._aliases()

    def service(self,name,request_type,request):
        reply=subprocess.run([self.host.executable('gazebo') or 'gz','service','-s',f'/world/{self.world}/{name}',
            '--reqtype',request_type,'--reptype','gz.msgs.Boolean','--timeout','5000','--req',request],
            env=self.session.env,capture_output=True,text=True,timeout=7)
        if reply.returncode or 'data: true' not in reply.stdout:
            raise RuntimeError('Gazebo '+name+' not confirmed: '+reply.stderr[-500:])

    def confirm_absent(self,entity):
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            reply=subprocess.run([self.host.executable('gazebo') or 'gz','topic','-e','-t',f'/world/{self.world}/pose/info','-n','1'],
                env=self.session.env,capture_output=True,text=True,timeout=3)
            if reply.returncode==0 and reply.stdout and not re.search(r'name:\s*"'+re.escape(entity)+r'"',reply.stdout):return
            time.sleep(.1)
        raise RuntimeError('removed entity remains present or World observation unavailable')

    @synchronized
    def alive(self):
        if self.session is None:return False
        for process,_,record in self.session.processes:
            if not record.get('transient') and process.poll() is not None:
                raise RuntimeError(record['name']+' process exited '+str(process.returncode))
        for child in tuple(self.vehicles.values()):
            if child.state=='FAILED':raise RuntimeError('failed vehicle rollback unconfirmed: '+str(child.error))
            child.alive()
        return True

    @synchronized
    def sample(self):
        result=super().sample()
        if not self.vehicles:
            result['vehicles']=[]
            return result
        reply=subprocess.run([self.host.executable('gazebo') or 'gz','topic','-e','-t',f'/world/{self.world}/pose/info','-n','1'],
            env=self.session.env,capture_output=True,text=True,timeout=3)
        raw=reply.stdout
        for child in tuple(self.vehicles.values()):
            if not child.stages['plugin_connected']:
                log=child.directory/'sitl.log'
                child.stages['plugin_connected']=log.exists() and 'JSON received:' in log.read_text(errors='replace')
            match=re.search(r'name:\s*"'+re.escape(child.model.name)+r'".*?position\s*\{([^}]*)\}',raw,re.S)
            truth=None if match is None else dict(source='gazebo_pose_info',model=child.model.name,world=self.world,
                simulation_seconds=duration(raw,'stamp'),position={axis:number(match[1],axis) or 0 for axis in ('x','y','z')},received_at=stamp())
            child.stages['entity_spawned']=truth is not None
            self._truths[child.id]=truth
        result['vehicles']=[dict(child.view(),ground_truth=self._truths.get(child.id)) for child in tuple(self.vehicles.values())]
        return result

    @synchronized
    def truth(self,vehicle_id=None):
        if not self.vehicles:return None
        return self._truths.get(vehicle_id or next(iter(self.vehicles)))

    @synchronized
    def close(self):
        errors=[]
        for child in tuple(self.vehicles.values()):
            try:child.close(world_ending=True)
            except Exception as exc:errors.append(str(exc))
        if self.session:
            try:self.session.close()
            except Exception as exc:errors.append(str(exc))
        # If Gazebo was stalled by a failed FDM peer, its termination releases
        # the dependency before retrying owned children. No foreign PID adopts.
        for child in self.vehicles.values():
            if not child.closed:
                try:child.close(world_ending=True)
                except Exception as exc:errors.append(str(exc))
        if errors:raise RuntimeError('owned cleanup incomplete: '+'; '.join(errors))

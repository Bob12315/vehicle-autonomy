"""Structured simulation use cases, process ownership and honest evidence levels."""
from copy import deepcopy
from contextlib import nullcontext
from dataclasses import asdict
import fcntl
import hashlib
import json
import math
from pathlib import Path
from queue import Queue,Empty,Full
import re
import shutil
import subprocess
from threading import Event, RLock, Thread
import time
from uuid import uuid4

from vehicle_autonomy._resources import resource_root as default_root
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.app.bootstrap.simulation_profile import SimulationProfile
from .catalog import SceneRegistry
from .runtime import stamp
from .universal_runtime import LocalRuntime
from .vehicles import VehicleRegistry
from .world_spawns import WorldSpawnRegistry


TERMINAL = frozenset({'FINISHED','FAILED','CANCELLED'})
ACTIVE = frozenset({'PREPARING','STARTING','READY','RUNNING'})
STATES = frozenset({'CREATED',*ACTIVE,'STOPPING',*TERMINAL})


class FrameworkFailure(RuntimeError):
    """The receive/control application failed while the World may stay healthy."""


def fields(payload, allowed, required=()):
    if type(payload) is not dict or set(payload)-set(allowed) or set(required)-set(payload):
        raise ValueError('structured fields required: '+', '.join(required))


class SimulationManager:
    def __init__(self, data_dir, registry=None, *, application=None, resource_root=None,
                 ardupilot_root=None, plugin_root=None, twin_root=None,
                 allow_send=False, startup_timeout=120):
        if type(allow_send) is not bool:
            raise ValueError('deployment SEND requires an explicit boolean')
        if type(startup_timeout) not in (int,float) or not math.isfinite(startup_timeout) or not 10<=startup_timeout<=600:
            raise ValueError('startup timeout must be within 10..600 seconds')
        self.root=Path(resource_root) if resource_root else default_root()
        self.directory=Path(data_dir).absolute()
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.registry=registry or SceneRegistry(self.root)
        self.world_spawns=WorldSpawnRegistry(self.registry)
        self.vehicle_registry=VehicleRegistry(self.root,ardupilot_root=ardupilot_root,plugin_root=plugin_root,twin_root=twin_root)
        self.operation_threads={}
        self.progress={}
        self.application=application
        self.allow_send=allow_send
        self.startup_timeout=startup_timeout
        self.runtime_options=dict(ardupilot_root=ardupilot_root,plugin_root=plugin_root,
                                  twin_root=twin_root,allow_send=allow_send)
        self.lock=RLock()
        self.records={}
        self.owners={}
        self._asset_leases={}
        self._owners_closed=set()
        self.threads={}
        self.stops={}
        self.asset_jobs={}
        self.asset_threads={}
        self.asset_stop=Event()
        self.closed=False
        self._directory_lock=(self.directory/'owner.lock').open('a')
        try:
            fcntl.flock(self._directory_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self._directory_lock.close()
            self._directory_lock=None
            raise ValueError('simulation data directory already has a live manager') from None
        # Restart never adopts a PID, reopens a writer, or replays an Action.
        for path in sorted(self.directory.glob('sim-*/report.json')):
            try:
                record=json.loads(path.read_text())
                identifier=record['id']
                if not re.fullmatch(r'sim-[0-9a-f]{32}',identifier) or path.parent.name!=identifier:
                    continue
                if record['state'] not in TERMINAL:
                    record.update(state='FAILED',ended_at=stamp(),
                        error='backend restarted: process ownership UNKNOWN; no automatic adoption or cleanup',
                        cleanup='UNKNOWN')
                    record['history'].append(dict(state='FAILED',at=stamp(),reason='backend restart'))
                self.records[identifier]=record
                self._save(record)
            except (OSError,ValueError,KeyError,TypeError):
                continue

    def _specifications(self,scene_id,raw,parameters,seed,*,peers=()):
        result=[]
        occupied=list(peers)
        slots={peer.get('slot_id') for peer in peers}
        for index,item in enumerate(raw):
            fields(item,('kind','spawn','slot_id'),('kind',))
            kind=item['kind']
            if type(kind) is not str:raise ValueError('registered vehicle kind required')
            definition=self.vehicle_registry.get(kind)
            if definition['status']!='READY':raise ValueError('BLOCKED: '+str(definition.get('reason')))
            slot=item.get('slot_id','slot-'+str(index+1))
            if type(slot) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',slot) or slot in slots:
                raise ValueError('unique bounded slot_id required')
            slots.add(slot)
            spawn=item.get('spawn')
            if type(spawn) is dict and set(spawn)=={'preset_id'}:spawn={'id':spawn['preset_id']}
            spawn=self.world_spawns.validate(scene_id,definition,spawn,peers=[{k:p[k] for k in ('spawn','definition')} for p in occupied],
                parameters=parameters,seed=seed)
            bounds=SimulationProfile.load(definition['profile_path']).safety
            if not (bounds.min_x_m<=spawn['x']<=bounds.max_x_m and bounds.min_y_m<=spawn['y']<=bounds.max_y_m):
                raise ValueError('BLOCKED: spawn is outside the unchanged Framework vehicle profile geofence')
            geo=self.world_spawns.describe(scene_id)['geographic_reference']
            if geo['heading_deg']!=0:raise ValueError('BLOCKED: rotated World geography has no qualified ENU binding')
            if kind!='plane' and (geo['latitude_deg'],geo['longitude_deg'],geo['elevation'])!=(-35.363262,149.165237,584.):
                raise ValueError('BLOCKED: World origin differs from the fixed Framework environment binding')
            spec=dict(kind=kind,slot_id=slot,spawn=spawn)
            result.append(spec)
            occupied.append(dict(spawn=spawn,definition=definition,slot_id=slot))
        return result

    def _project_vehicles(self,record,owner):
        if not hasattr(owner,'vehicles'):return
        vehicles=[]
        for child in tuple(owner.vehicles.values()):
            ready=self._vehicle_ready(child)
            child.stages['framework_controlled']=ready
            if ready and child.stages['plugin_connected']:child.state='RUNNING'
            vehicles.append(child.view())
        record['vehicles']=vehicles
        record['retired_vehicles']=deepcopy(owner.retired)
        record['target']=vehicles[0]['target'] if vehicles else None
        record['vehicle_id']=vehicles[0]['id'] if vehicles else None
        record['vehicle']=vehicles[0]['kind'] if vehicles else 'none'

    def _selected_vehicle(self,record,identifier,*,required=True):
        vehicles=record.get('vehicles',[])
        if identifier is None:
            if len(vehicles)>1:raise ValueError('vehicle_id required for a multi-vehicle World')
            if vehicles:return vehicles[0]
            if not required:return None
        for item in vehicles:
            if item['id']==identifier:return item
        raise ValueError('unknown vehicle_id in this World')

    def _require_safe(self,child):
        if not self._vehicle_ready(child):raise ValueError('fresh VALID vehicle state required for safe retirement')
        _,world=child.driver.read_view()
        state=world.vehicle
        linear=state.reported_twist.value.linear
        speed=math.sqrt(linear.x**2+linear.y**2+linear.z**2)
        if state.operation.armed is not False or abs(state.reported_pose.value.position.z)>1.5 or speed>.3:
            raise ValueError('safe switch/removal requires disarmed stationary ground; use original control to land/stop/disarm')
        related=self._related(child.target,bounded=False)
        for action in related['actions']:
            if action['state']=='REJECTED':continue
            if action['state'] not in {'SUCCEEDED','FAILED','CANCELLED','TIMED_OUT','UNKNOWN'} or not (action.get('safety') or {}).get('release_safe'):
                raise ValueError('unresolved Action safety barrier prevents epoch retirement')
        for mission in related['missions']:
            if mission['state'] not in {'SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN'} or mission.get('release_safe') is False:
                raise ValueError('unresolved Mission safety barrier prevents epoch retirement')

    def _detach(self,child):
        if not self.application:return
        app=self.application
        with app._control_lock:
            # Historical Action views still obtain their immutable command
            # results from this closed Driver. Never delete that evidence port.
            # The live vehicle selector excludes these retired targets.
            retired=getattr(app,'_retired_simulation_targets',set())
            retired.add(child.target)
            app._retired_simulation_targets=retired
            app._tracks.pop(child.target,None)

    def retiring_targets(self):
        with self.lock:
            return {target for record in self.records.values() for target in record.get('retiring_targets',[])}

    def _retire(self,record,children,value=True):
        targets=set(record.get('retiring_targets',[]))
        for child in children:
            if child.driver:child.driver.set_retiring(value)
            if value:targets.add(child.target)
            else:targets.discard(child.target)
        record['retiring_targets']=sorted(targets)

    def _vehicle_operation(self,kind,payload):
        with self.lock:
            record=self._get(payload['id'])
            if self.closed or record['state']!='RUNNING' or record.get('operation',{}).get('state')=='RUNNING' or record.get('switch',{}).get('state') in {'PREPARING','STOPPING','STARTING'}:
                raise ValueError('idle RUNNING World required')
            owner=self.owners[record['id']]
            if kind=='add':
                if len(owner.vehicles)>=4:raise ValueError('four vehicle budget exhausted')
                peers=[dict(spawn=c.spawn,definition=self.vehicle_registry.get(c.vehicle),slot_id=c.slot_id) for c in owner.vehicles.values()]
                vehicle=deepcopy(payload['vehicle'])
                if type(vehicle) is dict:vehicle.setdefault('slot_id','slot-'+uuid4().hex[:12])
                specification=self._specifications(record['scene_id'],[vehicle],record['configuration']['parameters'],record['configuration']['seed'],peers=peers)[0]
            else:
                selected=self._selected_vehicle(record,payload['vehicle_id'])
                specification=selected['id']
            self._retire(record,[owner.vehicles[specification]] if kind=='remove' else tuple(owner.vehicles.values()))
            record['operation']=dict(kind=kind,state='RUNNING',started_at=stamp(),error=None)
            try:self._save(record)
            except Exception as exc:
                self._persistence_failed(record,'vehicle operation dispatch',exc)
                self.stops[record['id']].set()
                raise
            thread=Thread(target=self._do_vehicle_operation,args=(record['id'],kind,specification),daemon=True)
            self.operation_threads[record['id']]=thread
            thread.start()
            return deepcopy(record)

    def _do_vehicle_operation(self,identifier,kind,specification):
        record=self.records[identifier]
        owner=self.owners[identifier]
        error=None
        child=None
        try:
            if kind=='remove':
                child=owner.vehicles[specification]
                self._cancel(child)
                self._require_safe(child)
                owner.remove(child.id)
                self._detach(child)
            else:
                owner.sample()
                peers=[]
                for peer in tuple(owner.vehicles.values()):
                    self._require_safe(peer)
                    truth=owner.truth(peer.id)
                    if truth is None:raise ValueError('live Gazebo peer position required before spawn')
                    peers.append(dict(spawn=truth['position'],definition=self.vehicle_registry.get(peer.vehicle),slot_id=peer.slot_id))
                specification=self._specifications(record['scene_id'],[dict(kind=specification['kind'],slot_id=specification['slot_id'],
                    spawn={k:specification['spawn'][k] for k in ('x','y','z','heading_deg')})],
                    record['configuration']['parameters'],record['configuration']['seed'],peers=peers)[0]
                child=owner.add(specification,self.stops[identifier].is_set)
                deadline=time.monotonic()+self.startup_timeout
                while time.monotonic()<deadline and not self.stops[identifier].is_set():
                    owner.sample()
                    if self._vehicle_ready(child) and child.stages['plugin_connected']:break
                    time.sleep(.2)
                else:raise TimeoutError('added vehicle readiness deadline expired')
                with self.application._control_lock if self.application else nullcontext():
                    if self.stops[identifier].is_set():raise InterruptedError('World stopping before added vehicle admission')
                    self._attach(child)
        except Exception as exc:
            error=type(exc).__name__+': '+str(exc)
            if kind=='add' and child is not None:
                try:owner.remove(child.id)
                except Exception:
                    # A partial plugin failure can stall lockstep peers; retire
                    # the World rather than publish false continuing health.
                    self.stops[identifier].set()
        finally:
            with self.lock:
                if record['state']=='RUNNING' and not self.stops[identifier].is_set():
                    if kind=='remove' and error and child is not None:self._retire(record,[child],False)
                    if kind=='add':self._retire(record,tuple(owner.vehicles.values()),False)
                record['operation'].update(state='FAILED' if error else 'SUCCEEDED',error=error,ended_at=stamp())
                self._project_vehicles(record,owner)
                try:self._save(record)
                except Exception as exc:
                    self._persistence_failed(record,'vehicle operation completion',exc)
                    self.stops[identifier].set()

    def _switch(self,payload):
        with self.lock:
            record=self._get(payload['id'])
            if self.closed or record['state']!='RUNNING' or record.get('operation',{}).get('state')=='RUNNING' or record.get('switch',{}).get('state') in {'PREPARING','STOPPING','STARTING'}:
                raise ValueError('idle RUNNING World required')
            spawns=payload.get('spawns',{})
            if type(spawns) is not dict or set(spawns)-{c.slot_id for c in self.owners[record['id']].vehicles.values()}:
                raise ValueError('spawns must map existing slot IDs')
            vehicles=[dict(kind=c.vehicle,slot_id=c.slot_id,spawn=spawns.get(c.slot_id,{'id':c.spawn['preset_id']}) if c.spawn.get('preset_id') else spawns.get(c.slot_id,{k:c.spawn[k] for k in ('x','y','z','heading_deg')}))
                for c in self.owners[record['id']].vehicles.values()]
            destination=dict(scene_id=payload['scene_id'],vehicles=vehicles,
                parameters=payload.get('parameters',{}),seed=payload.get('seed',record['configuration']['seed']))
            # Make the exact destination concrete and validate before retiring
            # a healthy World. New record never adopts old writers/credentials.
            new=self.create(destination)
            self._retire(record,tuple(self.owners[record['id']].vehicles.values()))
            record['switch']=dict(state='PREPARING',new_session_id=new['id'],scene_id=payload['scene_id'],error=None,started_at=stamp())
            try:self._save(record)
            except Exception as exc:
                self._persistence_failed(record,'World switch dispatch',exc)
                self.stops[record['id']].set()
                self.stop(new['id'])
                raise
            thread=Thread(target=self._do_switch,args=(record['id'],new['id']),daemon=True)
            self.operation_threads[record['id']]=thread
            thread.start()
            return deepcopy(record)

    def _do_switch(self,identifier,new_id):
        record=self.records[identifier]
        owner=self.owners[identifier]
        try:
            self._cancel(owner)
            for child in tuple(owner.vehicles.values()):self._require_safe(child)
            with self.lock:
                record['switch']['state']='STOPPING'
                self._save(record)
            self.stop(identifier)
            self.threads[identifier].join(self.startup_timeout+40)
            if self.threads[identifier].is_alive() or record['cleanup']!='COMPLETE':
                raise RuntimeError('old World cleanup not confirmed')
            for child in tuple(owner.vehicles.values()):self._detach(child)
            if self.closed:raise InterruptedError('service closing')
            with self.lock:
                record['switch']['state']='STARTING'
                self._save(record)
            self.start(new_id)
            self.wait_ready(new_id,self.startup_timeout+10)
            with self.lock:
                record['switch'].update(state='SUCCEEDED',ended_at=stamp())
                self.records[new_id]['previous_session_id']=identifier
                self._save(record)
                self._save(self.records[new_id])
        except Exception as exc:
            self.stop(new_id)
            with self.lock:
                if record['state']=='RUNNING':self._retire(record,tuple(owner.vehicles.values()),False)
                record['switch'].update(state='FAILED',error=type(exc).__name__+': '+str(exc),ended_at=stamp())
                self._save(record)

    def _queue_progress(self,identifier,vehicle):
        queue=self.progress[identifier]
        try:queue.put_nowait(vehicle)
        except Full:
            try:queue.get_nowait()
            except Empty:pass
            queue.put_nowait(vehicle)

    def _drain_progress(self,record):
        queue=self.progress.get(record['id'])
        if queue is None:return
        updates={}
        while True:
            try:
                vehicle=queue.get_nowait();updates[vehicle['id']]=vehicle
            except Empty:break
        if record['state'] not in {'PREPARING','STARTING'} and record.get('operation',{}).get('state')!='RUNNING':return
        vehicles={v['id']:v for v in record.get('vehicles',[])}
        vehicles.update(updates)
        record['vehicles']=list(vehicles.values())
        record['startup_progress']={v['id']:v['stages'] for v in record['vehicles']}

    def _save(self, record):
        path=self.directory/record['id']/'report.json'
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        temporary.replace(path)

    def _transition(self, record, state, reason=None):
        if state not in STATES:
            raise ValueError('unknown simulation state')
        record['state']=state
        record['history'].append(dict(state=state,at=stamp(),reason=reason))
        if state in TERMINAL:
            record['ended_at']=stamp()
        self._save(record)

    def _persistence_failed(self, record, stage, exc):
        """Record failure in memory only; never recursively attempt disk I/O."""
        message=stage+': '+type(exc).__name__+': '+str(exc)
        record.setdefault('persistence_errors',[]).append(message)
        record['persistence_errors']=record['persistence_errors'][-32:]
        record['error']='; '.join(filter(None,(record.get('error'),'report persistence failed: '+message)))
        domain=record.get('failure_domain')
        if not domain or 'persistence' not in domain.split('+'):
            record['failure_domain']='persistence' if not domain else domain+'+persistence'
        record['state']='FAILED'
        record['ended_at']=stamp()

    def _cleanup_owner(self, identifier, owner):
        """Cancellation, owned shutdown and observation have independent exits."""
        errors=[]
        if identifier not in self._owners_closed:
            try:
                self._cancel(owner)
            except Exception as exc:
                errors.append('cancel: '+type(exc).__name__+': '+str(exc))
            finally:
                # Neither a journal/report failure nor a broken cancellation
                # callback can suppress process and credential reclamation.
                try:
                    owner.close()
                    self._owners_closed.add(identifier)
                except Exception as exc:
                    errors.append('owner close: '+type(exc).__name__+': '+str(exc))
        return errors

    def _get(self, identifier):
        if type(identifier) is not str or identifier not in self.records:
            raise ValueError('unknown simulation session')
        return self.records[identifier]

    def catalog(self):
        result=[]
        definitions={kind:self.vehicle_registry.get(kind) for kind in ('rover','copter','plane','vtol')}
        for entry in self.registry.list_scenes():
            item=deepcopy(entry)
            spawn_info=self.world_spawns.describe(item['id'])
            item['spawn_info']=spawn_info
            ready=item.get('ready',True) and shutil.which('gz') is not None
            support={'none':dict(available=ready,reason='仅加载 Gazebo World')}
            for kind in ('rover','copter','plane','vtol'):
                definition=definitions[kind]
                admission=spawn_info['vehicle_support'][kind]
                support[kind]=dict(available=ready and admission['available'] and definition['status']=='READY',
                    reason=admission['reason'] if not admission['available'] else definition.get('reason'),
                    acceptance='NOT_TESTED: geometric admission is not native motion acceptance')
            item['vehicle_support']=support
            item['launchable_vehicles']=[k for k,v in support.items() if v['available']]
            result.append(item)
        return result

    def create(self, payload):
        fields(payload,('scene_id','vehicle','vehicles','spawn','seed','parameters'),('scene_id',))
        scene_id=payload['scene_id']
        scene=self.registry.get(scene_id)
        if 'vehicles' in payload and ('vehicle' in payload or 'spawn' in payload):
            raise ValueError('use either vehicles or legacy vehicle/spawn')
        raw=payload.get('vehicles')
        if raw is None:
            kind=payload.get('vehicle','none')
            if kind not in ('none','rover','copter','plane','vtol'):
                raise ValueError('unsupported simulation vehicle')
            raw=[] if kind=='none' else [dict(kind=kind,spawn=payload.get('spawn'))]
        if type(raw) is not list or len(raw)>4:
            raise ValueError('at most four fixed vehicles per World')
        seed=payload.get('seed',0)
        if type(seed) is not int or not 0<=seed<2**32:
            raise ValueError('seed must be an integer within 0..4294967295')
        parameters=deepcopy(payload.get('parameters',{}))
        if type(parameters) is not dict:
            raise ValueError('scenario parameters must be an object')
        parameters=self.registry.validate(scene_id,seed=seed,parameters=parameters)
        specifications=self._specifications(scene_id,raw,parameters,seed)
        vehicle=specifications[0]['kind'] if specifications else 'none'
        with self.lock:
            if self.closed:
                raise ValueError('simulation service is closed')
            if scene_id.startswith(('U_','H_')) and any(job.get('state') in ('INSTALLING','UNINSTALLING') for job in self.asset_jobs.values()):
                raise ValueError('asset installation is changing; wait for its operation to finish')
            if len(self.records)>=512:
                raise ValueError('simulation session budget exhausted')
            identifier='sim-'+uuid4().hex
            directory=self.directory/identifier
            directory.mkdir(mode=0o700)
            try:
                if scene_id.startswith(('U_','H_')) and self.registry.assets is not None:
                    self._asset_leases[identifier]=self.registry.assets.acquire_usage()
                self.registry.generate(scene_id,directory/'scenario.sdf',seed=seed,parameters=parameters)
            except Exception:
                lease=self._asset_leases.pop(identifier,None)
                if lease:lease.close()
                shutil.rmtree(directory)
                raise
            record=dict(schema=1,id=identifier,test_id=identifier,scene_id=scene_id,
                world_id=scene.get('world_id',scene_id),scenario_id=scene_id,vehicle=vehicle,
                vehicle_id=None,target=None,vehicles=[],vehicle_specifications=specifications,retired_vehicles=[],state='CREATED',paused=False,
                configuration=dict(seed=seed,parameters=parameters,scene_version=scene.get('version'),
                    generated_sdf_sha256=hashlib.sha256((directory/'scenario.sdf').read_bytes()).hexdigest()),created_at=stamp(),
                started_at=None,ended_at=None,error=None,failure_domain=None,cleanup=None,
                history=[dict(state='CREATED',at=stamp(),reason=None)],
                levels={f'L{i}':'NOT_TESTED' for i in range(1,7)},metrics={},samples=[],
                tests=[],actions=[],missions=[],tool_status=None,faults=[],
                logs={'gazebo':'gazebo.log','sitl':'sitl.log'},
                notes=['SITL 就绪不等于运动验收；Ground Truth 与飞控估计分别记录',
                       'CPU为自有进程组采样；GPU/碰撞/外部传感器没有来源时保持未知'])
            self.records[identifier]=record
            self._save(record)
            return deepcopy(record)

    def start(self, identifier):
        with self.lock:
            record=self._get(identifier)
            if self.closed or record['state']!='CREATED':
                raise ValueError('only a CREATED session can start; create a fresh session to replay')
            if sum(r['state'] in ACTIVE|{'STOPPING'} for r in self.records.values())>=4:
                raise ValueError('four-session concurrency budget exhausted')
            stop=Event()
            self.stops[identifier]=stop
            self.progress[identifier]=Queue(maxsize=64)
            self._transition(record,'PREPARING')
            worker=Thread(target=self._run,args=(identifier,),name='simulation-'+identifier,daemon=True)
            self.threads[identifier]=worker
            worker.start()
            return deepcopy(record)

    def _attach(self, owner):
        if hasattr(owner,'vehicles'):
            for child in tuple(owner.vehicles.values()):self._attach(child)
            return
        if not self.application or not owner.driver:
            return
        app=self.application
        with app._control_lock:
            from vehicle_autonomy.app.bootstrap.mission_binding import bind_simulations
            identities=bind_simulations({owner.target:owner.driver},app.journal)
            if owner.target in app.drivers or owner.target in app.runtime.drivers:
                raise ValueError('unique simulation target required')
            app.drivers[owner.target]=owner.driver
            app.runtime.drivers[owner.target]=owner.driver
            app.deployment_identities.update(identities)
            app.missions.identities.update(identities)

    def _cancel(self, owner):
        if hasattr(owner,'vehicles'):
            for child in tuple(owner.vehicles.values()):self._cancel(child)
            return
        if not self.application or not owner.driver:
            return
        app=self.application
        terminal={'SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN'}
        with app._control_lock:
            for run in app.missions.views():
                if run['target']==owner.target and run['state'] not in terminal:
                    app.missions.cancel(run['id'])
            for action in app.runtime.views():
                if action['target']==owner.target and (action['state'] not in terminal or
                    action.get('safety') and action['safety'].get('continuation_allowed')):
                    app.runtime.cancel(action['id'])
        # The application scheduler remains responsible for the original exit
        # barriers. Driver shutdown subsequently handles unresolved effects.
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            with app._control_lock:
                active=[r for r in app.runtime.views() if r['target']==owner.target and r['state'] not in terminal]
            if not active:
                break
            time.sleep(.05)

    def _run(self, identifier):
        record=self.records[identifier]
        stop=self.stops[identifier]
        directory=self.directory/identifier
        owner=None
        failed=None
        failure_domain=None
        try:
            if shutil.which('gz') is None:
                raise ValueError('BLOCKED: Gazebo is unavailable')
            checked=subprocess.run(['gz','sdf','-k',str(directory/'scenario.sdf')],
                capture_output=True,text=True,timeout=30)
            (directory/'sdf-check.log').write_text(checked.stdout+checked.stderr)
            if checked.returncode:
                record['levels']['L1']='FAIL'
                raise ValueError('SDF validation failed; see sdf-check.log')
            with self.lock:
                record['levels']['L1']='PASS'
                if stop.is_set():
                    raise InterruptedError('cancelled before startup')
                record['started_at']=stamp()
                self._transition(record,'STARTING')
            owner=LocalRuntime(self.root,directory,record['scene_id'],record['vehicle'],
                               seed=record['configuration']['seed'],
                               vehicles=record.get('vehicle_specifications',[]),
                               progress=lambda vehicle:self._queue_progress(identifier,vehicle),
                               geographic_reference=self.world_spawns.describe(record['scene_id'])['geographic_reference'],
                               extra_plugin_paths=() if self.registry.assets is None else self.registry.assets.plugin_paths,
                               **self.runtime_options)
            self.owners[identifier]=owner
            started=time.monotonic()
            owner.start(directory/'scenario.sdf',stop.is_set)
            deadline=started+self.startup_timeout
            while not stop.is_set() and time.monotonic()<deadline:
                try:
                    sample=owner.sample()
                    if sample['error_lines']:
                        raise RuntimeError('Gazebo reported a required resource/plugin error')
                    with self.lock:
                        self._project_vehicles(record,owner)
                        record['startup_progress']={v['id']:v['stages'] for v in record.get('vehicles',[])}
                        self._save(record)
                    for child in tuple(getattr(owner,'vehicles',{}).values()):
                        info=child.driver.info() if child.driver else {}
                        if info.get('fault'):raise FrameworkFailure('startup '+child.id+': '+str(info['fault']))
                    if sample['metrics']['sim_seconds'] is not None and sample['metrics']['sim_seconds']>0 and self._vehicle_ready(owner):
                        break
                except subprocess.TimeoutExpired:
                    pass
                stop.wait(.1)
            else:
                if stop.is_set():
                    raise InterruptedError('cancelled during startup')
                raise TimeoutError('Gazebo time or fresh signed vehicle health/pose/twist did not become ready before startup deadline')
            # Use the same app -> manager lock order as authenticated stop.
            # Cancellation and admission/publication are one serialized cut.
            with self.application._control_lock if self.application else nullcontext():
                with self.lock:
                    if stop.is_set():
                        raise InterruptedError('cancelled before Framework admission')
                    try:
                        self._attach(owner)
                    except Exception as exc:
                        raise FrameworkFailure('Framework target admission failed: '+str(exc)) from exc
                    record['target']=record['vehicle_id']=owner.target if owner.driver else None
                    self._project_vehicles(record,owner)
                    record['world_id']=owner.world
                    record['metrics']['load_seconds']=time.monotonic()-started
                    self._transition(record,'READY')
                    self._transition(record,'RUNNING')
            first_sim=sample['metrics']['sim_seconds']
            last_stats=last_progress=time.monotonic()
            latest_sim=first_sim
            while not stop.is_set():
                if record.get('operation',{}).get('state')=='RUNNING' or record.get('switch',{}).get('state')=='PREPARING':
                    last_stats=last_progress=time.monotonic()
                    stop.wait(.2)
                    continue
                if record['paused']:
                    owner.alive()
                    last_stats=last_progress=time.monotonic()
                    stop.wait(.25)
                    continue
                try:
                    sample=owner.sample()
                except subprocess.TimeoutExpired:
                    if time.monotonic()-last_stats>15:
                        raise TimeoutError('Gazebo statistics unavailable for 15 seconds')
                    if owner.driver and not owner.driver.info().get('connected'):
                        raise RuntimeError('owned Framework telemetry link lost')
                    stop.wait(.25)
                    continue
                now=time.monotonic()
                sim=sample['metrics']['sim_seconds']
                if sim is not None:
                    last_stats=now
                    if sim!=latest_sim:
                        last_progress=now
                        latest_sim=sim
                if now-last_stats>15:
                    raise TimeoutError('Gazebo statistics missing for 15 seconds')
                if now-last_progress>30:
                    raise TimeoutError('Gazebo simulation time stalled for 30 seconds')
                sample['estimated_vehicle']=None
                sample['ground_truth']=owner.truth()
                sample['software_link']=owner.link.diagnostics() if owner.link else None
                driver_fault=None
                if owner.driver:
                    info,world=owner.driver.read_view()
                    sample['vehicle_status']=info
                    sample['estimated_vehicle']=None if world is None else to_json_value(world.vehicle)
                    if info.get('fault') or not info.get('connected'):
                        driver_fault='Framework vehicle health failed: '+str(info.get('fault') or 'owned vehicle link disconnected')
                    elif not self._vehicle_ready(owner):
                        driver_fault='Framework vehicle state expired or is no longer VALID'
                related=self._world_related(owner)
                sample['actions']=[{key:item.get(key) for key in ('id','name','state')} for item in related['actions']]
                sample['missions']=[{key:item.get(key) for key in ('id','name','state')} for item in related['missions']]
                with self.lock:
                    if sample['error_lines']:
                        record['levels']['L2']='FAIL'
                        raise RuntimeError('Gazebo required resource/plugin errors; inspect gazebo.log')
                    sim=sample['metrics']['sim_seconds']
                    if sim is not None and sim>first_sim:
                        record['levels']['L2']='PASS'
                    self._project_vehicles(record,owner)
                    record['metrics'].update(sample['metrics'])
                    record.update(related)
                    if owner.driver:
                        record['vehicle_status']=sample['vehicle_status']
                    record['samples'].append(self._history_sample(sample))
                    record['samples']=record['samples'][-512:]
                    self._sync_tests(record)
                    self._save(record)
                with (directory/'samples.jsonl').open('a') as output:
                    output.write(json.dumps(sample,ensure_ascii=False,allow_nan=False)+'\n')
                if not self._vehicle_ready(owner):
                    driver_fault=driver_fault or 'one or more vehicle states expired or are no longer VALID'
                if driver_fault and not (record.get('operation',{}).get('state')=='RUNNING' or record.get('switch',{}).get('state')=='PREPARING'):
                    raise FrameworkFailure(driver_fault)
                stop.wait(1)
        except InterruptedError:
            pass
        except Exception as exc:
            failed=type(exc).__name__+': '+str(exc)
            failure_domain='framework' if isinstance(exc,FrameworkFailure) else 'simulation'
        finally:
            persistence_errors=[]
            try:
                with self.lock:
                    if record.get('persistence_errors'):
                        failed='; '.join(filter(None,(failed,record.get('error'))))
                        failure_domain='persistence' if not failure_domain else failure_domain+'+persistence'
                    record['error']=failed
                    self._transition(record,'STOPPING')
            except Exception as exc:
                persistence_errors.append(('STOPPING',exc))
            cleanup_errors=[]
            try:
                operation=self.operation_threads.get(identifier)
                if operation and record.get('operation',{}).get('state')=='RUNNING':operation.join(self.startup_timeout+40)
                if owner:
                    cleanup_errors=self._cleanup_owner(identifier,owner)
                    # Post-cleanup projections are diagnostics, not prerequisites
                    # for shutting down the independently owned runtime.
                    try:
                        self._sync_tests(record)
                        record.update(self._world_related(owner))
                    except Exception as exc:
                        cleanup_errors.append('exit projection: '+type(exc).__name__+': '+str(exc))
                    self._project_vehicles(record,owner)
                    if owner.driver:
                        record['vehicle_stop_status']='UNCONFIRMED: simulation processes retired; physical stop is not inferred'
                    if hasattr(owner,'vehicles'):
                        for child in tuple(owner.vehicles.values()):self._detach(child)
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__+': '+str(exc))
            record['cleanup']='FAILED' if cleanup_errors else 'COMPLETE'
            if not owner or identifier in self._owners_closed:
                lease=self._asset_leases.pop(identifier,None)
                if lease:lease.close()
            if cleanup_errors:
                failed=(failed+'; ' if failed else '')+'cleanup: '+'; '.join(cleanup_errors)
                failure_domain='cleanup' if failure_domain is None else failure_domain+'+cleanup'
            with self.lock:
                record['error']=failed
                record['failure_domain']=failure_domain
                # STOPPING failure is retained before choosing the terminal
                # state, while cleanup above has already run independently.
                for stage,exc in persistence_errors:
                    self._persistence_failed(record,stage,exc)
                failed=record['error']
                failure_domain=record['failure_domain']
                if failed:
                    if 'BLOCKED:' in failed and record['levels']['L1']=='NOT_TESTED':
                        record['levels']['L1']='BLOCKED'
                    if record['levels']['L2']=='NOT_TESTED' and failure_domain!='framework':
                        record['levels']['L2']='BLOCKED' if 'BLOCKED:' in failed else 'FAIL'
                    elif record['levels']['L2']=='PASS' and failure_domain!='framework':
                        record['levels']['L2']='FAIL'
                state='FAILED' if failed else 'CANCELLED' if record.get('cancelled_during_start') else 'FINISHED'
                try:
                    self._transition(record,state,failed)
                except Exception as exc:
                    self._persistence_failed(record,'terminal '+state,exc)

    @staticmethod
    def _history_sample(sample):
        # Persist full raw cuts in JSONL; the bounded in-memory/UI timeline
        # retains motion/health evidence without duplicating every telemetry
        # field and immutable vehicle definition on every sample. Large JSON
        # walks otherwise hold Python's GIL across strict Driver deadlines.
        def estimate(value):
            return None if value is None else {k:v for k,v in value.items() if k!='telemetry'}
        result={k:v for k,v in sample.items() if k not in ('vehicles','estimated_vehicle','vehicle_status','stats_raw')}
        result['estimated_vehicle']=estimate(sample.get('estimated_vehicle'))
        result['vehicles']=[]
        for vehicle in sample.get('vehicles',[]):
            item={k:vehicle.get(k) for k in ('id','target','kind','state','ground_truth','stages')}
            item['estimated_vehicle']=estimate(vehicle.get('estimated_vehicle'))
            info=vehicle.get('vehicle_status',{})
            item['vehicle_status']={k:info.get(k) for k in ('connected','session_id','fault','system_send','action_send')}
            result['vehicles'].append(item)
        return result

    def _sync_tests(self, record):
        if not self.application:
            return
        for item in record['tests']:
            try:
                action=self.application.runtime.view(item['action_id'])
                item['action']=action
            except (KeyError, ValueError):
                pass

    def _vehicle_ready(self, owner):
        if hasattr(owner,'vehicles'):
            with owner._state_lock:
                return all(self._vehicle_ready(child) for child in tuple(owner.vehicles.values()))
        if hasattr(owner,'stages') and (not owner.stages['plugin_connected'] or owner.owner.truth(owner.id) is None):return False
        if owner.driver is None:
            return not hasattr(owner,'stages')
        info,world=owner.driver.read_view()
        if not info.get('connected') or not info.get('owned_simulation') or world is None or world.vehicle is None:
            return False
        state=world.vehicle
        if state.health.quality.value!='VALID' or state.reported_pose is None or state.reported_twist is None:
            return False
        try:
            now=owner.driver.clock()
            return all(0<=now.elapsed_ns_since(point)<=3_000_000_000 for point in (
                state.published_at,state.reported_pose.captured_at,state.reported_twist.captured_at))
        except ValueError:
            return False

    def _related(self, target, *, bounded=True):
        if not self.application:
            return dict(actions=[],missions=[])
        app=self.application
        with app._control_lock:
            actions=[deepcopy(item) for item in app.runtime.views() if item.get('target')==target]
            missions=[deepcopy(item) for item in app.missions.views() if item.get('target')==target]
        if bounded:actions,missions=actions[-64:],missions[-64:]
        for item in actions:
            for key,limit in (('history',16),('feedback',8),('command_results',16)):
                if isinstance(item.get(key),list):item[key]=item[key][-limit:]
        return dict(actions=actions,missions=missions)

    def _world_related(self,owner):
        if not hasattr(owner,'vehicles'):return self._related(owner.target)
        result=dict(actions=[],missions=[])
        targets={child.target for child in tuple(owner.vehicles.values())}|{item['target'] for item in owner.retired}
        for target in sorted(targets):
            related=self._related(target)
            for key in result:result[key].extend(related[key])
        return result

    def stop(self, identifier):
        with self.lock:
            record=self._get(identifier)
            if record['state'] in TERMINAL:
                return deepcopy(record)
            if record['state']=='CREATED':
                record['cleanup']='COMPLETE'
                lease=self._asset_leases.pop(identifier,None)
                if lease:lease.close()
                try:self._transition(record,'CANCELLED')
                except Exception as exc:self._persistence_failed(record,'cancel before startup',exc)
                return deepcopy(record)
            record['cancelled_during_start']=record['state'] in ('PREPARING','STARTING')
            owner=self.owners.get(identifier)
            if owner and hasattr(owner,'vehicles'):self._retire(record,tuple(owner.vehicles.values()))
            self.stops[identifier].set()
            try:self._transition(record,'STOPPING')
            except Exception as exc:self._persistence_failed(record,'stop request',exc)
            return deepcopy(record)

    def wait_ready(self, identifier, timeout=130):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            with self.lock:
                record=deepcopy(self._get(identifier))
            if record['state'] in ('READY','RUNNING'):
                return record
            if record['state'] in TERMINAL:
                raise RuntimeError(record['error'] or record['state'])
            time.sleep(.05)
        raise TimeoutError('simulation manager readiness wait timed out')

    def sample(self, identifier):
        with self.lock:
            self._drain_progress(self._get(identifier))
            record=deepcopy(self._get(identifier))
        return record

    def handle(self, operation, payload):
        if operation=='simulation.vehicles':
            fields(payload,())
            return self.vehicle_registry.list_vehicles()
        if operation=='simulation.add_vehicle':
            fields(payload,('id','vehicle'),('id','vehicle'))
            return self._vehicle_operation('add',payload)
        if operation=='simulation.remove_vehicle':
            fields(payload,('id','vehicle_id'),('id','vehicle_id'))
            return self._vehicle_operation('remove',payload)
        if operation=='simulation.switch':
            fields(payload,('id','scene_id','seed','parameters','spawns'),('id','scene_id'))
            return self._switch(payload)
        if operation=='simulation.assets':
            fields(payload,())
            return [] if self.registry.assets is None else self.registry.assets.list_assets()
        if operation in ('simulation.install','simulation.uninstall','simulation.asset_status'):
            fields(payload,('asset_id',),('asset_id',))
            if self.registry.assets is None:
                raise ValueError('locked asset catalog is unavailable')
            asset_id=payload['asset_id']
            if type(asset_id) is not str:
                raise ValueError('registered asset identifier required')
            if operation=='simulation.asset_status':
                return dict(**self.registry.assets.status(asset_id),job=deepcopy(self.asset_jobs.get(asset_id)))
            with self.lock:
                if self.closed:
                    raise ValueError('simulation service is closed')
                if any(item['scene_id'].startswith(('U_','H_')) and item['state'] not in TERMINAL
                       for item in self.records.values()):
                    raise ValueError('asset is reserved by an unfinished scene session')
                if self.asset_jobs.get(asset_id,{}).get('state') in ('INSTALLING','UNINSTALLING'):
                    raise ValueError('asset operation is already running')
                if sum(thread.is_alive() for thread in self.asset_threads.values())>=2:
                    raise ValueError('asset operation concurrency budget exhausted')
                self.registry.assets.status(asset_id)  # validate trusted id before dispatch
                job=dict(asset_id=asset_id,id='asset-'+uuid4().hex,
                    state='INSTALLING' if operation=='simulation.install' else 'UNINSTALLING',
                    started_at=stamp(),ended_at=None,error=None)
                self.asset_jobs[asset_id]=job
                worker=Thread(target=self._asset_operation,args=(asset_id,operation),
                    name='asset-'+asset_id,daemon=True)
                self.asset_threads[asset_id]=worker
                worker.start()
                return deepcopy(job)
        if operation=='simulation.catalog':
            fields(payload,())
            return self.catalog()
        if operation=='simulation.sessions':
            fields(payload,())
            with self.lock:
                result=[]
                for value in self.records.values():
                    self._drain_progress(value)
                    compact=deepcopy({key:item for key,item in value.items() if key!='samples'})
                    compact['samples']=deepcopy(value['samples'][-1:])
                    compact['last_sample']=deepcopy(value['samples'][-1] if value['samples'] else None)
                    result.append(compact)
                return result
        if operation=='simulation.create':
            return self.create(payload)
        if operation=='simulation.logs':
            fields(payload,('id','offset','limit','stream','vehicle_id'),('id',))
            record=self._get(payload['id'])
            stream=payload.get('stream','gazebo')
            if stream not in ('gazebo','sitl','sdf-check'):
                raise ValueError('registered log stream required')
            offset,limit=payload.get('offset',0),payload.get('limit',32768)
            if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=65536:
                raise ValueError('bounded log offset/limit required')
            child=self._selected_vehicle(record,payload.get('vehicle_id'),required=False)
            path=self.directory/record['id']/(child['logs']['sitl'] if stream=='sitl' and child else stream+'.log')
            data=b''
            if path.is_file():
                with path.open('rb') as source:
                    source.seek(offset);data=source.read(limit)
            return dict(id=record['id'],stream=stream,offset=offset,next_offset=offset+len(data),
                        text=data.decode('utf-8',errors='replace'))
        if operation=='simulation.test':
            fields(payload,('id','name','parameters','allow_send','timeout_s','vehicle_id'),('id',))
            if payload.get('name','GetVehicleState')!='GetVehicleState' or payload.get('parameters',{})!={} or payload.get('allow_send',False) is not False:
                raise ValueError('simulation test only admits the read-only GetVehicleState query; use the existing control/Mission authorization for movement')
            record=self._get(payload['id'])
            if not self.application or not record['target'] or record['state']!='RUNNING' or record['paused']:
                raise ValueError('running owned Framework vehicle session required')
            child=self._selected_vehicle(record,payload.get('vehicle_id'),required=False)
            request=dict(name=payload.get('name','GetVehicleState'),target=child['target'] if child else record['target'],
                parameters=payload.get('parameters',{}),allow_send=payload.get('allow_send',False),
                timeout_s=payload.get('timeout_s',30))
            action=self.application.handle('run',request)
            with self.lock:
                record['tests'].append(dict(action_id=action['id'],requested_at=stamp(),action=action))
                self._save(record)
            return action
        if operation=='simulation.fault':
            fields(payload,('id','settings','vehicle_id'),('id','settings'))
            record=self._get(payload['id'])
            owner=self.owners.get(record['id'])
            child=self._selected_vehicle(record,payload.get('vehicle_id'),required=False)
            if child and owner:owner=owner.vehicles.get(child['id'])
            if record['state']!='RUNNING' or not owner or not owner.link:
                raise ValueError('live owned Framework software receive link required')
            owner.link.configure(payload['settings'])
            with self.lock:
                item=dict(at=stamp(),settings=asdict(owner.link.settings),
                    applied_to='Framework TCP receive stream / pre-write timeout; not SITL EKF sensors')
                record['faults'].append(item)
                self._save(record)
            return item
        fields(payload,('id',),('id',))
        identifier=payload['id']
        if operation=='simulation.start':
            return self.start(identifier)
        if operation=='simulation.stop':
            return self.stop(identifier)
        if operation=='simulation.report':
            with self.lock:
                record=self._get(identifier)
                self._drain_progress(record)
                self._sync_tests(record)
                return deepcopy(record)
        if operation in ('simulation.pause','simulation.resume','simulation.reset'):
            with self.lock:
                record=self._get(identifier)
                if record['state']!='RUNNING':
                    raise ValueError('running session required')
                if record.get('vehicles') or record['vehicle']!='none':
                    raise ValueError('pause/reset of a live vehicle clock is fenced; stop and create a fresh SITL epoch')
                owner=self.owners[identifier]
                owner.control(operation.split('.')[1])
                record['paused']=operation=='simulation.pause'
                record['history'].append(dict(state=record['state'],at=stamp(),reason=operation))
                self._save(record)
                return deepcopy(record)
        raise ValueError('unsupported simulation operation')

    def _asset_operation(self, asset_id, operation):
        job=self.asset_jobs[asset_id]
        try:
            if operation=='simulation.install':
                result=self.registry.assets.install(asset_id,cancelled=self.asset_stop.is_set)
            else:
                result=self.registry.assets.uninstall(asset_id)
            with self.lock:
                job.update(state='SUCCEEDED',result=result,ended_at=stamp())
        except Exception as exc:
            with self.lock:
                job.update(state='CANCELLED' if isinstance(exc,InterruptedError) else 'FAILED',
                           error=type(exc).__name__+': '+str(exc),ended_at=stamp())

    def close(self):
        with self.lock:
            self.closed=True
            self.asset_stop.set()
            identifiers=[key for key,value in self.records.items() if value['state'] not in TERMINAL]
        errors=[]
        for identifier in identifiers:
            try:self.stop(identifier)
            except Exception as exc:
                errors.append(identifier+': stop: '+type(exc).__name__)
                # Signal first even if a future stop implementation or report
                # callback fails, then keep cleaning every remaining session.
                event=self.stops.get(identifier)
                if event:event.set()
        for identifier,thread in tuple(self.threads.items()):
            try:
                thread.join(self.startup_timeout+40)
                if thread.is_alive():errors.append(identifier)
            except Exception as exc:errors.append(identifier+': join: '+type(exc).__name__)
        # A failed worker cleanup remains retryable from its live Python owner;
        # no PID or persisted process record is adopted for this fallback.
        for identifier,owner in tuple(self.owners.items()):
            thread=self.threads.get(identifier)
            if identifier in self._owners_closed or thread is not None and thread.is_alive():
                continue
            cleanup_errors=self._cleanup_owner(identifier,owner)
            record=self.records[identifier]
            with self.lock:
                record['cleanup']='FAILED' if cleanup_errors else 'COMPLETE'
                if cleanup_errors:errors.extend(identifier+': '+error for error in cleanup_errors)
                try:self._save(record)
                except Exception as exc:self._persistence_failed(record,'close fallback',exc)
        for identifier,thread in tuple(self.operation_threads.items()):
            thread.join(self.startup_timeout+40)
            if thread.is_alive():errors.append('operation:'+identifier)
        for identifier,thread in tuple(self.asset_threads.items()):
            thread.join(40)
            if thread.is_alive():
                errors.append('asset:'+identifier)
        for record in tuple(self.records.values()):
            if record.get('persistence_errors'):
                with self.lock:
                    try:self._save(record)
                    except Exception as exc:
                        self._persistence_failed(record,'close report retry',exc)
                        errors.append(record['id']+': report persistence')
        for identifier,lease in tuple(self._asset_leases.items()):
            if identifier not in self.owners or identifier in self._owners_closed:
                lease.close()
                self._asset_leases.pop(identifier,None)
        if (self._directory_lock is not None and
                not any(thread.is_alive() for thread in (*self.threads.values(),*self.asset_threads.values())) and
                all(identifier in self._owners_closed for identifier in self.owners)):
            self._directory_lock.close()
            self._directory_lock=None
        if errors:
            raise RuntimeError('simulation cleanup threads did not finish: '+','.join(errors))

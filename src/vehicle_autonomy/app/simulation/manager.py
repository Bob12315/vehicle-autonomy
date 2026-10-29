"""Structured simulation use cases, process ownership and honest evidence levels."""
from copy import deepcopy
from contextlib import nullcontext
from dataclasses import asdict
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from threading import Event, RLock, Thread
import time
from uuid import uuid4

from vehicle_autonomy._resources import resource_root as default_root
from vehicle_autonomy.contracts.core.serialization import to_json_value
from .catalog import SceneRegistry
from .runtime import LocalRuntime, stamp


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
        representative={'R01':'rover','C01':'copter','F01':'plane'}
        for entry in self.registry.list_scenes():
            item=deepcopy(entry)
            ready=item.get('ready',True)
            support={'none':dict(available=shutil.which('gz') is not None and ready,
                               reason='仅加载真实 Gazebo 场景，不连接飞控' if ready else
                               '场景入口或锁定依赖未安装完整，先安装资源并检查缺失项')}
            for kind in ('rover','copter','plane','vtol'):
                compatible=representative.get(item['id'])==kind
                reason=('复用受控本机 SITL 模型；须等待实际初始化，默认 SEND 关闭' if compatible
                        else '尚无该场景/机型的受控启动适配；不能由候选车型推断已验收')
                if kind=='vtol':
                    reason='未配置经过验证的 QuadPlane 模型和专属控制 profile'
                support[kind]=dict(available=compatible and shutil.which('gz') is not None,reason=reason)
            item['vehicle_support']=support
            item['launchable_vehicles']=[k for k,v in support.items() if v['available']]
            result.append(item)
        return result

    def create(self, payload):
        fields(payload,('scene_id','vehicle','seed','parameters'),('scene_id',))
        scene_id=payload['scene_id']
        scene=self.registry.get(scene_id)
        vehicle=payload.get('vehicle','none')
        if type(vehicle) is not str or vehicle not in ('none','rover','copter','plane','vtol'):
            raise ValueError('unsupported simulation vehicle')
        if vehicle!='none' and {'R01':'rover','C01':'copter','F01':'plane'}.get(scene_id)!=vehicle:
            raise ValueError('BLOCKED: this scene/vehicle has no qualified local bootstrap')
        seed=payload.get('seed',0)
        if type(seed) is not int or not 0<=seed<2**32:
            raise ValueError('seed must be an integer within 0..4294967295')
        parameters=deepcopy(payload.get('parameters',{}))
        if type(parameters) is not dict:
            raise ValueError('scenario parameters must be an object')
        parameters=self.registry.validate(scene_id,seed=seed,parameters=parameters)
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
                vehicle_id=None,target=None,state='CREATED',paused=False,
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
            self._transition(record,'PREPARING')
            worker=Thread(target=self._run,args=(identifier,),name='simulation-'+identifier,daemon=True)
            self.threads[identifier]=worker
            worker.start()
            return deepcopy(record)

    def _attach(self, owner):
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
                    record['world_id']=owner.world
                    record['metrics']['load_seconds']=time.monotonic()-started
                    self._transition(record,'READY')
                    self._transition(record,'RUNNING')
            first_sim=sample['metrics']['sim_seconds']
            last_stats=last_progress=time.monotonic()
            latest_sim=first_sim
            while not stop.is_set():
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
                driver_fault=None
                if owner.driver:
                    info,world=owner.driver.read_view()
                    sample['vehicle_status']=info
                    sample['estimated_vehicle']=None if world is None else to_json_value(world.vehicle)
                    if info.get('fault') or not info.get('connected'):
                        driver_fault='Framework vehicle health failed: '+str(info.get('fault') or 'owned vehicle link disconnected')
                related=self._related(owner.target)
                sample['actions']=[{key:item.get(key) for key in ('id','name','state')} for item in related['actions']]
                sample['missions']=[{key:item.get(key) for key in ('id','name','state')} for item in related['missions']]
                with self.lock:
                    if sample['error_lines']:
                        record['levels']['L2']='FAIL'
                        raise RuntimeError('Gazebo required resource/plugin errors; inspect gazebo.log')
                    sim=sample['metrics']['sim_seconds']
                    if sim is not None and sim>first_sim:
                        record['levels']['L2']='PASS'
                    record['metrics'].update(sample['metrics'])
                    record.update(related)
                    if owner.driver:
                        record['vehicle_status']=sample['vehicle_status']
                    record['samples'].append(sample)
                    record['samples']=record['samples'][-512:]
                    self._sync_tests(record)
                    self._save(record)
                with (directory/'samples.jsonl').open('a') as output:
                    output.write(json.dumps(sample,ensure_ascii=False,allow_nan=False)+'\n')
                if driver_fault:
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
                if owner:
                    cleanup_errors=self._cleanup_owner(identifier,owner)
                    # Post-cleanup projections are diagnostics, not prerequisites
                    # for shutting down the independently owned runtime.
                    try:
                        self._sync_tests(record)
                        record.update(self._related(owner.target))
                    except Exception as exc:
                        cleanup_errors.append('exit projection: '+type(exc).__name__+': '+str(exc))
                    if owner.driver:
                        record['vehicle_stop_status']='UNCONFIRMED: simulation processes retired; physical stop is not inferred'
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
        if owner.driver is None:
            return True
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

    def _related(self, target):
        if not self.application:
            return dict(actions=[],missions=[])
        app=self.application
        with app._control_lock:
            actions=[deepcopy(item) for item in app.runtime.views() if item.get('target')==target][-64:]
            missions=[deepcopy(item) for item in app.missions.views() if item.get('target')==target][-64:]
        for item in actions:
            for key,limit in (('history',16),('feedback',8),('command_results',16)):
                if isinstance(item.get(key),list):item[key]=item[key][-limit:]
        return dict(actions=actions,missions=missions)

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
            record=deepcopy(self._get(identifier))
        return record

    def handle(self, operation, payload):
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
                    compact=deepcopy({key:item for key,item in value.items() if key!='samples'})
                    compact['samples']=deepcopy(value['samples'][-1:])
                    compact['last_sample']=deepcopy(value['samples'][-1] if value['samples'] else None)
                    result.append(compact)
                return result
        if operation=='simulation.create':
            return self.create(payload)
        if operation=='simulation.logs':
            fields(payload,('id','offset','limit','stream'),('id',))
            record=self._get(payload['id'])
            stream=payload.get('stream','gazebo')
            if stream not in ('gazebo','sitl','sdf-check'):
                raise ValueError('registered log stream required')
            offset,limit=payload.get('offset',0),payload.get('limit',32768)
            if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=65536:
                raise ValueError('bounded log offset/limit required')
            path=self.directory/record['id']/(stream+'.log')
            data=b''
            if path.is_file():
                with path.open('rb') as source:
                    source.seek(offset);data=source.read(limit)
            return dict(id=record['id'],stream=stream,offset=offset,next_offset=offset+len(data),
                        text=data.decode('utf-8',errors='replace'))
        if operation=='simulation.test':
            fields(payload,('id','name','parameters','allow_send','timeout_s'),('id',))
            if payload.get('name','GetVehicleState')!='GetVehicleState' or payload.get('parameters',{})!={} or payload.get('allow_send',False) is not False:
                raise ValueError('simulation test only admits the read-only GetVehicleState query; use the existing control/Mission authorization for movement')
            record=self._get(payload['id'])
            if not self.application or not record['target'] or record['state']!='RUNNING' or record['paused']:
                raise ValueError('running owned Framework vehicle session required')
            request=dict(name=payload.get('name','GetVehicleState'),target=record['target'],
                parameters=payload.get('parameters',{}),allow_send=payload.get('allow_send',False),
                timeout_s=payload.get('timeout_s',30))
            action=self.application.handle('run',request)
            with self.lock:
                record['tests'].append(dict(action_id=action['id'],requested_at=stamp(),action=action))
                self._save(record)
            return action
        if operation=='simulation.fault':
            fields(payload,('id','settings'),('id','settings'))
            record=self._get(payload['id'])
            owner=self.owners.get(record['id'])
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
                self._sync_tests(record)
                return deepcopy(record)
        if operation in ('simulation.pause','simulation.resume','simulation.reset'):
            with self.lock:
                record=self._get(identifier)
                if record['state']!='RUNNING':
                    raise ValueError('running session required')
                if record['vehicle']!='none':
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

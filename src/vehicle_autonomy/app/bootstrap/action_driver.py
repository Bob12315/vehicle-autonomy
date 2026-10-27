"""Per-vehicle owner thread around the existing safety-gated composition.

HTTP and Actions cannot touch its command port. All effects use Execution.
Blocking stop/recovery waits affect only this vehicle's owner thread.
"""
from concurrent.futures import Future
from dataclasses import replace
from queue import Empty,Queue
from threading import Event,RLock,Thread
import time

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.actions.catalog import capabilities
from vehicle_autonomy.actions.common.standard import ground,speed
from vehicle_autonomy.app.bootstrap.simulation_runtime import SimulationRuntime
from vehicle_autonomy.contracts.action import ActionContext,ActionSafety
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected
from vehicle_autonomy.contracts.core.geometry import Pose3,Quaternion,Vector3
from vehicle_autonomy.contracts.decision import EffectPhase,EffectResult
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect,ModeEffect,FixedWingTargetEffect,TakeoffEffect,LandEffect,StopMotionEffect,TwistTargetEffect
from vehicle_autonomy.world.environment.resources import Environment


class VehicleActionDriver:
    def __init__(self,target,profile,translator,ownership,*,allow_send=False,event_sink=None,transport_factory=None,source_time_sync=False,cycle_period_ns=None,native_input_fence=None):
        if type(allow_send) is not bool:raise TypeError('deployment SEND must be an explicit bool')
        if profile.kind!=ownership.kind or profile.port!=ownership.port or profile.host!='127.0.0.1':
            raise ValueError('profile must exactly match the explicit owned SITL endpoint')
        self.target=target;self.profile=profile;self.ownership=ownership;self.allow_send=allow_send
        self._cycle_period_ns=profile.period_ns if cycle_period_ns is None else cycle_period_ns
        if type(self._cycle_period_ns) is not int or not 0<self._cycle_period_ns<=profile.period_ns:raise ValueError('owner cadence may only be faster than the validated profile')
        if source_time_sync and self._cycle_period_ns>20_000_000:raise ValueError('clock queries need an explicit fast owner cadence')
        if native_input_fence is not None:
            from vehicle_autonomy.engine.navigation.write_fence import NativeNavigationWriteFence
            if not isinstance(native_input_fence,NativeNavigationWriteFence):raise TypeError('typed native navigation data fence required')
        self._native_input_fence=native_input_fence
        self.events=event_sink or (lambda e:None)
        if source_time_sync and ownership.manifest.get('phase5_clock_uart_baud')!={'SERIAL0_BAUD':115.}:raise ValueError('clock sync requires public owned SERIAL0 baud proof')
        self._runtime=SimulationRuntime(profile,translator=translator,receive_signing=ownership.receive_signing,source_time_sync=source_time_sync,time_sync_uart_baud=115200 if source_time_sync else None,
            event_sink=self._event,transport_factory=transport_factory,motion_guard=lambda command,state,now:self._ownership_reason() or (None if self._native_input_fence is None else self._native_input_fence.validate(command,state,now,self._runtime.world_snapshot())))
        if self._native_input_fence is not None:self._native_input_fence.bind_authority(self._runtime.authority)
        self.clock=self._runtime.clock
        self._queue=Queue(maxsize=128);self._lock=RLock();self._stop=Event();self._ready=Event()
        self._world=None;self._scope=None;self._effects={};self._results={};self._effect_sessions={};self._requested_scopes=set();self._cancelled=set();self._guards={};self._home=None
        self._info={};self._fault=None;self._recovery=None
        self._thread=Thread(target=self._run,name='action-owner-'+target,daemon=True);self._thread.start()
        if not self._ready.wait(5):raise TimeoutError('vehicle owner startup timed out')
        if self._fault:raise RuntimeError(self._fault)

    def _ownership_reason(self):
        try:self.ownership.assert_alive();return None
        except Exception:return 'owned_simulation_epoch_unavailable'

    def _event(self,event):
        if event.get('event')=='fixed_wing_recovery_requested':self._recovery=event.get('status')
        self.events(dict(event,target=self.target))

    def _publish(self):
        world=self._runtime.world_snapshot()
        with self._lock:
            self._world=world
            self._info=dict(target=self.target,kind=self.profile.kind,connected=self._runtime.connected,
                session_id=self._runtime.session_id,owned_simulation=self._ownership_reason() is None,
                system_send=self._runtime.authority.system_send,action_send=self._runtime.authority.action_send,
                deployment_send=self.allow_send,lease_active=bool(self._runtime.authority.lease is not None
                    and self._runtime.authority.lease.expires_at.elapsed_ns_since(self.clock())>0),
                scope=self._scope,fault=self._fault,capabilities=sorted(self.context().capabilities))
            for identifier,items in self._effects.items():
                self._results[identifier]=tuple(EffectResult(str(env.effect_id),identifier,
                    EffectPhase((status or {}).get('phase','REQUESTED')),(status or {}).get('command_id'),
                    self._effect_sessions.get(str(env.effect_id)),(status or {}).get('reason')) for env in items
                    for status in [self._runtime.effect_status(str(env.effect_id))])

    def _bind(self):
        if self.profile.kind!='plane':
            env=Environment.load(resource_root()/f'simulation/environments/{self.profile.kind}.toml').bind(self._runtime.world_epoch)
            self._runtime.set_environment(env.reference)

    def _run(self):
        try:
            self.ownership.assert_alive();self._runtime.connect();self._bind();self._publish();self._ready.set()
            while not self._stop.is_set():
                started=time.monotonic()
                self.ownership.assert_alive()
                # One bounded task, then a mandatory safety/telemetry cycle.
                try:future,function=self._queue.get_nowait()
                except Empty:pass
                else:
                    if future.set_running_or_notify_cancel():
                        try:future.set_result(function())
                        except Exception as exc:future.set_exception(exc)
                if self._runtime.connected:
                    result=self._runtime.cycle()
                    if result.fault:self._fault=result.fault
                self._publish()
                self._stop.wait(max(0,self._cycle_period_ns/1e9-(time.monotonic()-started)))
        except Exception as exc:
            self._fault='vehicle owner failed: '+type(exc).__name__;self._ready.set()
        finally:
            try:self._runtime.shutdown()
            except Exception:self._fault='shutdown outcome UNCONFIRMED'
            self._publish()
            while not self._queue.empty():
                future,_=self._queue.get_nowait()
                if not future.done():future.set_exception(RuntimeError('vehicle owner stopped'))

    def _task(self,function):
        f=Future()
        if not self._thread.is_alive() or self._stop.is_set():f.set_exception(RuntimeError('vehicle owner unavailable'))
        else:
            try:self._queue.put_nowait((f,function))
            except Exception:f.set_exception(RuntimeError('vehicle task budget exhausted'))
        return f

    def context(self):
        caps=capabilities(self.profile.kind)
        if 'RTL' not in self.profile.mode_ids:caps=caps-{'return_home','rtl'}
        return ActionContext(self.target,self.profile.kind,frozenset(caps),True,
            getattr(self,'_home',None),{'mode_ids':self.profile.mode_ids,
                'home_source':'signed local position at completed Arm; owned flat-world AP unlocked-home convention',
                'native_input_fence':None if getattr(self,'_native_input_fence',None) is None else self._native_input_fence.identity})
    def stream_ingress(self):
        return self._runtime.stream_ingress()

    def snapshot(self):
        with self._lock:return self._world
    def read_view(self):
        # One immutable published cut; no Mission/journal lock or vehicle I/O.
        with self._lock:return dict(self._info),self._world
    def info(self):
        with self._lock:return dict(self._info)
    def effect_results(self,identifier):
        with self._lock:return self._results.get(identifier,())

    def open_scope(self,identifier,*,allow_send,continuation_of,deadline):
        with self._lock:self._requested_scopes.add(identifier)
        def admit():
            if identifier in self._cancelled or deadline.elapsed_ns_since(self.clock())<=0:
                raise ActionAdmissionRejected('admission cancelled or expired')
            if not self.allow_send or not allow_send:raise ActionAdmissionRejected('explicit deployment and Action SEND required')
            try:self.ownership.assert_alive()
            except Exception:raise ActionAdmissionRejected('owned SITL proof is no longer live') from None
            if continuation_of:
                guard=self._guards.get(continuation_of)
                if not guard or not guard.continuation_allowed or self._scope!=continuation_of:
                    raise ActionAdmissionRejected('no successful native continuation reservation')
                if self.profile.kind!='plane':raise ActionAdmissionRejected('continuation only for confirmed fixed-wing flight')
                self._guards[continuation_of]=ActionSafety(False,False,'explicit native handoff in progress; flight UNCONFIRMED')
                self._recovery=None
                stops=self._runtime.end_run();self._scope=None
                if stops!={'fixed-wing-flight':'UNCONFIRMED'} or not self._recovery or self._recovery['phase']!='COMPLETED':
                    raise RuntimeError('native recovery unconfirmed; continuation forbidden')
                self._runtime.connect();self._bind()
                end=time.monotonic()+3
                while time.monotonic()<end:
                    started=time.monotonic()
                    self.ownership.assert_alive();self._runtime.cycle();world=self._runtime.world_snapshot()
                    if (world.vehicle and world.vehicle.health.quality.value=='VALID'
                            and world.vehicle.operation.native_mode=='ARDUPILOT_CUSTOM_12'
                            and world.vehicle.reported_pose and world.vehicle.reported_pose.value.position.z>=10
                            and world.vehicle.global_position is not None
                            and 0<=self.clock().elapsed_ns_since(world.vehicle.global_position.captured_at)<=self.profile.safety.max_snapshot_age_ns):break
                    time.sleep(max(0,self.profile.period_ns/1e9-(time.monotonic()-started)))
                else:raise RuntimeError('fresh read-only airborne LOITER evidence unavailable')
                if self._runtime.authority.system_send or self._runtime.authority.lease:raise RuntimeError('reconnect inherited authorization')
            elif self._scope is not None:raise ActionAdmissionRejected('previous physical scope still owns authority')
            if not continuation_of and getattr(self,'_home',None) is None:
                world=self._runtime.world_snapshot()
                if (not world or not world.vehicle or world.vehicle.operation.armed is not False
                        or world.vehicle.health.quality.value!='VALID' or world.vehicle.reported_pose is None
                        or world.vehicle.reported_twist is None or abs(world.vehicle.reported_pose.value.position.z)>1.5
                        or speed(world)>1):
                    raise ActionAdmissionRejected('new owner requires fresh disarmed ground; previous execution may be unresolved')
            if identifier in self._cancelled or deadline.elapsed_ns_since(self.clock())<=0:
                raise ActionAdmissionRejected('admission cancelled or expired after recovery')
            # Reconnection never grants authority: only this explicit new request.
            self._runtime.begin_run(allow_send=True,run_id=identifier,action_id=identifier)
            if continuation_of:self._guards.pop(continuation_of,None)
            self._scope=identifier;self._effects[identifier]=[];self._publish()
        return self._task(admit)

    def emit(self,identifier,envelope,*,cleanup):
        def dispatch():
            if self._scope!=identifier:raise RuntimeError('Action no longer owns the execution scope')
            if identifier in self._cancelled and not cleanup:raise RuntimeError('Action ingress already fenced')
            if cleanup:
                effect=envelope.effect
                zero=(isinstance(effect,TwistTargetEffect) and self.profile.kind!='plane' and all(v==0 for vector in
                    (effect.target_twist.linear,effect.target_twist.angular) for v in (vector.x,vector.y,vector.z)))
                recovery=(isinstance(effect,ModeEffect) and effect.native_mode=={'rover':'HOLD','copter':'LOITER','plane':'LOITER'}[self.profile.kind])
                if not (isinstance(effect,StopMotionEffect) or zero or recovery):
                    raise RuntimeError('exit ingress permits only stopping/recovery effects')
            result=self._runtime.dispatch_envelope(envelope)
            self._effect_sessions[str(envelope.effect_id)]=self._runtime.session_id
            # Publish one stable post-cycle cut. Exposing a transient ACCEPTED
            # replacement before its mandatory writer cycle would repeatedly
            # reset the existing Action's physical settling observation.
            self._effects[identifier].append(envelope)
            return result
        return self._task(dispatch)

    def begin_exit(self,identifier):
        with self._lock:self._cancelled.add(identifier)
        if identifier not in self._requested_scopes:return  # Query never occupies the vehicle task queue.
        def fence():
            if self._scope==identifier:self._runtime.cancel_pending_requests()
        self._task(fence)

    def finish_scope(self,identifier,*,succeeded):
        if identifier not in self._requested_scopes:
            future=Future();future.set_result(ActionSafety(True));return future
        def finish():
            if self._scope!=identifier:
                if identifier in self._effects:return self._guards.get(identifier,ActionSafety(False,False,'execution scope lost'))
                return ActionSafety(True)  # Read-only Actions never touch authority.
            self._publish();world=self._runtime.world_snapshot();items=self._effects.get(identifier,[])
            results=self._results.get(identifier,())
            complete=bool(results) and all(r.phase is EffectPhase.COMPLETED for r in results)
            if succeeded and complete and any(isinstance(e.effect,ArmEffect) for e in items):
                # AP resets an unlocked home on arming. No SetHome capability
                # is exposed by this composition. Never reuse launch origin
                # after a later Arm at a different location.
                p=world.vehicle.reported_pose.value.position
                self._home=Pose3(Vector3(p.x,p.y,p.z),Quaternion(0,0,0,1))
            native=any(isinstance(e.effect,(ModeEffect,FixedWingTargetEffect)) for e in items)
            if succeeded and self.profile.kind=='plane' and native and complete and world.vehicle.operation.armed and world.vehicle.reported_pose.value.position.z>=10:
                safety=ActionSafety(False,True,'confirmed native configuration; fixed-wing flight remains active',{'physical_stop':'UNCONFIRMED','session_id':self._runtime.session_id})
                self._guards[identifier]=safety;return safety
            stops=self._runtime.end_run();self._scope=None
            self._publish();world=self._runtime.world_snapshot()
            valid=bool(world and world.vehicle and world.vehicle.health.quality.value=='VALID' and
                0<=self.clock().elapsed_ns_since(world.vehicle.published_at)<=self.profile.safety.max_snapshot_age_ns)
            bad=any(r.phase in (EffectPhase.TRANSMITTED,EffectPhase.ACKNOWLEDGED,EffectPhase.UNKNOWN) for r in self._results.get(identifier,()))
            stopped=bool(stops) and all(v=='CONFIRMED' for v in stops.values())
            motion=any(isinstance(e.effect,(TakeoffEffect,LandEffect)) or isinstance(e.effect,ModeEffect) and e.effect.native_mode=='RTL' for e in items)
            proven=valid and not any(v!='CONFIRMED' for v in stops.values()) and (
                stopped or not stops and (succeeded or not motion and not bad))
            safety=ActionSafety(bool(proven),False,'execution exit confirmed' if proven else 'physical outcome UNCONFIRMED',{'stops':stops})
            self._guards[identifier]=safety;return safety
        return self._task(finish)

    def guard_status(self,identifier):
        with self._lock:return self._guards.get(identifier)
    def close(self):
        self._stop.set();self._thread.join(15)
        if self._thread.is_alive():raise TimeoutError('vehicle owner cleanup did not finish')
        self.ownership.close()

"""One standalone, device-independent scheduler for all four Action semantics.

Drivers are application-injected execution boundaries. They must truthfully
assess physical exit safety; a terminal Action never releases a hazardous claim.
The caller schedules tick under its own serialized loop, independently of HTTP.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field, replace
import math
from threading import RLock
from uuid import uuid4

from vehicle_autonomy.contracts.action import ActionKind, ActionSafety, ActionState, TERMINAL_ACTION_STATES
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected
from vehicle_autonomy.contracts.core.primitives import SchemaVersion
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.decision import ActionDecision, ActionOutcome, ExitDecision, ExitReason
from vehicle_autonomy.contracts.effects.payload import PayloadEffectEnvelope, ReleasePayloadEffect
from vehicle_autonomy.contracts.effects.vehicle import EffectEnvelope
from vehicle_autonomy.engine.action.resources import ActionResources
from vehicle_autonomy.engine.action.external_lifecycle import ExternalLifecycle
from vehicle_autonomy.engine.action.schema import validate_json


class _StatePending(ValueError):
    """A partial source cut, not evidence authorizing any new effect."""


@dataclass
class _Record:
    id: str
    target: str
    registration: object
    parameters: object
    created: TimePoint
    deadline_ns: int
    wait_deadline_ns: int
    allow_send: bool
    continuation_of: str | None
    state: ActionState = ActionState.CREATED
    instance: object = None
    opening: object = None
    closing: object = None
    opened: bool = False
    preflight_pending: bool = True
    last_valid_state: TimePoint | None = None
    requested_end: ActionState | None = None
    exit_started_ns: int | None = None
    exit_complete: bool = False
    exit_safety: ActionSafety | None = None
    error: str | None = None
    result: object = None
    safety: ActionSafety | None = None
    effects: list = field(default_factory=list)
    feedback: deque = field(default_factory=lambda:deque(maxlen=100))
    history: deque = field(default_factory=lambda:deque(maxlen=128))
    guard_stop: object = None
    driver_safety: ActionSafety | None = None
    provider_started: bool = False
    external: object = None


class ActionRuntime:
    def __init__(self,registry,drivers,*,clock,event_sink=None,max_instances=128,max_effects=2048):
        if type(max_instances) is not int or not 1<=max_instances<=4096:raise ValueError('bounded instance budget required')
        if type(max_effects) is not int or max_effects<=0:raise ValueError('bounded effect budget required')
        self.registry=registry;self.drivers=dict(drivers);self.clock=clock
        self.resources=ActionResources({k:d.resource_store for k,d in self.drivers.items() if hasattr(d,'resource_store')})
        self._records={};self._lock=RLock()
        self._event_sink=event_sink or (lambda event:None)
        self.max_instances=max_instances;self.max_effects=max_effects;self._last_now=None

    def _event(self,r,event,**fields):
        value=dict(event=event,action_id=r.id,target=r.target,at_ns=self.clock().monotonic_ns,**fields)
        r.history.append(value);self._event_sink(value)

    def _state(self,r,state):
        if r.state is not state:
            r.state=state;self._event(r,'action_state',state=state.value,error=r.error)

    def _fresh(self,r,world,now):
        s=r.registration.spec
        if world is None:raise ValueError('world snapshot unavailable')
        if s.required_state:
            if not 0<=now.elapsed_ns_since(world.published_at)<=s.max_snapshot_age_ns:raise ValueError('world snapshot stale or future')
            vehicle=world.vehicle
            if vehicle is None or vehicle.health.quality.value!='VALID':raise ValueError('fresh VALID vehicle required')
            stamps=[world.published_at]
            for name in s.required_state:
                if name=='vehicle':continue
                sample=getattr(vehicle,name,None)
                if sample is None:raise _StatePending(name)
                if not 0<=now.elapsed_ns_since(sample.captured_at)<=s.max_snapshot_age_ns:
                    raise ValueError('fresh state required: '+name)
                stamps.append(sample.captured_at)
            r.last_valid_state=min(stamps,key=lambda stamp:stamp.monotonic_ns)

    def _preflight(self,r):
        driver=self.drivers[r.target];s=r.registration.spec;ctx=driver.context()
        if s.vehicle_types and ctx.target_kind not in s.vehicle_types:raise ValueError('unsupported vehicle type')
        if not s.required_capabilities<=ctx.capabilities:raise ValueError('required Action capabilities unavailable')
        world=driver.snapshot();now=self.clock();self._fresh(r,world,now)
        check=getattr(r.registration.factory,'validate_context',None)
        if check:check(r.parameters,world,ctx)
        if r.continuation_of:
            old=self._records.get(r.continuation_of)
            if (not r.allow_send or old is None or old.target!=r.target or old.state is not ActionState.SUCCEEDED
                    or old.safety is None or not old.safety.continuation_allowed or old.guard_stop is not None):
                raise ValueError('explicit continuation requires a successful retained scope')
        r.preflight_pending=False;self._admit(r,now)

    def _waiting_state(self,r,reason):
        now=self.clock()
        stamp=r.last_valid_state or r.created
        if not 0<=now.elapsed_ns_since(stamp)<r.registration.spec.max_snapshot_age_ns:
            raise ValueError('required state unavailable beyond freshness bound')
        r.feedback.append(dict(at_ns=now.monotonic_ns,value={'waiting_for_state':str(reason)}))

    def submit(self,name,target,parameters=None,*,version=None,allow_send=False,timeout_s=None,
               wait_timeout_s=0,continuation_of=None):
        with self._lock:
            if len(self._records)>=self.max_instances:raise ValueError('Action record budget exhausted; no unsafe eviction')
            if target not in self.drivers:raise ValueError('unknown Action target')
            if type(allow_send) is not bool:raise TypeError('explicit SEND bool required')
            entry=self.registry.resolve_typed(name,version);s=entry.spec;now=self.clock()
            ctx=self.drivers[target].context()
            metadata=self.registry.metadata(name,version,vehicle_kind=ctx.target_kind)
            if type(wait_timeout_s) not in (int,float) or not math.isfinite(wait_timeout_s) or not 0<=wait_timeout_s<=60:
                raise ValueError('resource wait must be 0..60 seconds')
            timeout=metadata['default_timeout_s'] if timeout_s is None else timeout_s
            if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=metadata['max_timeout_s']:
                raise ValueError('Action timeout outside declared limits')
            r=_Record('action:'+uuid4().hex,target,entry,None,now,now.monotonic_ns+int(timeout*1e9),
                now.monotonic_ns+int(wait_timeout_s*1e9),allow_send,continuation_of)
            self._records[r.id]=r;self._event(r,'action_created',name=s.name,version=s.version)
            self._state(r,ActionState.VALIDATING)
            try:
                r.parameters=self.registry.parameters(name,{} if parameters is None else parameters,s.version,vehicle_kind=ctx.target_kind)
                self._preflight(r)
            except _StatePending as exc:self._waiting_state(r,exc)
            except Exception as exc:
                r.error=f'{type(exc).__name__}: {exc}';self.resources.release(r.id,no_effects=True);self._state(r,ActionState.REJECTED)
            return self._view(r)

    def _admit(self,r,now):
        s=r.registration.spec
        store=getattr(r.registration.factory,'resource_store',None) or getattr(self.drivers[r.target],'resource_store',None)
        r.external=ExternalLifecycle(s,store,r.id,self.resources.runtime_id,
            lambda:r.provider_started and r.state in (ActionState.VALIDATING,ActionState.RUNNING)
                and self.clock().monotonic_ns<r.deadline_ns)
        if not self.resources.acquire(r.id,r.target,s.resources,continuation_of=r.continuation_of,
                persistent=s.kind is not ActionKind.QUERY,
                metadata={'action':s.name,'version':s.version,'kind':s.kind.value},external_store=store):
            if now.monotonic_ns>=r.wait_deadline_ns:
                r.error='resource conflict';self._state(r,ActionState.REJECTED)
            else:self._state(r,ActionState.WAITING_RESOURCE)
            return
        if s.kind is ActionKind.QUERY or not s.effect_types:
            r.opened=True
        else:
            deadline=TimePoint(r.deadline_ns,now.utc,now.clock_domain_id)
            r.opening=self.drivers[r.target].open_scope(r.id,allow_send=r.allow_send,continuation_of=r.continuation_of,deadline=deadline)

    def cancel(self,identifier):
        with self._lock:
            r=self._records[identifier]
            if r.state in TERMINAL_ACTION_STATES:
                if r.safety and r.safety.continuation_allowed and r.guard_stop is None:
                    r.safety=ActionSafety(False,False,'retained physical effects are being cancelled')
                    try:
                        self.drivers[r.target].begin_exit(r.id)
                        r.guard_stop=self.drivers[r.target].finish_scope(r.id,succeeded=False)
                    except Exception:
                        self.resources.retain(r.id,'retained physical exit failed; UNCONFIRMED')
                    self._event(r,'retained_guard_cancelled')
                return self._view(r)
            self._begin_exit(r,ActionState.CANCELLED,None)
            return self._view(r)

    def _begin_exit(self,r,outcome,error):
        if r.state is ActionState.CANCELLING:return
        if r.external is not None:r.external.seal()
        r.requested_end=outcome;r.error=error;r.exit_started_ns=self.clock().monotonic_ns
        if r.state is ActionState.WAITING_RESOURCE or not r.opened and r.opening is None:
            self.resources.release(r.id,no_effects=True);self._state(r,outcome);return
        try:self.drivers[r.target].begin_exit(r.id)
        except Exception as exc:
            r.requested_end=ActionState.UNKNOWN
            self._finish(r,ActionSafety(False,False,'exit ingress fence failed: '+type(exc).__name__))
            return
        self._state(r,ActionState.CANCELLING)

    def _emit(self,r,effects,now,*,cleanup):
        if not isinstance(effects,tuple) or any(type(e) not in r.registration.spec.effect_types for e in effects):
            raise TypeError('Action emitted undeclared effects')
        if r.registration.spec.kind is ActionKind.QUERY and effects:raise TypeError('Query cannot emit effects')
        if len(r.effects)+len(effects)>self.max_effects:raise ValueError('Action effect budget exhausted')
        driver=self.drivers[r.target]
        for effect in effects:
            # Cleanup has its own bounded window. The final writer still enforces
            # every Lease/TTL/session/generation condition using its own clock.
            limit=(r.exit_started_ns+r.registration.spec.exit_timeout_ns) if cleanup else r.deadline_ns
            ttl=(to_json_value(r.registration.spec.effect_ttl_overrides) or {}).get(type(effect).__name__,r.registration.spec.effect_ttl_ns)
            deadline=min(now.monotonic_ns+ttl,limit)
            if deadline<=now.monotonic_ns:raise ValueError('Action effect deadline expired')
            at=TimePoint(deadline,now.utc,now.clock_domain_id)
            kind=PayloadEffectEnvelope if isinstance(effect,ReleasePayloadEffect) else EffectEnvelope
            envelope=kind(SchemaVersion(1,0),r.id+':effect:'+str(len(r.effects)+1),r.id,r.id,now,at,effect)
            future=driver.emit(r.id,envelope,cleanup=cleanup)
            r.effects.append((envelope,future))
            self._event(r,'effect_requested',effect_id=str(envelope.effect_id),effect_type=type(effect).__name__,cleanup=cleanup)

    def _combined_safety(self,r,safety):
        if not isinstance(safety,ActionSafety):raise TypeError('driver must return a typed physical safety assessment')
        r.driver_safety=safety
        if r.external is not None:
            external=r.external.assess()
            if not external.release_safe:return external
        if r.exit_safety is not None and not r.exit_safety.release_safe:
            return ActionSafety(False,False,r.exit_safety.reason or 'Action external effects unconfirmed',r.exit_safety.evidence)
        return safety

    def _finish(self,r,safety):
        if r.external is not None:r.external.seal()
        safety=self._combined_safety(r,safety)
        r.safety=safety
        if safety.release_safe:self.resources.release(r.id,safety=safety)
        else:self.resources.retain(r.id,safety.reason or 'physical safety UNCONFIRMED')
        state=r.requested_end
        if not safety.release_safe and not (state is ActionState.SUCCEEDED and safety.continuation_allowed):
            state=ActionState.UNKNOWN
            r.error=r.error or safety.reason or 'physical outcome unconfirmed'
        self._state(r,state)

    def _tick(self,r,now):
        driver=self.drivers[r.target];s=r.registration.spec
        if r.state in TERMINAL_ACTION_STATES:
            if r.external is not None and s.external_lifecycle=='managed' and r.external.jobs and r.external.assess().release_safe:
                r.exit_safety=ActionSafety(True,False,'all registered independent jobs have trusted terminal results')
                if r.driver_safety is not None and r.safety is not None and not r.safety.release_safe:
                    r.safety=self._combined_safety(r,r.driver_safety)
                    if r.safety.release_safe:
                        self.resources.release(r.id,safety=r.safety);self._event(r,'external_jobs_reconciled')
            if r.exit_safety is not None and not r.exit_safety.release_safe:
                reconcile=getattr(r.instance,'reconcile_exit',None)
                if reconcile:
                    assessed=reconcile()
                    if assessed is not None:
                        if not isinstance(assessed,ActionSafety):raise TypeError('typed external reconciliation required')
                        if assessed.release_safe:
                            r.exit_safety=assessed
                            if r.driver_safety is not None:
                                r.safety=self._combined_safety(r,r.driver_safety)
                                if r.safety.release_safe:
                                    self.resources.release(r.id,safety=r.safety)
                                    self._event(r,'external_guard_reconciled')
            if r.guard_stop is not None and r.guard_stop.done():
                try:r.safety=self._combined_safety(r,r.guard_stop.result())
                except Exception as exc:r.safety=ActionSafety(False,False,f'guard exit failed: {type(exc).__name__}')
                r.guard_stop=None
                if r.safety.release_safe:self.resources.release(r.id,safety=r.safety)
                else:self.resources.retain(r.id,r.safety.reason or 'physical stop UNCONFIRMED')
            elif r.safety and not r.safety.release_safe:
                status=driver.guard_status(r.id)
                if status is not None:
                    if not isinstance(status,ActionSafety):raise TypeError('typed guard status required')
                    r.safety=self._combined_safety(r,status)
                    if r.safety.release_safe:self.resources.release(r.id,safety=r.safety);self._event(r,'physical_guard_reconciled')
                    else:self.resources.retain(r.id,r.safety.reason or 'physical outcome UNCONFIRMED')
            return
        if r.state is not ActionState.CANCELLING and now.monotonic_ns>=r.deadline_ns:
            self._begin_exit(r,ActionState.TIMED_OUT,'Action deadline exceeded')
        if r.state in TERMINAL_ACTION_STATES:return
        if r.state is ActionState.VALIDATING and r.preflight_pending:
            if now.elapsed_ns_since(r.created)>=s.max_snapshot_age_ns:
                r.error='state precondition wait expired';self._state(r,ActionState.REJECTED);return
            try:self._preflight(r)
            except _StatePending as exc:self._waiting_state(r,exc);return
            except Exception as exc:
                r.error=f'{type(exc).__name__}: {exc}';self._state(r,ActionState.REJECTED);return
        if r.state is ActionState.CANCELLING and now.monotonic_ns-r.exit_started_ns>=s.exit_timeout_ns:
            # A hung driver cannot freeze the global scheduler or release its
            # physical claim. The driver has already been told to close ingress.
            if s.kind is not ActionKind.QUERY and s.external_lifecycle!='typed_only' and (r.instance is not None or r.opening is not None):
                r.exit_safety=ActionSafety(False,False,'Action exit deadline; external/admission effects UNCONFIRMED')
            abandon=getattr(r.instance,'abandon',None)
            if abandon:
                try:abandon()
                except Exception:pass
            if r.closing is None:
                try:r.guard_stop=driver.finish_scope(r.id,succeeded=False)
                except Exception:pass
            else:r.guard_stop=r.closing
            self._finish(r,ActionSafety(False,False,'Action exit deadline exceeded'))
            return
        if r.state is ActionState.WAITING_RESOURCE:
            self._fresh(r,driver.snapshot(),self.clock())
            if now.monotonic_ns>=r.wait_deadline_ns:
                r.error='resource wait deadline exceeded';self._state(r,ActionState.TIMED_OUT)
            else:self._preflight(r)
            return
        if r.opening is not None:
            if not r.opening.done():return
            try:r.opening.result();r.opened=True
            except Exception as exc:
                r.error=f'admission failed: {type(exc).__name__}: {exc}'
                if isinstance(exc,ActionAdmissionRejected):
                    self.resources.release(r.id,no_effects=True)
                    self._state(r,r.requested_end if r.state is ActionState.CANCELLING else ActionState.REJECTED)
                else:
                    r.requested_end=ActionState.UNKNOWN
                    self._finish(r,ActionSafety(False,False,'admission outcome uncertain'))
                return
            finally:r.opening=None
            if r.continuation_of:
                self.resources.release(r.continuation_of,safety=ActionSafety(True,False,'explicit successful resource transfer'))
                old=self._records[r.continuation_of]
                old.safety=ActionSafety(True,False,'resource transferred under explicit new authorization',
                    {'successor':r.id,'physical_stop':'UNCONFIRMED'})
                self._event(old,'resource_transferred',successor=r.id)
        for _,future in r.effects:
            if future.done() and (future.cancelled() or future.exception() is not None):
                if r.state is not ActionState.CANCELLING:
                    self._begin_exit(r,ActionState.FAILED,'effect dispatch failed')
                break
        if r.state is ActionState.VALIDATING and r.opened:
            world=driver.snapshot();self._fresh(r,world,self.clock())
            factory=r.registration.factory
            self.resources.started(r.id);r.provider_started=True
            try:
                with r.external.callback():
                    r.instance=(factory.start_with_context(r.parameters,world,replace(driver.context(),external_jobs=r.external))
                                if hasattr(factory,'start_with_context') else factory.start(r.parameters,world))
            except Exception as exc:
                if not isinstance(exc,ActionAdmissionRejected) and s.kind is not ActionKind.QUERY and s.external_lifecycle!='typed_only':
                    r.exit_safety=ActionSafety(False,False,'provider admission raised; external side effects UNCONFIRMED')
                raise
            if not callable(getattr(r.instance,'tick',None)) or not callable(getattr(r.instance,'exit',None)):
                raise TypeError('Action factory returned no lifecycle instance')
            self._state(r,ActionState.RUNNING)
        if r.state is ActionState.RUNNING:
            describe=getattr(r.instance,'recovery_descriptor',None)
            if describe:self.resources.describe(r.id,describe())
            world=driver.snapshot();self._fresh(r,world,self.clock())
            results=driver.effect_results(r.id)
            with r.external.callback():
                decision=(r.instance.tick_with_results(world,results) if hasattr(r.instance,'tick_with_results') else r.instance.tick(world))
            if not isinstance(decision,ActionDecision):raise TypeError('typed Action decision required')
            if decision.outcome is not ActionOutcome.RUNNING and decision.effects:
                raise TypeError('terminal Action decision cannot start new effects')
            if decision.feedback is not None:r.feedback.append(dict(at_ns=now.monotonic_ns,value=to_json_value(decision.feedback)))
            now=self.clock()
            if now.monotonic_ns>=r.deadline_ns:
                self._begin_exit(r,ActionState.TIMED_OUT,'Action deadline exceeded during callback');return
            self._emit(r,decision.effects,now,cleanup=False)
            if decision.outcome is not ActionOutcome.RUNNING:
                if decision.outcome is ActionOutcome.SUCCEEDED:
                    if s.kind is ActionKind.CONTINUOUS:
                        self._begin_exit(r,ActionState.FAILED,'Continuous operation ended without cancellation')
                        return
                    value=to_json_value(decision.result)
                    if s.output_schema:validate_json(value,to_json_value(s.output_schema),'result')
                    r.result=value;self._begin_exit(r,ActionState.SUCCEEDED,None)
                else:self._begin_exit(r,ActionState.FAILED,decision.error)
        if r.state is ActionState.CANCELLING:
            if r.opening is not None:return
            if r.closing is not None:
                if r.closing.done():
                    try:self._finish(r,r.closing.result())
                    except Exception as exc:self._finish(r,ActionSafety(False,False,f'exit failed: {type(exc).__name__}'))
                return
            if not r.exit_complete and r.instance is not None:
                world=driver.snapshot()
                reason={ActionState.SUCCEEDED:ExitReason.SUCCEEDED,ActionState.CANCELLED:ExitReason.CANCELLED}.get(r.requested_end,ExitReason.FAILED)
                try:
                    results=driver.effect_results(r.id)
                    with r.external.callback():
                        decision=(r.instance.exit_with_results(world,reason,results) if hasattr(r.instance,'exit_with_results') else r.instance.exit(world,reason))
                    if not isinstance(decision,ExitDecision):raise TypeError('typed Action exit required')
                    self._emit(r,decision.effects,self.clock(),cleanup=True);r.exit_complete=decision.complete;r.exit_safety=decision.safety
                except Exception as exc:
                    r.error=f'Action exit failed: {type(exc).__name__}: {exc}';r.exit_complete=True
                    r.requested_end=ActionState.FAILED
                    if s.kind is not ActionKind.QUERY and s.external_lifecycle!='typed_only':
                        r.exit_safety=ActionSafety(False,False,'Action exit raised; side effects UNCONFIRMED')
            elif r.instance is None:r.exit_complete=True
            if r.exit_complete:
                r.closing=driver.finish_scope(r.id,succeeded=r.requested_end is ActionState.SUCCEEDED)

    def tick(self):
        with self._lock:
            now=self.clock()
            try:invalid=self._last_now is not None and now.elapsed_ns_since(self._last_now)<0
            except ValueError:invalid=True
            if invalid:
                for r in self._records.values():
                    if r.state not in TERMINAL_ACTION_STATES:self._begin_exit(r,ActionState.UNKNOWN,'Action clock regressed')
            self._last_now=now
            for r in tuple(self._records.values()):
                try:self._tick(r,self.clock())
                except _StatePending as exc:
                    try:self._waiting_state(r,exc)
                    except ValueError as expired:self._begin_exit(r,ActionState.FAILED,str(expired))
                except Exception as exc:
                    if r.state in TERMINAL_ACTION_STATES:
                        r.safety=ActionSafety(False,False,'physical guard query failed: '+type(exc).__name__)
                        self.resources.retain(r.id,r.safety.reason)
                    else:self._begin_exit(r,ActionState.FAILED,f'{type(exc).__name__}: {exc}')

    def _view(self,r):
        return deepcopy(dict(id=r.id,target=r.target,name=r.registration.spec.name,version=r.registration.spec.version,
            kind=r.registration.spec.kind.value,state=r.state.value,parameters=to_json_value(r.parameters),
            result=r.result,error=r.error,feedback=list(r.feedback),history=list(r.history),
            deadline_ns=r.deadline_ns,allow_send=r.allow_send,continuation_of=r.continuation_of,
            safety=None if r.safety is None else to_json_value(r.safety),
            effects=[dict(effect_id=str(e.effect_id),type=type(e.effect).__name__) for e,_ in r.effects],
            command_results=[to_json_value(x) for x in self.drivers[r.target].effect_results(r.id)]))

    def view(self,identifier):
        with self._lock:return self._view(self._records[identifier])

    def views(self):
        with self._lock:return [self._view(r) for r in self._records.values()]

    def resource_view(self):
        with self._lock:return self.resources.view()

    def reconcile_external(self,identifier,verify):
        """Trusted, bounded provider inspection; no force flag or re-submission.

        Deployment code invokes this outside normal Action execution. It may
        resolve an old process's reservation without resuming its Action.
        """
        if not callable(verify):raise TypeError('provider verifier required')
        with self._lock:
            r=self._records.get(identifier)
            if r is not None and (r.state not in TERMINAL_ACTION_STATES or r.driver_safety is None or not r.driver_safety.release_safe):
                return False
            assessments=[]
            def checked(record):
                result=verify(record);assessments.append(result);return result
            if not self.resources.reconcile(identifier,checked):return False
            if r is not None:
                r.external.attested=True
                r.exit_safety=assessments[-1]
                r.safety=self._combined_safety(r,r.driver_safety)
                self._event(r,'external_guard_reconciled',evidence=to_json_value(r.exit_safety.evidence))
            return True

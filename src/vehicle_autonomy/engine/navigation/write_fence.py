"""Additional native-navigation DATA fence; never grants vehicle authorization.

One vehicle has one admitted native scope. Execution/Authority still enforce
Lease, gates, session/generation and the immutable source deadline afterwards.
"""
from dataclasses import replace
from contextlib import contextmanager,nullcontext
from vehicle_autonomy.engine.control.control_authority import ControlAuthority
from threading import RLock
from uuid import uuid4
from vehicle_autonomy.engine.navigation.inputs import RoverNavigationInputs


class NativeNavigationWriteFence:
    def __init__(self):self.identity=uuid4().hex;self._lock=RLock();self._scope=None;self._inputs=None;self._closed=True;self._authority=None;self.rejected=0;self.last_rejection=None
    def bind_authority(self,authority):
        if not isinstance(authority,ControlAuthority):raise TypeError('existing typed vehicle authority required')
        with self._lock:
            if self._authority is not None and self._authority is not authority:raise ValueError('native fence belongs to another vehicle authority')
            if not self._closed:raise ValueError('bind before native source admission')
            self._authority=authority
    @contextmanager
    def _transaction(self):
        # Same order as the actual Writer: Authority -> data fence. Closing
        # linearizes with the bounded in-flight transport call, not beside it.
        with (self._authority.lock if self._authority else nullcontext()):
            with self._lock:yield
    def admit(self,scope,inputs):
        if not isinstance(scope,str) or not scope or not isinstance(inputs,RoverNavigationInputs):raise ValueError('bound native scope and typed inputs required')
        with self._transaction():
            if not self._closed:raise ValueError('another native source scope is still active')
            self._scope=scope;self._inputs=inputs;self._closed=False
    def close(self,scope):
        with self._transaction():
            if self._scope==scope:self._closed=True
    def validate(self,command,state,now,world):
        with self._transaction():
            if str(command.run_id)!=self._scope:return None
            if self._closed:return 'native_navigation_source_closed'
            try:self._inputs.validate(replace(world,vehicle=state),now)
            except (ValueError,TypeError,AttributeError) as exc:
                self.rejected+=1;self.last_rejection=dict(at_ns=now.monotonic_ns,reason=str(exc),world_published_ns=None if world is None else world.published_at.monotonic_ns,stream_freshness=[] if world is None else [dict(component_id=f.component_id,reason=f.reason,age_ns=f.age_ns) for f in world.freshness if f.component_id.startswith('stream:')])
                return 'native_navigation_current_evidence_invalid'
            return None

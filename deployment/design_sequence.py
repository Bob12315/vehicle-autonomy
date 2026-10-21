"""Finite Application mission sequence; every child uses the original execution chain."""
from copy import deepcopy
from uuid import uuid4

TERMINAL=('SUCCEEDED','FAILED','CANCELLED')


class DesignExecution:
    def __init__(self, design, context, now_ns):
        self.design,self.context=design,context
        self.task_id='design:'+uuid4().hex
        self.status='WAITING_BOUNDARY';self.error=None
        self.index=0;self.child_id=None;self.results=[]
        self.deadline_ns=now_ns+600_000_000_000
        self.pending=None;self.cleanup_deadline_ns=None
        self.stable_since=None;self.last_capture=None;self.samples=0
        self.stop_evidence='UNCONFIRMED'

    @property
    def active(self):return self.status not in TERMINAL

    def _reset_boundary(self):
        self.stable_since=None;self.last_capture=None;self.samples=0
        self.stop_evidence='UNCONFIRMED'

    def cancel(self, app, error=None):
        if not self.active or self.pending is not None:return
        self.pending='FAILED' if error else 'CANCELLED'
        self.error=error
        self.status='CANCELLING'
        self.cleanup_deadline_ns=app.vehicle.clock().monotonic_ns+10_000_000_000
        self._reset_boundary()
        if self.child_id is not None:
            try:app.cancel_mission(_design_child=True)
            except ValueError:pass  # The child may already be terminal; never launch a substitute.
        app._emit('design_cancel_requested',task_id=self.task_id,error=error)

    def _finish(self, app, status, error=None):
        self.status=status
        if error:self.error=error
        app._emit('design_finished',task_id=self.task_id,status=status,error=self.error,
                  completed_steps=len(self.results),stop_evidence=self.stop_evidence)

    def tick(self, app):
        if not self.active:return
        now=app.vehicle.clock().monotonic_ns
        if self.pending is None:
            try:
                if app.design_catalog()['context']!=self.context:
                    raise ValueError('design_context_changed')
                if not app.vehicle.connected or app.environment_fault or app.state=='DEGRADED':
                    raise ValueError('design_vehicle_or_environment_unavailable')
                if now>self.deadline_ns:raise ValueError('design_deadline_exceeded')
            except (OSError,ValueError,RuntimeError) as exc:self.cancel(app,str(exc))
        child=app.task_status() if self.child_id is not None else None
        if self.child_id is not None:
            if child is None or child.get('task_id')!=self.child_id:
                self.cancel(app,'design_child_identity_lost')
                self._finish(app,'FAILED','design_child_identity_lost; cleanup_unconfirmed');return
            if child['status'] not in TERMINAL:
                if self.pending is not None and now>=self.cleanup_deadline_ns:
                    self._finish(app,'FAILED',(self.error or 'cancel')+'; cleanup_unconfirmed')
                return
            if not self.results or self.results[-1]['task_id']!=self.child_id:
                self.results.append(deepcopy(child))
            self.child_id=None
            if self.pending is None and child['status']!='SUCCEEDED':
                self.cancel(app,'design_child_'+child['status'].lower()+': '+str(child.get('error')))
            elif self.pending is None:
                self.index+=1;self.status='WAITING_BOUNDARY';self._reset_boundary()
        boundary=app.design_boundary()
        if boundary['eligible']:
            if self.stable_since is None:self.stable_since=now
            if boundary['capture_ns']!=self.last_capture:
                self.samples+=1;self.last_capture=boundary['capture_ns']
            stable=self.samples>=3 and now-self.stable_since>=300_000_000
        else:
            self._reset_boundary();stable=False
        if stable:self.stop_evidence='SIMULATION_TELEMETRY_DISARMED_STATIONARY'
        if self.pending is not None:
            if stable:self._finish(app,self.pending)
            elif now>=self.cleanup_deadline_ns:self._finish(app,'FAILED',(self.error or 'cancel')+'; cleanup_unconfirmed')
            return
        if not stable:return
        if self.index==len(self.design.missions):self._finish(app,'SUCCEEDED');return
        try:
            child=app.start_mission(self.design.missions[self.index],_design_child=True)
            self.child_id=child['task_id'];self.status='RUNNING';self._reset_boundary()
            app._emit('design_step_started',task_id=self.task_id,index=self.index,
                      mission=self.design.missions[self.index],child_task_id=self.child_id)
        except (OSError,ValueError,RuntimeError) as exc:self.cancel(app,str(exc))

    def view(self, app):
        return {'task_id':self.task_id,'mission':'designed:'+self.design.sha256,'title':self.design.title,
                'configuration_sha256':self.design.sha256,'status':self.status,'error':self.error,
                'step_index':self.index,'step_count':len(self.design.missions),
                'steps':[{'mission':m} for m in self.design.missions], 'completed':deepcopy(self.results),
                'child':app.task_status() if self.child_id is not None else None,
                'deadline_ns':self.deadline_ns,'stop_evidence':self.stop_evidence,
                'scope':'explicit localhost simulation; not physical vehicle stop acceptance'}

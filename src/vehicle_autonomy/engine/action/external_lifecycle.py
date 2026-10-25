"""Independent external responsibility; a vehicle guard cannot discharge it."""
from contextlib import contextmanager
from contextvars import ContextVar

from vehicle_autonomy.contracts.action import ActionKind,ActionSafety
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected

_current=ContextVar('managed_action_jobs',default=None)
TERMINAL=frozenset({'SUCCEEDED','FAILED','CANCELLED'})


def register_job(job,protocol,locator,*,provider_id=None,provider_epoch=None):
    owner=_current.get()
    if owner is None:raise ActionAdmissionRejected('external jobs require a managed Action lifecycle')
    owner.register(job,protocol,locator,provider_id=provider_id,provider_epoch=provider_epoch)


def require_job_scope():
    owner=_current.get()
    if owner is None:raise ActionAdmissionRejected('external jobs require a managed Action lifecycle')
    return owner._allowed()


class ExternalLifecycle:
    def __init__(self,spec,store,owner,runtime_id,can_start):
        self.spec=spec;self.store=store;self.jobs=[];self.pending=None;self.attested=False
        self.owner=owner;self.runtime_id=runtime_id;self.can_start=can_start;self.sealed=False

    def seal(self):self.sealed=True

    @contextmanager
    def callback(self):
        token=_current.set(self)
        try:yield
        finally:_current.reset(token)

    def _allowed(self):
        if self.sealed or not self.can_start() or _current.get() is not self:
            raise ActionAdmissionRejected('external job ingress is fenced outside the active Action callback')
        if self.spec.kind is ActionKind.QUERY or self.spec.external_lifecycle=='typed_only':
            raise ActionAdmissionRejected('Action contract forbids independent external jobs')
        if self.store is None:raise ActionAdmissionRejected('external provider has no verified resource ledger')
        binding=self.store.binding()
        if not any(r['owner']==self.owner and r['runtime']==self.runtime_id and r['phase']=='ACTIVE'
                and r['retained'] is None for r in self.store.records()):
            raise ActionAdmissionRejected('no active durable provider reservation')
        return binding

    def register(self,job,protocol,locator,*,provider_id=None,provider_epoch=None):
        binding=self._allowed()
        if protocol!=binding['protocol']:raise ActionAdmissionRejected('job protocol/provider binding mismatch')
        if protocol=='http_job':
            if (provider_id,provider_epoch)!=(binding['provider_id'],binding['provider_epoch']) or binding['resource_id']!='jobs':
                raise ActionAdmissionRejected('HTTP provider identity/epoch changed')
        elif protocol=='ros2':
            if binding['resource_id']!='jobs' or not (locator==binding['locator'] or locator.startswith(binding['locator']+'/')):
                raise ActionAdmissionRejected('ROS endpoint/provider binding mismatch')
        elif protocol=='native':
            if (locator,provider_id,provider_epoch)!=(binding['locator'],binding['provider_id'],binding['provider_epoch']) or binding['resource_id']!='jobs':
                raise ActionAdmissionRejected('local native provider binding mismatch')
        else:raise ActionAdmissionRejected('unverified external job protocol')
        if self.pending is not None:
            if self.pending['job'] is not None:raise ActionAdmissionRejected('one job per external registration')
            self.pending['job']=job;return
        if not self.assess().release_safe:raise ActionAdmissionRejected('prior managed external job still unresolved')
        self.jobs.append({'job':job})

    def start(self,create):
        """Register opaque SDK/job factories before invoking any side effect.

        Built-in clients also enroll themselves before thread/process/POST.
        Custom implementations must use this port and truthfully implement the
        job terminal contract; arbitrary unregistered I/O is prohibited.
        """
        self._allowed()
        if not self.assess().release_safe:raise ActionAdmissionRejected('prior external job unresolved')
        entry={'job':None};self.jobs.append(entry);self.pending=entry
        try:
            with self.callback():job=create()
            if not callable(getattr(job,'poll',None)):raise TypeError('managed job handle required')
            if entry['job'] is not None and entry['job'] is not job:raise ValueError('multiple jobs in one registration')
            entry['job']=job;return job
        except ActionAdmissionRejected:
            if entry['job'] is None:self.jobs.remove(entry)
            raise
        finally:self.pending=None

    def assess(self):
        if self.attested:return ActionSafety(True)
        for entry in self.jobs:
            try:
                job=entry['job'];value=job.poll() if job is not None else {'state':'UNKNOWN'}
                if value['state'] not in TERMINAL:
                    reconcile=getattr(job,'reconcile',None)
                    if reconcile:value=reconcile()
                if value['state'] not in TERMINAL:
                    return ActionSafety(False,False,'independent external job outcome UNKNOWN/UNCONFIRMED')
            except Exception:return ActionSafety(False,False,'independent external job evidence unavailable')
        return ActionSafety(True)

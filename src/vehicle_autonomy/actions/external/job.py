"""One asynchronous job contract for native, ROS, HTTP and continuous services."""
from dataclasses import dataclass,field
from typing import Literal

from vehicle_autonomy.actions.common.standard import ContextFactory
from vehicle_autonomy.contracts.action import ActionSafety
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected
from vehicle_autonomy.contracts.decision import ActionDecision,ActionOutcome,ExitDecision,ExitReason


@dataclass(frozen=True,slots=True)
class DurationParameters:
    duration_s: float=field(default=.5,metadata={'minimum':.05,'maximum':30})


@dataclass(frozen=True,slots=True)
class WaitParameters(DurationParameters):
    behavior: Literal['normal','error']='normal'


class ExternalFactory(ContextFactory):
    def __init__(self,create_job):self.create_job=create_job
    def start_with_context(self,p,world,ctx):
        try:return ExternalInstance(self.create_job(p))
        except ActionAdmissionRejected:return ExternalInstance(_AdmissionDenied())
        except Exception:return ExternalInstance(_AdmissionUnknown())


class _AdmissionDenied:
    def poll(self):return {'state':'FAILED','error':'explicit external admission rejection; no side effects'}
    def cancel(self):pass
    def close(self):pass


class _AdmissionUnknown:
    """No handle returned: absence of a handle is not proof of remote rollback."""
    def poll(self):return {'state':'UNKNOWN','error':'external admission raised before returning a handle'}
    def cancel(self):pass
    def close(self):pass


class ExternalInstance:
    def __init__(self,job):self.job=job;self.cancelling=False
    def tick(self,world):
        value=self.job.poll();state=value['state']
        if state=='SUCCEEDED':return ActionDecision(ActionOutcome.SUCCEEDED,result=value.get('result'))
        if state in ('FAILED','UNKNOWN','CANCELLED'):
            return ActionDecision(ActionOutcome.FAILED,error=value.get('error') or 'external job '+state)
        return ActionDecision(ActionOutcome.RUNNING,feedback=value.get('feedback'))
    def exit(self,world,reason):
        try:return self._exit(world,reason)
        except Exception:
            try:self.job.close()
            except Exception:pass
            return ExitDecision(True,safety=ActionSafety(False,False,'external cancellation or cleanup raised; outcome UNKNOWN'))
    def _exit(self,world,reason):
        state=self.job.poll()['state']
        if state in ('SUCCEEDED','FAILED','CANCELLED'):
            self.job.close()
            return ExitDecision(True,safety=ActionSafety(True))
        if state=='UNKNOWN':
            self.job.close();return ExitDecision(True,safety=ActionSafety(False,False,'external outcome UNKNOWN'))
        if not self.cancelling:
            self.cancelling=True;self.job.cancel()
        return ExitDecision(False)
    def abandon(self):
        # Stop the local client, never claim that its remote service stopped.
        self.job.cancel();self.job.close()

    def recovery_descriptor(self):
        method=getattr(self.job,'recovery_descriptor',None)
        return method() if method else {'protocol':'opaque_external','queryable':False}

    def reconcile_exit(self):
        """Only an actual provider terminal result can resolve the latch."""
        method=getattr(self.job,'reconcile',None)
        if method is None:return None
        value=method()
        if value['state'] in ('SUCCEEDED','FAILED','CANCELLED'):
            return ActionSafety(True,False,'external terminal result reconciled',{'state':value['state']})
        return None

"""Mission membership uses the same ActionResources claims, never an authority.

The opaque in-process permit is not a serializable authorization token. SEND,
lease, physical exit and the Driver's explicit native handoff remain mandatory.
"""
from dataclasses import dataclass
from vehicle_autonomy.contracts.action import ActionSafety


@dataclass(frozen=True,eq=False)
class MissionPermit:
    id: str
    target: str
    resources: tuple


class MissionGroups:
    def __init__(self,runtime):self.runtime=runtime;self.groups={}

    def reserve(self,identifier,target,resources,*,allow_send=False,continuation_of=None,recovered=False):
        if len(self.groups)>=128 or identifier in self.groups:raise ValueError('Mission permit budget/identity unavailable')
        owners=[]
        if continuation_of:
            old=self.runtime._records.get(continuation_of)
            if (not allow_send or old is None or old.target!=target or old.state.value!='SUCCEEDED'
                    or old.safety is None or not old.safety.continuation_allowed or old.guard_stop is not None):
                raise ValueError('explicit successful continuation required')
            if old.mission_permit:
                group=self.groups[old.mission_permit.id]
                if group['phase']!='CONTINUATION':raise ValueError('old Mission still owns continuation')
                owners.append(old.mission_permit.id)
        if not self.runtime.resources.acquire(identifier,target,resources,continuation_of=continuation_of,group_owners=tuple(owners)):
            raise ValueError('Mission resource conflict')
        permit=MissionPermit(identifier,target,tuple(resources))
        self.groups[identifier]=dict(permit=permit,phase='UNKNOWN' if recovered else 'RUNNING',recovered=recovered)
        if recovered:self.runtime.resources.retain(identifier,'restarted Mission effects unresolved')
        return permit

    def check(self,permit,target):
        if (not isinstance(permit,MissionPermit) or self.groups.get(permit.id,{}).get('permit') is not permit
                or permit.target!=target or self.groups[permit.id]['phase']!='RUNNING'):
            raise ValueError('live Mission membership required')

    def owners(self,record):
        owners=[]
        if record.mission_permit:
            self.check(record.mission_permit,record.target)
            for requested in record.registration.spec.resources:
                if not any((r.conflict_group or r.name)==(requested.conflict_group or requested.name) and
                        (r.mode.value=='exclusive' or requested.mode.value=='shared') for r in record.mission_permit.resources):
                    raise ValueError('Action resource exceeds pinned Mission reservation')
            owners.append(record.mission_permit.id)
        if record.continuation_of:
            old=self.runtime._records[record.continuation_of]
            if old.mission_permit and old.mission_permit is not record.mission_permit:
                group=self.groups[old.mission_permit.id]
                if group['phase']!='CONTINUATION':raise ValueError('continuation belongs to an active/uncertain Mission')
                owners.append(old.mission_permit.id)
        return tuple(owners)

    def finish(self,permit,*,continuation=False):
        group=self.groups[permit.id]
        if group['permit'] is not permit:raise ValueError('unknown Mission permit')
        group['phase']='CONTINUATION' if continuation else 'UNKNOWN'
        self.runtime.resources.retain(permit.id,'Mission exits/continuation require all member safety evidence')
        self.settle()

    def settle(self):
        for identifier,group in self.groups.items():
            if group['phase'] in ('RUNNING','RELEASED') or group['recovered']:continue
            members=[r for r in self.runtime._records.values() if r.mission_permit is group['permit']]
            if all(r.state.value=='REJECTED' or r.safety and r.safety.release_safe for r in members):
                self.runtime.resources.release(identifier,safety=ActionSafety(True,False,'all Mission members safely exited'))
                group['phase']='RELEASED'

    def reconstructed(self,permit):
        group=self.groups[permit.id]
        if group['permit'] is not permit or not group['recovered']:raise ValueError('recovered Mission group required')
        self.runtime.resources.release(permit.id,safety=ActionSafety(True,False,'trusted explicit deployment reconstruction'))
        group.update(recovered=False,phase='RELEASED')

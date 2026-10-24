"""Per-target resource arbitration; no vehicle authorization is granted here."""
from dataclasses import dataclass

from vehicle_autonomy.contracts.action import ActionResource, ResourceMode


@dataclass(frozen=True,slots=True)
class Claim:
    owner: str
    target: str
    resource: ActionResource


class ActionResources:
    def __init__(self):
        self._claims: list[Claim] = []
        self._guards: dict[str,str] = {}

    @staticmethod
    def _key(target,resource):return target,resource.conflict_group or resource.name

    def acquire(self,owner,target,resources,*,continuation_of=None):
        if any(not isinstance(r,ActionResource) for r in resources):raise TypeError('typed resources required')
        if any(c.owner==owner for c in self._claims):return True
        for requested in resources:
            for existing in self._claims:
                if (existing.owner!=continuation_of and self._key(target,requested)==self._key(existing.target,existing.resource)
                        and (requested.mode is ResourceMode.EXCLUSIVE or existing.resource.mode is ResourceMode.EXCLUSIVE)):
                    return False
        self._claims.extend(Claim(owner,target,r) for r in resources)
        return True

    def release(self,owner):
        self._claims[:]=[c for c in self._claims if c.owner!=owner]
        self._guards.pop(owner,None)

    def retain(self,owner,reason):self._guards[owner]=reason

    def view(self):
        return [dict(owner=c.owner,target=c.target,name=c.resource.name,mode=c.resource.mode.value,
                     conflict_group=c.resource.conflict_group,retained=self._guards.get(c.owner)) for c in self._claims]

"""Capability selection never grants motion or replaces safety identity binding."""
from threading import RLock
from vehicle_autonomy.contracts.algorithms import AlgorithmProvider
from vehicle_autonomy.contracts.action import ActionSafety


class AlgorithmCatalog:
    def __init__(self):self._definitions={};self._selected={};self._lock=RLock()

    def register(self,definition):
        if not isinstance(definition,AlgorithmProvider):raise TypeError('typed algorithm definition required')
        with self._lock:
            if definition.provider_id in self._definitions:raise ValueError('duplicate algorithm provider identity')
            if len(self._definitions)>=64:raise ValueError('algorithm registry capacity exhausted')
            self._definitions[definition.provider_id]=definition

    def definitions(self):
        with self._lock:return tuple(self._definitions.values())

    def select(self,target,provider_id,*,vehicle_kind,capability,assess_idle,assess_ready,safety_store=None):
        """Trusted callbacks supplied by composition; never accepted from JSON.

        Active jobs always retain their original provider; only a fresh Action
        may consume this selection. No lease, epoch or SEND is created here.
        """
        with self._lock:
            definition=self._definitions[provider_id]
            if vehicle_kind not in definition.vehicle_types or capability not in definition.capabilities:raise ValueError('unsupported algorithm capability or vehicle')
            idle=assess_idle();ready=assess_ready(definition)
            if not isinstance(idle,ActionSafety) or not idle.release_safe or idle.continuation_allowed:raise ValueError('provider switch requires fully resolved control/external exit')
            if ready is not True:raise ValueError('algorithm profile/input/health unavailable')
            binding=None
            if definition.requires_motion_bridge:
                if safety_store is None:raise ValueError('verified safety provider binding required')
                binding=safety_store.binding()  # Existing fixed-root identity checks.
                if safety_store.records():raise ValueError('provider has unresolved jobs')
                if tuple(safety_store.bound_resources())!=definition.resources:raise ValueError('algorithm/safety resource definitions disagree')
            if (target,definition.provider_type) not in self._selected and len(self._selected)>=128:raise ValueError('selection capacity exhausted')
            self._selected[target,definition.provider_type]=(definition,binding)
            return definition

    def selected(self,target,provider_type):
        with self._lock:return self._selected.get((target,provider_type))

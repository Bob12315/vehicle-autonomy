from typing import Protocol
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.effects.payload import PayloadEffectEnvelope
from vehicle_autonomy.contracts.sensor import Observation,DetectedObject

class PayloadCommandPort(Protocol):
    @property
    def state_producer_id(self)->str:
        """Identity of the independent payload-state observer."""
    def release(self,command:PayloadEffectEnvelope,now:TimePoint)->None:
        """Execution-only mutation, while holding the final authorization fence."""
    def poll(self,now:TimePoint)->tuple[Observation[DetectedObject],...]:
        """Read independent payload state; acceptance is not completion."""

"""Non-vehicle one-shot payload request; never translated to Servo/MAVLink."""
from dataclasses import dataclass
from contracts.core.geometry import Vector3
from contracts.core.primitives import ActionInstanceId,EffectId,RunId,SchemaVersion
from contracts.core.time import TimePoint
from contracts.world.models import ResourceReference

@dataclass(frozen=True,slots=True)
class ReleasePayloadEffect:
    payload_id: str
    target_id: str
    producer_id: str
    target_observation_id: str
    target_position: Vector3
    target_captured_at: TimePoint
    environment: ResourceReference

    def __post_init__(self):
        if any(not isinstance(getattr(self,n),str) or not getattr(self,n).strip() for n in ('payload_id','target_id','producer_id','target_observation_id')):raise ValueError('payload and target provenance required')
        if not isinstance(self.target_position,Vector3) or not isinstance(self.target_captured_at,TimePoint) or not isinstance(self.environment,ResourceReference):raise TypeError('typed target geometry/time/environment required')

@dataclass(frozen=True,slots=True)
class PayloadEffectEnvelope:
    schema_version: SchemaVersion
    effect_id: EffectId
    run_id: RunId
    action_instance_id: ActionInstanceId
    created_at: TimePoint
    deadline: TimePoint
    effect: ReleasePayloadEffect

    def __post_init__(self):
        for name,kind in (('effect_id',EffectId),('run_id',RunId),('action_instance_id',ActionInstanceId)):
            if not isinstance(getattr(self,name),kind):object.__setattr__(self,name,kind(getattr(self,name)))
        if not isinstance(self.schema_version,SchemaVersion) or not isinstance(self.created_at,TimePoint) or not isinstance(self.deadline,TimePoint) or not isinstance(self.effect,ReleasePayloadEffect):raise TypeError('typed payload envelope required')
        if self.deadline.elapsed_ns_since(self.created_at)<=0:raise ValueError('payload deadline must follow creation')

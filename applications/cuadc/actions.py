"""Observation-driven selection/approach; no Gazebo, vehicle port or legacy imports."""
from dataclasses import dataclass,replace
import math
from actions.basic import BasicInstance,BasicParameters
from contracts.core.geometry import Vector3
from contracts.core.quality import QualityState
from contracts.decision import ActionSpec,ActionDecision,ActionOutcome,ExitDecision,ExitReason,EffectPhase
from contracts.effects.vehicle import PoseTargetEffect,TwistTargetEffect,StopMotionEffect
from contracts.effects.payload import ReleasePayloadEffect
from contracts.world.models import ResourceReference
from environments.resources import ResolvedTarget,Rectangle

@dataclass(frozen=True,slots=True)
class TargetParameters:
    vehicle_kind:str
    environment:ResourceReference
    region:Rectangle
    altitude_m:float
    payload_id:str|None=None
    scores:tuple[tuple[str,int],...]=(('bucket_1',500),('bucket_2',300),('bucket_3',100))
    allowed_sources:tuple[str,...]=('sim.objects:','vision.recorded:')
    timeout_ns:int=60_000_000_000
    def __post_init__(self):
        if self.vehicle_kind not in ('copter','rover') or not math.isfinite(self.altitude_m) or not 0<=self.altitude_m<=2 or type(self.timeout_ns) is not int or not 5_000_000_000<=self.timeout_ns<=60_000_000_000:raise ValueError('invalid target Action parameters')
        if self.region.frame!='odom' or not self.allowed_sources or not self.scores or len({p[0] for p in self.scores})!=len(self.scores) or any(type(v) is not int or v<=0 for _,v in self.scores):raise ValueError('explicit search region/scores/sources required')
        if self.payload_id is not None and (self.vehicle_kind!='copter' or not self.payload_id.strip()):raise ValueError('payload requires Copter capability')

def candidates(world,parameters):
    scores=dict(parameters.scores);result=[]
    for obj in world.objects:
        try:age=world.published_at.elapsed_ns_since(obj.position.captured_at)
        except ValueError:continue
        point=obj.position.value
        region=parameters.region
        if (obj.label not in scores or obj.quality is not QualityState.VALID or obj.confidence<.5 or obj.position.frame_id!='odom'
                or not 0<=age<=1_000_000_000 or not any(str(obj.producer_id).startswith(prefix) for prefix in parameters.allowed_sources)
                or not region.min_x<=point.x<=region.max_x or not region.min_y<=point.y<=region.max_y):continue
        result.append(obj)
    ranked=sorted(result,key=lambda o:(-scores[o.label],-o.confidence,o.object_id))
    unique=[]
    for obj in ranked:
        if not any(math.hypot(obj.position.value.x-old.position.value.x,obj.position.value.y-old.position.value.y)<.35 for old in unique):unique.append(obj)
    return tuple(unique)

class TargetAction:
    def start(self,parameters,snapshot):return TargetInstance(parameters,snapshot)

class TargetInstance:
    def __init__(self,p,world):
        self.p=p;self.start_ns=world.published_at.monotonic_ns;self.stage='acquire';self.target=None;self.navigation=None;self.release_boundary=None;self.observation=None
    def tick(self,world):return self.tick_with_results(world,())
    def tick_with_results(self,world,results):
        now=world.published_at.monotonic_ns
        if world.environment!=self.p.environment or world.vehicle is None or world.localization is None:return ActionDecision(ActionOutcome.FAILED,error='target_world_unavailable')
        if now-self.start_ns>self.p.timeout_ns:return ActionDecision(ActionOutcome.FAILED,error='target_approach_deadline')
        if self.stage=='acquire':
            ranked=candidates(world,self.p)
            if not ranked:
                if now-self.start_ns>5_000_000_000:return ActionDecision(ActionOutcome.FAILED,error='target_acquisition_deadline')
                return ActionDecision(ActionOutcome.RUNNING)
            self.target=ranked[0]
            position=self.target.position.value
            resolved=ResolvedTarget(self.target.object_id,'odom',Vector3(position.x,position.y,self.p.altitude_m),self.p.environment)
            nav=BasicParameters(self.p.vehicle_kind,self.p.environment,resolved,timeout_ns=45_000_000_000,arrival_margin_m=.2 if self.p.vehicle_kind=='copter' else .45)
            self.navigation=BasicInstance('goto',nav,world);self.stage='approach'
        current=next((o for o in candidates(world,self.p) if o.object_id==self.target.object_id and o.producer_id==self.target.producer_id),None)
        if current is None:return ActionDecision(ActionOutcome.FAILED,error='target_lost_or_expired')
        a,b=current.position.value,self.target.position.value
        if math.dist((a.x,a.y,a.z),(b.x,b.y,b.z))>.1:return ActionDecision(ActionOutcome.FAILED,error='locked_target_moved')
        self.observation=current
        if self.stage=='approach':
            decision=self.navigation.tick_with_results(world,results)
            if decision.outcome is ActionOutcome.SUCCEEDED:self.stage='settle';return ActionDecision(ActionOutcome.RUNNING)
            return decision
        if self.stage=='settle':
            exit=self.navigation.exit_with_results(world,ExitReason.SUCCEEDED,results)
            if not exit.complete:return ActionDecision(ActionOutcome.RUNNING,exit.effects)
            if self.p.payload_id is None:return ActionDecision(ActionOutcome.SUCCEEDED,result={'target':current.object_id,'observation':str(current.source_observation_id)})
            self.stage='release';self.release_boundary=len(results)
            effect=ReleasePayloadEffect(self.p.payload_id,current.object_id,str(current.producer_id),str(current.source_observation_id),current.position.value,current.position.captured_at,self.p.environment)
            return ActionDecision(ActionOutcome.RUNNING,(effect,))
        feedback=results[self.release_boundary:]
        if feedback and feedback[-1].phase in (EffectPhase.REJECTED,EffectPhase.CANCELLED,EffectPhase.UNKNOWN):return ActionDecision(ActionOutcome.FAILED,error=feedback[-1].reason or 'payload_release_unconfirmed')
        marker=self.p.payload_id+'@'+current.object_id
        observed=any(o.object_id.endswith(':'+marker) and str(o.producer_id).startswith('sim.payload:') and o.label=='sim_payload_released' for o in world.objects)
        if observed and feedback and feedback[-1].phase is EffectPhase.COMPLETED:return ActionDecision(ActionOutcome.SUCCEEDED,result={'target':current.object_id,'payload':self.p.payload_id,'target_observation':str(current.source_observation_id)})
        return ActionDecision(ActionOutcome.RUNNING)
    def exit(self,world,reason):return self.exit_with_results(world,reason,())
    def exit_with_results(self,world,reason,results):
        if self.navigation is None:return ExitDecision(True)
        return self.navigation.exit_with_results(world,reason,results)

def register_targets(registry):
    registry.register_typed(ActionSpec('cuadc.inspect',TargetParameters,frozenset({'navigation'}),(PoseTargetEffect,TwistTargetEffect,StopMotionEffect),1_000_000_000),TargetAction())
    registry.register_typed(ActionSpec('cuadc.approach_release',TargetParameters,frozenset({'navigation','payload_release'}),(PoseTargetEffect,StopMotionEffect,ReleasePayloadEffect),2_000_000_000),TargetAction())

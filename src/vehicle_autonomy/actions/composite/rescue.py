"""CUADC rescue operations over immutable observations and typed requests.

No archived code, Gazebo truth labels, sockets, camera inference or vehicle ports
are used here. Source recipes are translated in app/scenarios/cuadc/rescue.py.
"""
from dataclasses import dataclass, field, replace
import math

from vehicle_autonomy.actions.common.standard import ContextFactory
from vehicle_autonomy.actions.copter.rescue import MotionInstance, FlightFactory, TakeoffParameters, GotoParameters
from vehicle_autonomy.contracts.action import ActionKind, ActionResource, ResourceMode
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.core.geometry import Vector3
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.decision import ActionDecision, ActionOutcome, ActionSpec, ExitDecision, EffectPhase
from vehicle_autonomy.contracts.effects.vehicle import TakeoffEffect, TwistTargetEffect, StopMotionEffect
from vehicle_autonomy.contracts.effects.payload import ReleasePayloadEffect
from vehicle_autonomy.engine.action.schema import parameter_schema

SCORES = {'bucket_1':500, 'bucket_2':300, 'bucket_3':100, 'bucket':50}


@dataclass(frozen=True, slots=True)
class ServoOutput:
    channel: int
    release_pwm: int
    hold_pwm: int

    def __post_init__(self):
        if (self.channel, self.release_pwm, self.hold_pwm) not in ((8,1800,1370),(9,1835,1335)):
            raise ValueError('only the explicitly mapped rescue servo outputs 8/9 are allowed')


@dataclass(frozen=True, slots=True)
class Target:
    target_id: str
    producer_id: str
    label: str
    x_m: float
    y_m: float
    z_m: float
    confidence: float
    captured_ns: int
    clock_domain: str
    world_generation: str
    observation_id: str


@dataclass(frozen=True, slots=True)
class DropTarget:
    target: Target
    servo_outputs: tuple[ServoOutput, ...]
    release_target_ey: float


@dataclass(frozen=True, slots=True)
class CaptureParameters:
    min_confidence: float = field(default=.3, metadata={'minimum':.3, 'maximum':1})


@dataclass(frozen=True, slots=True)
class FuseParameters:
    objects: tuple[Target, ...]
    cluster_radius_m: float = field(default=.65, metadata={'minimum':.1, 'maximum':1})


@dataclass(frozen=True, slots=True)
class SelectParameters:
    objects: tuple[Target, ...]
    target_count: int = field(default=2, metadata={'minimum':1, 'maximum':2})


@dataclass(frozen=True, slots=True)
class ConfirmParameters:
    target: Target


@dataclass(frozen=True, slots=True)
class AlignParameters:
    target: Target
    target_altitude_m: float = field(default=1.1, metadata={'minimum':.3,'maximum':2.5})
    descend_speed_mps: float = field(default=.2, metadata={'minimum':.05,'maximum':.2})
    release_target_ey: float = field(default=0., metadata={'minimum':-.3,'maximum':.3})
    final_settle_time_s: float = field(default=.3, metadata={'minimum':.3,'maximum':2})
    target_acquisition_timeout_s: float = field(default=3., metadata={'minimum':.5,'maximum':5})


@dataclass(frozen=True, slots=True)
class ReleaseParameters:
    target: Target
    servo_outputs: tuple[ServoOutput, ...] = field(metadata={'minItems':1,'maxItems':2})
    alignment_confirmed: bool = False


def object_schema(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)

TARGET = parameter_schema(Target)
DROP = parameter_schema(DropTarget)
OBJECTS = object_schema({'objects':dict(type='array',items=TARGET,maxItems=128)})
SELECTED = object_schema({'targets':dict(type='array',items=DROP,maxItems=2), 'count':{'type':'integer'}})


def fresh(world, obj, threshold=.3):
    try: age=world.published_at.elapsed_ns_since(obj.position.captured_at)
    except ValueError: return False
    p=obj.position.value
    return (0<=age<=1_000_000_000 and obj.position.frame_id=='odom' and obj.quality is QualityState.VALID
        and obj.confidence>=threshold and (str(obj.producer_id).startswith('vision.pt:') or obj.label=='H' and str(obj.producer_id).startswith('vision.marker:'))
        and obj.label in (*SCORES,'H') and -4<=p.x<=4 and -2<=p.y<=62)


def encode_target(world, obj):
    p=obj.position.value
    return Target(str(obj.object_id),str(obj.producer_id),obj.label,p.x,p.y,p.z,obj.confidence,
        obj.position.captured_at.monotonic_ns,str(obj.position.captured_at.clock_domain_id),
        str(world.version.generation_id),str(obj.source_observation_id))


def current_target(world, target):
    if str(world.version.generation_id)!=target.world_generation or str(world.published_at.clock_domain_id)!=target.clock_domain:
        return None
    if not 0<=world.published_at.monotonic_ns-target.captured_ns<=180_000_000_000: return None
    obj=next((o for o in world.objects if str(o.object_id)==target.target_id and str(o.producer_id)==target.producer_id),None)
    if obj is None or not fresh(world,obj):return None
    p=obj.position.value
    if math.dist((p.x,p.y,p.z),(target.x_m,target.y_m,target.z_m))>.65:return None
    return obj


class QueryFactory(ContextFactory):
    def __init__(self, name):self.name=name
    def validate_context(self,p,world,ctx):
        if not ctx.owned_simulation or ctx.target_kind!='copter':raise ValueError('owned Copter simulation required')
    def start_with_context(self,p,world,ctx):
        self.validate_context(p,world,ctx);return QueryInstance(self.name,p,world)


class QueryInstance:
    def __init__(self,name,p,world):self.name=name;self.p=p;self.generation=world.version.generation_id;self.started_ns=world.published_at.monotonic_ns
    def tick(self,world):
        if world.version.generation_id!=self.generation:return ActionDecision(ActionOutcome.FAILED,error='rescue_world_epoch_changed')
        if world.vehicle is None or world.vehicle.health.quality is not QualityState.VALID or world.localization is None or world.localization.quality is not QualityState.VALID:
            return ActionDecision(ActionOutcome.FAILED,error='rescue_observation_pose_unavailable')
        if self.name=='ConfirmTarget':
            target=self.p.target
            if (str(world.version.generation_id)!=target.world_generation or str(world.published_at.clock_domain_id)!=target.clock_domain
                    or not 0<=world.published_at.monotonic_ns-target.captured_ns<=180_000_000_000):
                return ActionDecision(ActionOutcome.FAILED,error='rescue_selected_target_expired')
            candidates=[o for o in world.objects if fresh(world,o) and str(o.producer_id)==target.producer_id
                and o.label==target.label and math.hypot(o.position.value.x-target.x_m,o.position.value.y-target.y_m)<=.4
                and abs(o.position.value.z-target.z_m)<=.15 and world.published_at.elapsed_ns_since(o.position.captured_at)<=300_000_000]
            if len(candidates)!=1:
                if world.published_at.monotonic_ns-self.started_ns<3_000_000_000:return ActionDecision(ActionOutcome.RUNNING)
                return ActionDecision(ActionOutcome.FAILED,error='rescue_target_reacquisition_missing_or_ambiguous')
            return ActionDecision(ActionOutcome.SUCCEEDED,result={'target':to_json_value(encode_target(world,candidates[0]))})
        if self.name in ('CaptureView','LandingTarget','CaptureReconView'):
            values=[encode_target(world,o) for o in world.objects if fresh(world,o,self.p.min_confidence)
                and ((self.name=='CaptureView' and o.label in SCORES and 30<=o.position.value.y<=35)
                    or (self.name=='LandingTarget' and o.label=='H' and math.hypot(o.position.value.x,o.position.value.y)<=1.5)
                    or (self.name=='CaptureReconView' and 55<=o.position.value.y<=60))]
            if self.name=='LandingTarget':
                if not values:return ActionDecision(ActionOutcome.FAILED,error='rescue_landing_marker_unavailable')
                return ActionDecision(ActionOutcome.SUCCEEDED,result={'target':to_json_value(max(values,key=lambda t:t.confidence))})
        else:
            values=[]
            for target in self.p.objects:
                obj=current_target(world,target)
                if obj is None:return ActionDecision(ActionOutcome.FAILED,error='rescue_capture_expired_or_target_lost')
                values.append(encode_target(world,obj))
        values=sorted(values,key=lambda t:(-SCORES.get(t.label,0),-t.confidence,t.target_id))
        unique=[]
        distance=self.p.cluster_radius_m if self.name=='FuseViews' else 1.
        for value in values:
            if not any(math.hypot(value.x_m-t.x_m,value.y_m-t.y_m)<distance for t in unique):unique.append(value)
        if self.name=='SelectDropTargets':
            selected=unique[:self.p.target_count]
            if not selected:return ActionDecision(ActionOutcome.FAILED,error='rescue_no_observed_drop_target')
            first=ServoOutput(8,1800,1370);second=ServoOutput(9,1835,1335)
            drops=[DropTarget(t,(first,second) if len(selected)==1 else ((first,) if i==0 else (second,)),.3 if i==0 else -.05) for i,t in enumerate(selected)]
            result={'targets':to_json_value(tuple(drops)),'count':len(drops)}
        else:result={'objects':to_json_value(tuple(unique[:128]))}
        return ActionDecision(ActionOutcome.SUCCEEDED,result=result)
    def exit(self,world,reason):return ExitDecision(True)


class AlignFactory(FlightFactory):
    def __init__(self):super().__init__('AlignDescend')
    def validate_context(self,p,world,ctx):
        super().validate_context(p,world,ctx)
        if current_target(world,p.target) is None:raise ValueError('fresh locked visual target required')
    def start_with_context(self,p,world,ctx):
        self.validate_context(p,world,ctx);return AlignInstance(p,world)


class AlignInstance(MotionInstance):
    def __init__(self,p,world):super().__init__(world);self.p=p;self.lost_since=None
    def tick_with_results(self,world,results):
        error=self.error(world,results)
        if error:return error
        obj=current_target(world,self.p.target)
        if obj is None:
            now=world.published_at.monotonic_ns
            if self.lost_since is None:self.lost_since=now;self.refresh=0
            self.stable=None
            if now-self.lost_since>=self.p.target_acquisition_timeout_s*1e9:
                return ActionDecision(ActionOutcome.FAILED,error='rescue_alignment_target_lost')
            return self.request(world,Vector3(0,0,0))
        self.lost_since=None
        p=self.p;loc=world.localization;position=loc.pose.value.position;v=loc.twist.value.linear
        t=obj.position.value;height=max(.05,position.z-t.z)
        # Source recipe offset is kept explicitly. This is the declared virtual
        # camera projection (not a claim of physical camera calibration).
        offset=p.release_target_ey*height*math.tan(math.radians(131.870643)/2)*.21
        dx=t.x-position.x;dy=t.y+offset-position.y
        horizontal=math.hypot(dx,dy);dz=p.target_altitude_m-position.z
        final=abs(dz)<=.1
        good=horizontal<=.04 and abs(dz)<=.1 and math.sqrt(v.x*v.x+v.y*v.y+v.z*v.z)<=.08
        if self.settled(world,good,results,p.final_settle_time_s):
            return ActionDecision(ActionOutcome.SUCCEEDED,result={'alignment_confirmed':True,'target_id':p.target.target_id})
        kp=.2 if final else .42;cap=.15 if final else .3
        vx=max(-cap,min(cap,kp*dx));vy=max(-cap,min(cap,kp*dy))
        # Descent stops when the target is outside the alignment window. Target
        # loss/timeout fails and never enables a release node.
        vz=max(-p.descend_speed_mps,min(p.descend_speed_mps,.5*dz)) if horizontal<=.2 else 0.
        return self.request(world,Vector3(vx,vy,vz))


class ReleaseFactory(ContextFactory):
    def validate_context(self,p,world,ctx):
        if not ctx.owned_simulation or 'rescue_payload' not in ctx.capabilities:raise ValueError('explicit rescue payload Execution required')
        if not p.alignment_confirmed or not p.servo_outputs or len({s.channel for s in p.servo_outputs})!=len(p.servo_outputs):raise ValueError('confirmed alignment and unique mapped outputs required')
        if current_target(world,p.target) is None:raise ValueError('fresh locked release target required')
    def start_with_context(self,p,world,ctx):
        self.validate_context(p,world,ctx);return ReleaseInstance(p,world)


class ReleaseInstance:
    def __init__(self,p,world):self.p=p;self.requested=False;self.boundary=0;self.started=world.published_at
    def tick(self,world):return self.tick_with_results(world,())
    def tick_with_results(self,world,results):
        obj=current_target(world,self.p.target)
        if obj is None:return ActionDecision(ActionOutcome.FAILED,error='rescue_release_target_lost')
        if not self.requested:
            self.requested=True;self.boundary=len(results)
            return ActionDecision(ActionOutcome.RUNNING,tuple(ReleasePayloadEffect('payload_'+str(s.channel-7),str(obj.object_id),str(obj.producer_id),str(obj.source_observation_id),obj.position.value,obj.position.captured_at,world.environment) for s in self.p.servo_outputs))
        feedback=results[self.boundary:]
        if any(r.phase in (EffectPhase.REJECTED,EffectPhase.UNKNOWN,EffectPhase.CANCELLED) for r in feedback):
            return ActionDecision(ActionOutcome.FAILED,error='rescue_payload_unconfirmed')
        if len(feedback)==len(self.p.servo_outputs) and all(r.phase is EffectPhase.COMPLETED for r in feedback):
            return ActionDecision(ActionOutcome.SUCCEEDED,result={'release_observed':True})
        return ActionDecision(ActionOutcome.RUNNING)
    def exit(self,world,reason):
        # Already submitted one-shots are resolved by PayloadExecution and the
        # Driver's physical scope barrier; cancellation cannot undo a drop.
        return ExitDecision(True)


def register_rescue(registry):
    motion=(TwistTargetEffect,StopMotionEffect)
    def add(name,params,factory,cap,*,effects=(),output=None,timeout=15):
        registry.register_typed(ActionSpec('Rescue.'+name,params,frozenset(cap),effects,
            effect_ttl_ns=1_000_000_000,vehicle_types=frozenset({'copter'}),
            kind=ActionKind.GOAL if effects else ActionKind.QUERY,
            resources=(ActionResource('vehicle.motion',ResourceMode.EXCLUSIVE,'vehicle.control'),) if effects else (ActionResource('world.objects',ResourceMode.SHARED),),
            default_timeout_ns=timeout*1_000_000_000,max_timeout_ns=timeout*1_000_000_000,
            exit_timeout_ns=12_000_000_000,output_schema=output,external_lifecycle='typed_only',
            output_max_age_ns=180_000_000_000 if name in ('SelectDropTargets','ConfirmTarget','LandingTarget') else 5_000_000_000 if name=='AlignDescend' else 3_000_000_000,
            effect_ttl_overrides={'TakeoffEffect':5_000_000_000} if TakeoffEffect in effects else None,
            description='CUADC 2026 rescue; explicit owned simulation providers required',
            success_semantics='Fresh observed goal and existing physical exit barriers; ACK alone is insufficient.'),factory)
    add('Takeoff',TakeoffParameters,FlightFactory('Takeoff'),{'rescue_flight'},effects=(TakeoffEffect,*motion),timeout=45)
    add('Goto',GotoParameters,FlightFactory('Goto'),{'rescue_flight'},effects=motion,output=object_schema({'physical_goal_observed':{'const':True}}),timeout=180)
    add('CaptureView',CaptureParameters,QueryFactory('CaptureView'),{'rescue_vision'},output=OBJECTS)
    add('CaptureReconView',CaptureParameters,QueryFactory('CaptureReconView'),{'rescue_vision'},output=OBJECTS)
    add('LandingTarget',CaptureParameters,QueryFactory('LandingTarget'),{'rescue_vision'},output=object_schema({'target':TARGET}))
    add('FuseViews',FuseParameters,QueryFactory('FuseViews'),{'rescue_vision'},output=OBJECTS)
    add('SelectDropTargets',SelectParameters,QueryFactory('SelectDropTargets'),{'rescue_vision'},output=SELECTED)
    add('ConfirmTarget',ConfirmParameters,QueryFactory('ConfirmTarget'),{'rescue_vision'},output=object_schema({'target':TARGET}))
    add('AlignDescend',AlignParameters,AlignFactory(),{'rescue_flight','rescue_vision'},effects=motion,output=object_schema({'alignment_confirmed':{'type':'boolean'},'target_id':{'type':'string'}}),timeout=90)
    add('ReleasePayload',ReleaseParameters,ReleaseFactory(),{'rescue_payload'},effects=(ReleasePayloadEffect,),output=object_schema({'release_observed':{'type':'boolean'}}),timeout=15)

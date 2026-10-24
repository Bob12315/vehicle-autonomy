"""Shared Action operations. Only typed effects cross the execution boundary."""
from dataclasses import dataclass, field
import math

from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.decision import ActionDecision, ActionOutcome, EffectPhase, ExitDecision
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect, DisarmEffect, ModeEffect

BAD=(EffectPhase.REJECTED,EffectPhase.UNKNOWN,EffectPhase.CANCELLED)


@dataclass(frozen=True,slots=True)
class Empty:
    pass


@dataclass(frozen=True,slots=True)
class ModeParameters:
    mode: str=field(metadata={'minLength':1,'maxLength':20})


class ContextFactory:
    def start(self,p,world):
        raise ValueError('this standalone Action requires its declared target context')


class CommandInstance:
    def __init__(self,effect,expected):
        self.effect=effect;self.expected=expected;self.requested=False
    def tick(self,world):return self.tick_with_results(world,())
    def tick_with_results(self,world,results):
        if not self.requested:
            self.requested=True
            return ActionDecision(ActionOutcome.RUNNING,(self.effect,))
        if results and results[-1].phase in BAD:
            return ActionDecision(ActionOutcome.FAILED,error=results[-1].reason or results[-1].phase.value)
        if results and results[-1].phase is EffectPhase.COMPLETED and self.expected(world):
            return ActionDecision(ActionOutcome.SUCCEEDED,result={'confirmed':'command and fresh authenticated state','physical_arrival_claim':False})
        return ActionDecision(ActionOutcome.RUNNING,feedback={'command_phase':None if not results else results[-1].phase.value})
    def exit(self,world,reason):return ExitDecision(True)


class CommonFactory(ContextFactory):
    def __init__(self,name):self.name=name
    def validate_context(self,p,world,ctx):
        metadata=to_json_value(ctx.metadata) or {};state=world.vehicle
        if self.name=='SetMode':
            if p.mode not in metadata['mode_ids']:raise ValueError('mode absent from audited vehicle profile')
            if ctx.target_kind=='copter' and p.mode in ('RTL','LAND') or ctx.target_kind=='rover' and p.mode=='RTL':
                raise ValueError('use the native Goal Action; configuration alone cannot release its motion claim')
            if ctx.target_kind=='plane' and p.mode=='TAKEOFF':raise ValueError('use Takeoff Goal to observe physical climb')
            if ctx.target_kind=='plane' and p.mode=='AUTOLAND':raise ValueError('use AutoLand Goal to observe touchdown')
        elif self.name in ('Arm','Disarm'):
            target=self.name=='Arm'
            if state.operation.armed==target:raise ValueError('unexpected initial arm state; no implicit success')
            if not target and ctx.target_kind in ('plane','copter'):
                if ctx.home is None or abs(state.reported_pose.value.position.z-ctx.home.position.z)>.25 or speed(world)>(1 if ctx.target_kind=='plane' else .15):
                    raise ValueError('fresh stationary ground reference required; airborne Disarm forbidden')
    def start_with_context(self,p,world,ctx):
        self.validate_context(p,world,ctx)
        if self.name=='SetMode':
            number=to_json_value(ctx.metadata)['mode_ids'][p.mode]
            return CommandInstance(ModeEffect(p.mode),lambda w:w.vehicle.operation.native_mode==f'ARDUPILOT_CUSTOM_{number}')
        armed=self.name=='Arm'
        return CommandInstance(ArmEffect() if armed else DisarmEffect(),lambda w:w.vehicle.operation.armed==armed)


class QueryFactory(ContextFactory):
    def start_with_context(self,p,world,ctx):return QueryInstance(ctx)


class QueryInstance:
    def __init__(self,ctx):self.ctx=ctx
    def tick(self,world):
        return ActionDecision(ActionOutcome.SUCCEEDED,result={'target':self.ctx.target_id,'kind':self.ctx.target_kind,
            'world':to_json_value(world),'home':to_json_value(self.ctx.home),
            'context':to_json_value(self.ctx.metadata),'read_only':True})
    def exit(self,world,reason):return ExitDecision(True)


def speed(world):
    t=world.vehicle.reported_twist.value.linear
    return math.sqrt(t.x*t.x+t.y*t.y+t.z*t.z)


def ground(world,ground_z=0):
    return abs(world.vehicle.reported_pose.value.position.z-ground_z)<.25 and speed(world)<1


class NativeGoal(CommandInstance):
    """Mode adoption is necessary; physical completion is independently sampled."""
    def __init__(self,mode,number,predicate,*,settle_s=2,disarm=False):
        super().__init__(ModeEffect(mode),lambda w:w.vehicle.operation.native_mode==f'ARDUPILOT_CUSTOM_{number}')
        self.predicate=predicate;self.stable=None;self.settle_ns=int(settle_s*1e9);self.disarm=disarm;self.disarm_index=None
    def tick_with_results(self,world,results):
        if not self.requested:return super().tick_with_results(world,results)
        if any(r.phase in BAD for r in results):return ActionDecision(ActionOutcome.FAILED,error='native command failed or uncertain')
        now=world.published_at.monotonic_ns
        adopted=bool(results and results[0].phase is EffectPhase.COMPLETED)
        good=adopted and self.predicate(world)
        self.stable=(self.stable if self.stable is not None else now) if good else None
        settled=self.stable is not None and now-self.stable>=self.settle_ns
        if settled and self.disarm and world.vehicle.operation.armed:
            if self.disarm_index is None:
                self.disarm_index=len(results)
                return ActionDecision(ActionOutcome.RUNNING,(DisarmEffect(),),feedback={'stage':'ground disarm'})
            return ActionDecision(ActionOutcome.RUNNING)
        if settled and (not self.disarm or not world.vehicle.operation.armed and (self.disarm_index is None or
                        len(results)>self.disarm_index and results[self.disarm_index].phase is EffectPhase.COMPLETED)):
            return ActionDecision(ActionOutcome.SUCCEEDED,result={'physical_goal_observed':True,'armed':world.vehicle.operation.armed})
        return ActionDecision(ActionOutcome.RUNNING,feedback={'mode_confirmed':adopted,'physical_goal':good,
            'height_m':world.vehicle.reported_pose.value.position.z,'speed_mps':speed(world)})

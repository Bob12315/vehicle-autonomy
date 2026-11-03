"""Rover's audited body-forward/reverse and yaw-rate setpoints."""
from dataclasses import dataclass, field, replace
import math

from vehicle_autonomy.actions.common.stream import StreamFactory, StreamInstance
from vehicle_autonomy.actions.common.basic import STOP_TIMEOUT_NS, STOP_SETTLE_NS
from vehicle_autonomy.contracts.core.geometry import Twist3, Vector3
from vehicle_autonomy.contracts.effects.vehicle import TwistTargetEffect
from vehicle_autonomy.contracts.effects.vehicle import StopMotionEffect,ModeEffect
from vehicle_autonomy.contracts.decision import ExitDecision
from vehicle_autonomy.actions.common.standard import NativeGoal, ContextFactory, BAD, speed
from vehicle_autonomy.contracts.decision import ActionDecision, ActionOutcome, EffectPhase
from vehicle_autonomy.actions.copter.standard import BasicFactory, BasicFeedback


class RoverGotoFeedback(BasicFeedback):
    """Keep the existing stop proof, with native HOLD braking after zeroing."""
    def __init__(self,instance):
        super().__init__(instance)
        self.hold_index=None

    def exit(self,world,reason):return self.exit_with_results(world,reason,())

    def exit_with_results(self,world,reason,results):
        if self.hold_index is not None:
            hold=results[self.hold_index:self.hold_index+1]
            if hold and hold[0].phase in BAD:
                raise RuntimeError('rover_goto_hold_unconfirmed')
            # The original barrier must still inspect the StopMotion result,
            # never mistake an ACK/completed mode request for physical stopping.
            original=results[:self.hold_index]+results[self.hold_index+1:]
            decision=super().exit_with_results(world,reason,original)
            confirmed=bool(hold and hold[0].phase is EffectPhase.COMPLETED and
                           world.vehicle.operation.native_mode=='ARDUPILOT_CUSTOM_4')
            return ExitDecision(decision.complete and confirmed,decision.effects)
        decision=super().exit_with_results(world,reason,results)
        if any(isinstance(effect,StopMotionEffect) for effect in decision.effects):
            self.hold_index=len(results)+len(decision.effects)
            return ExitDecision(False,decision.effects+(ModeEffect('HOLD'),))
        return decision


class RoverGotoFactory(BasicFactory):
    def __init__(self):super().__init__('goto')
    def start_with_context(self,p,world,ctx):
        return RoverGotoFeedback(super().start_with_context(p,world,ctx).instance)


@dataclass(frozen=True,slots=True)
class DriveParameters:
    speed_mps: float=field(default=.3,metadata={'minimum':-.5,'maximum':.5})
    yaw_rate_rad_s: float=field(default=0.,metadata={'minimum':-.35,'maximum':.35})


@dataclass(frozen=True,slots=True)
class TurnParameters:
    yaw_rate_rad_s: float=field(default=.35,metadata={'minimum':-.35,'maximum':.35})


class RoverStream(StreamInstance):
    def __init__(self,*args):
        super().__init__(*args)
        self.neutral_since=None;self.neutral_stable=None
        self.neutral_boundary=None
        self.neutral_confirmed=False
        self.hold_index=None

    def update_input(self,parameters):
        super().update_input(parameters)
        self.refresh_ns=0

    def tick_with_results(self,world,results):
        decision=super().tick_with_results(world,results)
        if decision.outcome is not ActionOutcome.RUNNING:return decision
        neutral=(self.parameters.yaw_rate_rad_s==0 and (self.operation!='Drive' or self.parameters.speed_mps==0))
        now=world.published_at.monotonic_ns
        if not neutral:
            self.neutral_since=self.neutral_stable=None
            self.neutral_boundary=None
            self.neutral_confirmed=False
            return replace(decision,feedback=dict(stage='driving',stream_id=self.stream))
        if self.neutral_since is None:self.neutral_since=now;self.neutral_boundary=now
        stamp=world.localization.twist.captured_at.monotonic_ns
        fresh=stamp>self.neutral_boundary
        steady=fresh and self._steady(world)
        if self.neutral_confirmed and not steady:
            self.neutral_since=now;self.neutral_boundary=now;self.neutral_confirmed=False
        self.neutral_stable=(self.neutral_stable if self.neutral_stable is not None else stamp) if steady else None
        # Reuse the original full stop deadline AND continuous settling period.
        # Two seconds is a settling duration, not a new response deadline.
        confirmed=self.neutral_stable is not None and stamp-self.neutral_stable>=STOP_SETTLE_NS
        self.neutral_confirmed=confirmed
        if not confirmed and now-self.neutral_since>=STOP_TIMEOUT_NS:
            return ActionDecision(ActionOutcome.FAILED,error='rover_zero_velocity_stop_unconfirmed; safety HOLD required',
                feedback={'stage':'safety HOLD braking','stream_id':self.stream})
        return replace(decision,feedback=dict(stage='zero velocity hold' if confirmed else 'zero velocity stopping',
            physical_stop_observed=confirmed,stream_id=self.stream))

    def setpoint(self):
        return TwistTargetEffect('base_link',Twist3(Vector3(self.parameters.speed_mps if self.operation=='Drive' else 0,0,0),
            Vector3(0,0,self.parameters.yaw_rate_rad_s)),self.stream)
    def exit_with_results(self,world,reason,results):
        if self.hold_index is not None:
            hold=results[self.hold_index:self.hold_index+1]
            if hold and hold[0].phase in BAD:raise RuntimeError('rover_drive_hold_unconfirmed')
            original=results[:self.hold_index]+results[self.hold_index+1:]
            decision=super().exit_with_results(world,reason,original)
            confirmed=bool(hold and hold[0].phase is EffectPhase.COMPLETED and
                world.vehicle.operation.native_mode=='ARDUPILOT_CUSTOM_4')
            return ExitDecision(decision.complete and confirmed,decision.effects)
        decision=super().exit_with_results(world,reason,results)
        if any(isinstance(effect,StopMotionEffect) for effect in decision.effects):
            # Zero the old stream before requesting AP's audited native HOLD.
            # This avoids relying on slow Guided speed-controller integral
            # decay. Existing 8 s / 0.1 m/s / 2 s stop limits are unchanged.
            self.hold_index=len(results)+len(decision.effects)
            return ExitDecision(False,decision.effects+(ModeEffect('HOLD'),))
        return decision


class RoverStreamFactory(StreamFactory):
    def start_with_context(self,p,world,ctx):
        self.validate_context(p,world,ctx);return RoverStream(self.name,p,world,ctx)


class RoverReturnGoal(NativeGoal):
    """Native RTL approach, then explicit HOLD and post-braking arrival proof."""
    def __init__(self,number,home):
        super().__init__('RTL',number,lambda w:False)
        self.home=home;self.stop_index=None

    def tick_with_results(self,world,results):
        if not self.requested:return super().tick_with_results(world,results)
        if any(r.phase in BAD for r in results):
            return ActionDecision(ActionOutcome.FAILED,error='native return/stop failed or uncertain')
        p=world.vehicle.reported_pose.value.position
        distance=math.hypot(p.x-self.home.x,p.y-self.home.y)
        if self.stop_index is None:
            if results and results[0].phase is EffectPhase.COMPLETED and distance<=.5:
                self.stop_index=len(results)
                return ActionDecision(ActionOutcome.RUNNING,(ModeEffect('HOLD'),),feedback={'stage':'home HOLD braking','home_distance_m':distance})
            return ActionDecision(ActionOutcome.RUNNING,feedback={'stage':'native RTL approach','home_distance_m':distance})
        stopped=(len(results)>self.stop_index and results[self.stop_index].phase is EffectPhase.COMPLETED
                 and world.vehicle.operation.native_mode=='ARDUPILOT_CUSTOM_4' and distance<=.75 and speed(world)<=.1)
        now=world.published_at.monotonic_ns
        self.stable=(self.stable if self.stable is not None else now) if stopped else None
        if self.stable is not None and now-self.stable>=self.settle_ns:
            return ActionDecision(ActionOutcome.SUCCEEDED,result={'physical_goal_observed':True,'armed':world.vehicle.operation.armed})
        return ActionDecision(ActionOutcome.RUNNING,feedback={'stage':'post-HOLD home and stop confirmation','home_distance_m':distance,'speed_mps':speed(world)})


class RoverStopFactory(ContextFactory):
    def validate_context(self,p,world,ctx):
        if not world.vehicle.operation.armed:raise ValueError('armed Rover required')
    def start_with_context(self,p,world,ctx):
        self.validate_context(p,world,ctx)
        return RoverStopGoal(world.published_at.monotonic_ns)


class RoverStopGoal(NativeGoal):
    """Braking must not require switching an already held Rover to GUIDED."""
    def __init__(self,started_ns):
        super().__init__('HOLD',4,lambda w:w.vehicle.operation.native_mode=='ARDUPILOT_CUSTOM_4'
            and w.vehicle.reported_twist.captured_at.monotonic_ns>started_ns and speed(w)<=.1)
    def tick_with_results(self,world,results):
        decision=super().tick_with_results(world,results)
        return replace(decision,result={'physical_goal_observed':True}) if decision.outcome is ActionOutcome.SUCCEEDED else decision

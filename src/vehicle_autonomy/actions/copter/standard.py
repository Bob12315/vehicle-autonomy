"""Copter standalone factories compose the existing basic Action stop barrier."""
from dataclasses import dataclass, field, replace
import math
from uuid import uuid4

from vehicle_autonomy.actions.common.basic import BasicAction, BasicInstance, BasicParameters, yaw, BAD
from vehicle_autonomy.actions.common.standard import ContextFactory
from vehicle_autonomy.contracts.core.geometry import Pose3, Quaternion, Twist3, Vector3
from vehicle_autonomy.contracts.decision import ActionDecision, ActionOutcome
from vehicle_autonomy.contracts.effects.vehicle import PoseTargetEffect, TwistTargetEffect
from vehicle_autonomy.world.environment.resources import ResolvedTarget


@dataclass(frozen=True,slots=True)
class TakeoffParameters:
    height_m: float=field(default=1.5,metadata={'exclusiveMinimum':0,'maximum':50})


@dataclass(frozen=True,slots=True)
class GotoParameters:
    x_m: float=field(metadata={'minimum':-15,'maximum':15})
    y_m: float=field(metadata={'minimum':-15,'maximum':15})
    z_m: float=field(default=1.5,metadata={'minimum':0,'maximum':2})


@dataclass(frozen=True,slots=True)
class VelocityParameters:
    vx_mps: float=field(default=0.,metadata={'minimum':-.5,'maximum':.5})
    vy_mps: float=field(default=0.,metadata={'minimum':-.5,'maximum':.5})
    vz_mps: float=field(default=0.,metadata={'minimum':-.3,'maximum':.3})
    yaw_rate_rad_s: float=field(default=0.,metadata={'minimum':-.35,'maximum':.35})


@dataclass(frozen=True,slots=True)
class YawParameters:
    yaw_rad: float=field(metadata={'minimum':-math.pi,'maximum':math.pi})


class BasicFactory(ContextFactory):
    def __init__(self,name):self.name=name
    def validate_context(self,p,world,ctx):
        if self.name=='takeoff' and (not world.vehicle.operation.armed or not 0<p.height_m<=2):
            raise ValueError('armed Copter and audited takeoff height <=2 m required')
        if self.name not in ('arm','disarm') and not world.vehicle.operation.armed:raise ValueError('armed vehicle required')
        if world.environment is None:raise ValueError('bound simulation environment required')
        if self.name!='land' and world.vehicle.operation.native_mode!='ARDUPILOT_CUSTOM_'+('15' if ctx.target_kind=='rover' else '4'):
            raise ValueError('observed GUIDED mode required')
    def start_with_context(self,p,world,ctx):
        self.validate_context(p,world,ctx)
        target=None
        if self.name in ('goto','return_home','land'):
            position=(Vector3(p.x_m,p.y_m,0 if ctx.target_kind=='rover' else p.z_m) if self.name=='goto' else ctx.home.position)
            target=ResolvedTarget('action-target','odom',position,world.environment)
        return BasicFeedback(BasicAction(self.name).start(BasicParameters(ctx.target_kind,world.environment,target,
            height_m=p.height_m if self.name=='takeoff' else 1.5,timeout_ns=45_000_000_000),world))


class BasicFeedback:
    def __init__(self,instance):self.instance=instance
    def tick(self,world):return self.tick_with_results(world,())
    def tick_with_results(self,world,results):
        decision=self.instance.tick_with_results(world,results)
        return replace(decision,result={'physical_goal_observed':True} if decision.outcome is ActionOutcome.SUCCEEDED else decision.result,
            feedback={'stage':self.instance.stage,'height_m':world.vehicle.reported_pose.value.position.z})
    def exit(self,world,reason):return self.instance.exit(world,reason)
    def exit_with_results(self,world,reason,results):return self.instance.exit_with_results(world,reason,results)


class StreamInstance(BasicInstance):
    """Existing finite stop barrier; periodic setpoints are not physical success."""
    def __init__(self,name,p,world,ctx):
        super().__init__('hold',BasicParameters(ctx.target_kind,world.environment,timeout_ns=45_000_000_000),world)
        self.operation=name;self.parameters=p;self.stable=None
        self.stream='standalone:'+uuid4().hex
        if name=='SetYaw':
            q=Quaternion(0,0,math.sin(p.yaw_rad/2),math.cos(p.yaw_rad/2))
            self.pose=Pose3(self.pose.position,q)
    def tick_with_results(self,world,results):
        error=self._world_error(world,True)
        if error:return ActionDecision(ActionOutcome.FAILED,error=error)
        if not world.vehicle.operation.armed:return ActionDecision(ActionOutcome.FAILED,error='vehicle disarmed')
        if world.vehicle.operation.native_mode!='ARDUPILOT_CUSTOM_'+('15' if self.p.vehicle_kind=='rover' else '4'):
            return ActionDecision(ActionOutcome.FAILED,error='GUIDED state required')
        if results and results[-1].phase in BAD:return ActionDecision(ActionOutcome.FAILED,error=results[-1].reason or 'stream rejected')
        now=world.published_at.monotonic_ns
        if self.operation=='SetYaw':
            angle=math.atan2(math.sin(yaw(world.localization.pose.value)-self.parameters.yaw_rad),math.cos(yaw(world.localization.pose.value)-self.parameters.yaw_rad))
            good=abs(angle)<=.1 and self._steady(world)
            self.stable=(self.stable if self.stable is not None else now) if good else None
            if self.stable is not None and now-self.stable>=1_000_000_000:
                return ActionDecision(ActionOutcome.SUCCEEDED,result={'yaw_rad':yaw(world.localization.pose.value)})
        if now>=self.refresh_ns:
            self.touched=True;self.refresh_ns=now+300_000_000
            effect=self.setpoint()
            return ActionDecision(ActionOutcome.RUNNING,(effect,),feedback={'operation':self.operation,'stream_id':self.stream})
        return ActionDecision(ActionOutcome.RUNNING)
    def setpoint(self):
        p=self.parameters
        if self.operation in ('Hold','SetYaw'):return PoseTargetEffect('odom',self.pose,self.stream)
        return TwistTargetEffect('odom',Twist3(Vector3(p.vx_mps,p.vy_mps,p.vz_mps),Vector3(0,0,p.yaw_rate_rad_s)),self.stream)


class StreamFactory(ContextFactory):
    def __init__(self,name):self.name=name
    def validate_context(self,p,world,ctx):
        if not world.vehicle.operation.armed or world.localization is None or world.environment is None:
            raise ValueError('armed localized vehicle with bound environment required')
        if world.vehicle.operation.native_mode!='ARDUPILOT_CUSTOM_'+('15' if ctx.target_kind=='rover' else '4'):
            raise ValueError('observed GUIDED mode required')
    def start_with_context(self,p,world,ctx):
        self.validate_context(p,world,ctx);return StreamInstance(self.name,p,world,ctx)

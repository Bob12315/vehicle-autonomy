"""Copter standalone factories compose the existing basic Action stop barrier."""
from dataclasses import dataclass, field, replace
import math
from uuid import uuid4
from typing import Literal

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
    frame: Literal['odom','base_link']=field(default='odom',metadata={'description':'odom ENU or body-relative base_link FLU; SI units'})


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


# Public compatibility imports; Rover and Copter share a helper, never another
# running Action's state or a vehicle port.
from vehicle_autonomy.actions.common.stream import StreamFactory, StreamInstance

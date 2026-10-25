"""Shared setpoint lifecycle helpers; factories still declare vehicle semantics."""
from dataclasses import replace
import math
from uuid import uuid4
from vehicle_autonomy.actions.common.basic import BasicInstance, BasicParameters, yaw, BAD
from vehicle_autonomy.actions.common.standard import ContextFactory
from vehicle_autonomy.contracts.core.geometry import Pose3, Quaternion, Twist3, Vector3
from vehicle_autonomy.contracts.decision import ActionDecision, ActionOutcome
from vehicle_autonomy.contracts.effects.vehicle import PoseTargetEffect, TwistTargetEffect


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
        return TwistTargetEffect(p.frame,Twist3(Vector3(p.vx_mps,p.vy_mps,p.vz_mps),Vector3(0,0,p.yaw_rate_rad_s)),self.stream)

    def update_input(self,parameters):
        if self.operation not in ('Drive','Turn','SetVelocity') or type(parameters) is not type(self.parameters):
            raise ValueError('this Continuous Action does not accept input updates')
        self.parameters=parameters


class StreamFactory(ContextFactory):
    def __init__(self,name):self.name=name
    @property
    def supports_input_updates(self):return self.name in ('Drive','Turn','SetVelocity')
    def validate_context(self,p,world,ctx):
        if not world.vehicle.operation.armed or world.localization is None or world.environment is None:
            raise ValueError('armed localized vehicle with bound environment required')
        if world.vehicle.operation.native_mode!='ARDUPILOT_CUSTOM_'+('15' if ctx.target_kind=='rover' else '4'):
            raise ValueError('observed GUIDED mode required')
    def start_with_context(self,p,world,ctx):
        self.validate_context(p,world,ctx);return StreamInstance(self.name,p,world,ctx)

"""Rover's audited body-forward/reverse and yaw-rate setpoints."""
from dataclasses import dataclass, field

from vehicle_autonomy.actions.copter.standard import StreamFactory, StreamInstance
from vehicle_autonomy.contracts.core.geometry import Twist3, Vector3
from vehicle_autonomy.contracts.effects.vehicle import TwistTargetEffect
from vehicle_autonomy.contracts.effects.vehicle import StopMotionEffect,ModeEffect
from vehicle_autonomy.contracts.decision import ExitDecision


@dataclass(frozen=True,slots=True)
class DriveParameters:
    speed_mps: float=field(default=.3,metadata={'minimum':-.5,'maximum':.5})
    yaw_rate_rad_s: float=field(default=0.,metadata={'minimum':-.35,'maximum':.35})


@dataclass(frozen=True,slots=True)
class TurnParameters:
    yaw_rate_rad_s: float=field(default=.35,metadata={'minimum':-.35,'maximum':.35})


class RoverStream(StreamInstance):
    def setpoint(self):
        return TwistTargetEffect('base_link',Twist3(Vector3(self.parameters.speed_mps if self.operation=='Drive' else 0,0,0),
            Vector3(0,0,self.parameters.yaw_rate_rad_s)),self.stream)
    def exit_with_results(self,world,reason,results):
        decision=super().exit_with_results(world,reason,results)
        if any(isinstance(effect,StopMotionEffect) for effect in decision.effects):
            # Zero the old stream before requesting AP's audited native HOLD.
            # This avoids relying on slow Guided speed-controller integral
            # decay. Existing 8 s / 0.1 m/s / 2 s stop limits are unchanged.
            return ExitDecision(False,decision.effects+(ModeEffect('HOLD'),))
        return decision


class RoverStreamFactory(StreamFactory):
    def start_with_context(self,p,world,ctx):
        self.validate_context(p,world,ctx);return RoverStream(self.name,p,world,ctx)

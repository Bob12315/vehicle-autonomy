"""Native fixed-wing operations; never hover, zero velocity or airborne Disarm."""
from dataclasses import dataclass, field
import math

from vehicle_autonomy.actions.common.standard import CommandInstance, ContextFactory, NativeGoal, ground, speed
from vehicle_autonomy.contracts.core.geometry import GeoPoint
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.effects.vehicle import FixedWingTargetEffect, ModeEffect


@dataclass(frozen=True,slots=True)
class GuidedTargetParameters:
    latitude_deg: float=field(metadata={'minimum':-90,'maximum':90})
    longitude_deg: float=field(metadata={'minimum':-180,'maximum':180})
    altitude_amsl_m: float=field(metadata={'description':'Explicit AMSL metres; audited 20..140 m above home'})


class PlaneFactory(ContextFactory):
    def __init__(self,name):self.name=name
    def validate_context(self,p,world,ctx):
        state=world.vehicle
        if ctx.home is None:raise ValueError('ground reference from this owner\'s completed Arm required')
        if not state.operation.armed:raise ValueError('armed Plane required')
        if self.name=='Takeoff':
            if p.height_m!=50:raise ValueError('owned Plane TKOFF_ALT verified at 50 m; cannot silently alter it')
            if abs(state.reported_pose.value.position.z)>1.5 or speed(world)>1:raise ValueError('stationary ground takeoff required')
        elif state.reported_pose.value.position.z<10:raise ValueError('fresh airborne fixed-wing state required')
    def start_with_context(self,p,world,ctx):
        self.validate_context(p,world,ctx);modes=to_json_value(ctx.metadata)['mode_ids']
        if self.name=='Takeoff':
            return NativeGoal('TAKEOFF',modes['TAKEOFF'],lambda w:abs(w.vehicle.reported_pose.value.position.z-50)<=5 and 8<=speed(w)<=28)
        if self.name=='AutoLand':return NativeGoal('AUTOLAND',modes['AUTOLAND'],lambda w:ground(w,ctx.home.position.z),settle_s=3,disarm=True)
        if self.name=='SetGuidedTarget':
            effect=FixedWingTargetEffect(GeoPoint(p.latitude_deg,p.longitude_deg,p.altitude_amsl_m))
            return CommandInstance(effect,lambda w:w.vehicle.operation.native_mode==f'ARDUPILOT_CUSTOM_{modes["GUIDED"]}')
        mode={'Loiter':'LOITER','RTL':'RTL'}[self.name]
        return CommandInstance(ModeEffect(mode),lambda w:w.vehicle.operation.native_mode==f'ARDUPILOT_CUSTOM_{modes[mode]}')

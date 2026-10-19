"""Versioned navigation geometry/limits, injected by composition, ROS-free."""
from dataclasses import asdict,dataclass
import hashlib
import json
import math


@dataclass(frozen=True,slots=True)
class VehicleNavigationModel:
    model_id: str
    revision: int
    reference_point: str
    base_to_reference_x_m: float
    footprint_radius_m: float
    path_clearance_m: float
    cross_track_m: float
    max_speed_mps: float
    max_yaw_rate_rps: float
    capabilities: tuple[str,...] = ('arm','disarm','hold','navigation','stop')
    motion_effects: tuple[str,...] = ('TwistTargetEffect','StopMotionEffect')

    def __post_init__(self):
        if not self.model_id or type(self.revision) is not int or self.revision<1 or not self.reference_point:
            raise ValueError('explicit navigation model identity/version/reference required')
        for key in ('base_to_reference_x_m','footprint_radius_m','path_clearance_m','cross_track_m','max_speed_mps','max_yaw_rate_rps'):
            value=getattr(self,key)
            if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('finite SI navigation limits required')
        if not -.5<=self.base_to_reference_x_m<=.5 or not .2<=self.footprint_radius_m<=1:
            raise ValueError('unsupported Rover geometry')
        if not .05<=self.cross_track_m<=.15 or not self.footprint_radius_m+self.cross_track_m+.08-1e-9<=self.path_clearance_m<=1.5:
            raise ValueError('navigation clearance must cover geometry and tracking error')
        if not 0<self.max_speed_mps<=.18 or not .15<=self.max_yaw_rate_rps<=.25:
            raise ValueError('model exceeds audited motion envelope')
        if self.motion_effects!=('TwistTargetEffect','StopMotionEffect') or self.capabilities!=('arm','disarm','hold','navigation','stop'):
            raise ValueError('unreviewed navigation capabilities/effects')

    def document(self):
        d=asdict(self);d['capabilities']=sorted(self.capabilities);d['motion_effects']=list(self.motion_effects)
        return d

    @property
    def sha256(self):return hashlib.sha256(json.dumps(self.document(),sort_keys=True,separators=(',',':')).encode()).hexdigest()


FRONT_AXLE=VehicleNavigationModel('target_rover_front_axle_v1',1,'front_drive_axle',.25,.72,.95,.15,.18,.25)
COMPACT_AXLE=VehicleNavigationModel('compact_rover_front_axle_v1',1,'front_drive_axle',.18,.65,.95,.15,.18,.25)
MODELS={m.model_id:m for m in (FRONT_AXLE,COMPACT_AXLE)}


def resolve_model(model_id):
    if type(model_id) is not str or model_id not in MODELS:raise ValueError('unregistered navigation model')
    return MODELS[model_id]

DEPLOYMENT_PROFILES={FRONT_AXLE.model_id:'simulation-rover',COMPACT_AXLE.model_id:'simulation-compact-rover'}

"""Pinned data prerequisites for a native Rover navigation Action.

This is a data-only check. It grants neither vehicle SEND nor resource release.
The caller propagates the returned earliest expiry into ActionDecision.
"""
from dataclasses import dataclass
from math import hypot
from vehicle_autonomy.contracts.streams import DataKind,SourceKind,SampleHeader
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.time import TimePoint


class NavigationEvidenceUnavailable(ValueError):
    pass


@dataclass(frozen=True,slots=True)
class NavigationInput:
    header: SampleHeader
    max_age_ns: int
    def __post_init__(self):
        if not isinstance(self.header,SampleHeader) or type(self.max_age_ns) is not int or self.max_age_ns<=0:raise ValueError('explicit typed source/age prerequisite required')
        if self.header.source_kind is not SourceKind.SIMULATION:raise ValueError('owned simulation navigation cannot consume replay/truth')
        caps={DataKind.SCAN:300_000_000,DataKind.SLAM_POSE:500_000_000,DataKind.TRANSFORM:500_000_000,DataKind.MAP:10_000_000_000}
        if self.header.kind not in caps or self.max_age_ns>caps[self.header.kind]:raise ValueError('navigation input age exceeds qualified profile')
    def identity(self,h):
        p=self.header
        return (h.source_id,h.sensor_id,h.kind,h.generation,h.source_clock_domain,h.frame,h.calibration_version,h.source_kind)==(p.source_id,p.sensor_id,p.kind,p.generation,p.source_clock_domain,p.frame,p.calibration_version,p.source_kind)


class RoverNavigationInputs:
    def __init__(self,*,world_generation,vehicle_session,requirements):
        if not isinstance(world_generation,str) or not world_generation or not isinstance(vehicle_session,str) or not vehicle_session:raise ValueError('explicit vehicle/world session required')
        if not isinstance(requirements,tuple) or len(requirements)!=4 or not all(isinstance(x,NavigationInput) for x in requirements):raise ValueError('four immutable native navigation prerequisites required')
        if {r.header.kind for r in requirements}!={DataKind.SCAN,DataKind.SLAM_POSE,DataKind.TRANSFORM,DataKind.MAP}:raise ValueError('scan, native pose, map and transform required')
        scan=next(r.header for r in requirements if r.header.kind is DataKind.SCAN)
        native=[r.header for r in requirements if r.header.kind is not DataKind.SCAN]
        if scan.frame.frame_id!='laser' or scan.frame.convention!='FLU' or scan.frame.origin_id!=world_generation:raise ValueError('scan must belong to this calibrated AP/world frame epoch')
        if len({(h.source_id,h.generation,h.source_clock_domain,h.frame,h.calibration_version) for h in native})!=1 or any(h.frame.frame_id!='map' or h.frame.convention!='ENU' for h in native):raise ValueError('native map/pose/transform must share one trusted map epoch')
        if any(h.calibration_version!=scan.calibration_version for h in native):raise ValueError('native and sensor calibration mismatch')
        self.map_epoch=native[0].frame.origin_id
        self.world_generation=world_generation;self.vehicle_session=vehicle_session;self.requirements=requirements
    @staticmethod
    def _expiry(captured,now,age):
        if not isinstance(captured,TimePoint) or captured.clock_domain_id!=now.clock_domain_id or not 0<=now.monotonic_ns-captured.monotonic_ns<age:raise NavigationEvidenceUnavailable('navigation evidence missing/expired/clock mismatch: age_ns='+str(None if captured is None else now.monotonic_ns-captured.monotonic_ns)+' limit_ns='+str(age))
        return captured.monotonic_ns+age
    def validate(self,world,now):
        if not isinstance(now,TimePoint) or world is None or str(world.version.generation_id)!=self.world_generation:raise ValueError('navigation world generation changed')
        v=world.vehicle
        if v is None or v.telemetry is None or str(v.telemetry.link_session_id)!=self.vehicle_session or v.health.quality is not QualityState.VALID:raise ValueError('authenticated vehicle session/state unavailable')
        if not v.operation.armed or v.operation.native_mode!='ARDUPILOT_CUSTOM_15':raise ValueError('observed armed Rover GUIDED required')
        deadlines=[]
        for field in (v.reported_pose,v.reported_twist):
            if field is None:raise ValueError('signed AP pose/twist unavailable')
            deadlines.append(self._expiry(field.captured_at,now,200_000_000))
        twist=v.reported_twist.value
        if hypot(twist.linear.x,twist.linear.y)>.4 or abs(twist.angular.z)>.45:raise ValueError('observed Rover motion exceeds conservative scan halo qualification')
        for requirement in self.requirements:
            matches=[s for s in world.streams if requirement.identity(s.header)]
            if len(matches)!=1:raise NavigationEvidenceUnavailable('pinned native navigation stream missing/ambiguous: '+requirement.header.kind.value)
            h=matches[0].header
            if h.quality is not QualityState.VALID or h.captured_at is None:raise ValueError('navigation source quality unavailable')
            if h.received_at.clock_domain_id!=now.clock_domain_id or not h.captured_at<=h.received_at<=now:raise ValueError('navigation source receipt chronology invalid')
            deadlines.append(self._expiry(h.captured_at,now,requirement.max_age_ns))
        return min(deadlines)

"""Finite Rover maneuver Action. Emits typed Effects; no device/ROS capability."""
from dataclasses import dataclass
import math
from uuid import uuid4

from actions.basic import yaw, failed, BAD, WRITTEN
from contracts.core.geometry import Twist3, Vector3
from contracts.core.quality import QualityState
from contracts.decision import ActionSpec, ActionDecision, ActionOutcome, ExitDecision
from contracts.effects.vehicle import TwistTargetEffect, StopMotionEffect
from contracts.world.models import ResourceReference
from guidance.path_following import drive_reference, angle
from planning.models import Pose2D


@dataclass(frozen=True,slots=True)
class ManeuverParameters:
    environment: ResourceReference
    kind: str
    start: Pose2D
    end: Pose2D
    path: tuple[Pose2D,...]
    speed_mps: float = .15
    turn_rad: float = 0.
    radius_m: float = 0.
    duration_s: float = 0.
    timeout_ns: int = 90_000_000_000

    def __post_init__(self):
        if self.kind not in ('drive','visit','turn','circle','wait'):raise ValueError('unknown finite maneuver')
        if (type(self.timeout_ns) is not int or not 0<self.timeout_ns<=300_000_000_000
                or not 0<self.speed_mps<=.18 or not math.isfinite(self.speed_mps)
                or not all(math.isfinite(v) for v in (self.turn_rad,self.radius_m,self.duration_s))
                or abs(self.turn_rad)>6*math.pi+1e-8 or not 0<=self.duration_s<=30
                or not isinstance(self.path,tuple) or not 2<=len(self.path)<=4096):
            raise ValueError('bounded immutable maneuver required')
        if self.kind=='circle' and not 1.5<=self.radius_m<=3:raise ValueError('qualified circle radius is 1.5..3 m')


SPEC=ActionSpec('scenario.maneuver',ManeuverParameters,frozenset({'navigation','stop'}),
                (TwistTargetEffect,StopMotionEffect),1_000_000_000)


class ManeuverAction:
    def start(self,parameters,snapshot):return ManeuverInstance(parameters,snapshot)


class ManeuverInstance:
    def __init__(self,p,snapshot):
        self.p=p;self.start_ns=snapshot.published_at.monotonic_ns
        self.stream='maneuver:'+uuid4().hex;self.refresh_ns=0;self.touched=False
        self.last_capture=None;self.last_yaw=None;self.rotation=0.;self.stop_boundary=None
        self.initial_heading_error=None;self.stable_since=None;self.exit_ns=None
        self.last_polar=None;self.orbit=0.
        self.goal_alignment=False
        self.initial_alignment=p.kind=='visit';self.align_stop_boundary=None;self.align_stable=None

    def _pose(self,world):
        loc=world.localization
        if (world.environment!=self.p.environment or world.vehicle is None
                or world.vehicle.health.quality is not QualityState.VALID
                or loc is None or loc.twist is None or loc.quality is not QualityState.VALID):
            raise ValueError('maneuver_world_unavailable')
        if any(not 0<=world.published_at.elapsed_ns_since(s.captured_at)<=500_000_000 for s in (loc.pose,loc.twist)):
            raise ValueError('maneuver_localization_stale')
        pose=drive_reference(Pose2D(loc.pose.value.position.x,loc.pose.value.position.y,yaw(loc.pose.value)))
        if loc.pose.captured_at.monotonic_ns!=self.last_capture:
            if self.last_yaw is not None:self.rotation+=angle(pose.yaw-self.last_yaw)
            self.last_yaw=pose.yaw;self.last_capture=loc.pose.captured_at.monotonic_ns
        if self.initial_heading_error is None:self.initial_heading_error=angle(self.p.start.yaw-pose.yaw)
        return pose,loc.twist.value

    def _stopped(self,twist):
        return math.hypot(twist.linear.x,twist.linear.y)<=.05 and abs(twist.angular.z)<=.05

    def tick(self,world):return self.tick_with_results(world,())

    def tick_with_results(self,world,results):
        now=world.published_at.monotonic_ns
        if now-self.start_ns>self.p.timeout_ns:return failed('maneuver_deadline_exceeded')
        try:pose,twist=self._pose(world)
        except ValueError as exc:return failed(str(exc))
        if not world.vehicle.operation.armed or world.vehicle.operation.native_mode!='ARDUPILOT_CUSTOM_15':
            return failed('maneuver_requires_armed_guided')
        if self.stop_boundary is not None:
            feedback=results[self.stop_boundary:]
            steady=bool(feedback and feedback[-1].phase is not None and feedback[-1].phase.value=='COMPLETED') and self._stopped(twist)
            self.stable_since=(self.stable_since if self.stable_since is not None else now) if steady else None
            return ActionDecision(ActionOutcome.SUCCEEDED if self.stable_since is not None and now-self.stable_since>=500_000_000 else ActionOutcome.RUNNING)
        if self.align_stop_boundary is None and results and results[-1].phase in BAD:return failed(results[-1].reason or 'maneuver_effect_failed')
        p=self.p;v=0.;w=0.;arrived=False
        if self.initial_alignment:
            if math.hypot(p.end.x-pose.x,p.end.y-pose.y)<=.05:
                self.initial_alignment=False;self.goal_alignment=True
            elif self.align_stop_boundary is not None:
                feedback=results[self.align_stop_boundary:]
                if feedback and feedback[-1].phase in BAD:return failed('initial_alignment_stop_failed')
                steady=bool(feedback and feedback[-1].phase.value=='COMPLETED') and self._stopped(twist)
                self.align_stable=(self.align_stable if self.align_stable is not None else now) if steady else None
                if self.align_stable is not None and now-self.align_stable>=500_000_000:
                    self.initial_alignment=False;self.stream='maneuver:'+uuid4().hex
                    self.refresh_ns=0;self.touched=False;self.align_stop_boundary=None
                return ActionDecision(ActionOutcome.RUNNING)
            else:
                error=angle(math.atan2(p.end.y-pose.y,p.end.x-pose.x)-pose.yaw)
                dx,dy=p.start.x-pose.x,p.start.y-pose.y
                if abs(error)<=.07 and self._stopped(twist) and math.hypot(dx,dy)<=.1:
                    if not self.touched:
                        self.initial_alignment=False
                        return ActionDecision(ActionOutcome.RUNNING)
                    self.align_stop_boundary=len(results);self.touched=True
                    return ActionDecision(ActionOutcome.RUNNING,(StopMotionEffect(self.stream),))
                if now>=self.refresh_ns:
                    self.refresh_ns=now+200_000_000;self.touched=True
                    v=max(-.05,min(.05,.9*(dx*math.cos(pose.yaw)+dy*math.sin(pose.yaw))))
                    w=math.copysign(min(.25,max(.08,.8*abs(error))),error)
                    return ActionDecision(ActionOutcome.RUNNING,(TwistTargetEffect('base_link',Twist3(Vector3(v,0,0),Vector3(0,0,w)),self.stream),))
                return ActionDecision(ActionOutcome.RUNNING)
        if p.kind=='wait':arrived=now-self.start_ns>=p.duration_s*1e9
        elif p.kind=='turn':
            remaining=p.turn_rad+self.initial_heading_error-self.rotation
            dx,dy=p.start.x-pose.x,p.start.y-pose.y
            # A caster chassis has transient axle drift during a pivot. Keep
            # the approved axle point tethered using a small signed correction,
            # rather than rebasing the task or widening its 0.15 m fence.
            v=max(-.05,min(.05,.9*(dx*math.cos(pose.yaw)+dy*math.sin(pose.yaw))))
            arrived=abs(remaining)<=.07 and math.hypot(dx,dy)<=.10
            w=math.copysign(min(.25,max(.08,.8*abs(remaining))),remaining)
        elif p.kind in ('drive','visit'):
            dx,dy=p.end.x-pose.x,p.end.y-pose.y;distance=math.hypot(dx,dy)
            error=angle(math.atan2(dy,dx)-pose.yaw)
            # Leave room inside the unchanged 0.15 m writer fence for the
            # following pivot, whose caster transients can shift the axle.
            arrived=distance<=.05
            w=max(-.25,min(.25,1.2*error-.5*twist.angular.z))
            v=min(p.speed_mps,max(.025,.5*(distance-.015)))*max(0.,math.cos(error))**3 if abs(error)<.4 else 0.
            if abs(error)>.12 and abs(twist.angular.z)<.05 and abs(w)<.18:w=math.copysign(.18,error)
            if arrived:self.goal_alignment=True
            if self.goal_alignment:
                error=angle(p.end.yaw-pose.yaw)
                v=max(-.05,min(.05,.9*(dx*math.cos(pose.yaw)+dy*math.sin(pose.yaw))))
                w=math.copysign(min(.25,max(.08,.8*abs(error))),error)
                arrived=abs(error)<=.07 and distance<=.10
        elif p.kind=='circle':
            sign=1 if p.turn_rad>0 else -1
            cx=p.start.x-sign*p.radius_m*math.sin(p.start.yaw)
            cy=p.start.y+sign*p.radius_m*math.cos(p.start.yaw)
            radial=math.hypot(pose.x-cx,pose.y-cy)-p.radius_m
            tangent=math.atan2(pose.y-cy,pose.x-cx)+sign*math.pi/2
            polar=math.atan2(pose.y-cy,pose.x-cx)
            if self.last_polar is not None:self.orbit+=angle(polar-self.last_polar)
            self.last_polar=polar
            remaining=abs(p.turn_rad)-sign*self.orbit
            arrived=remaining<=.06 and math.hypot(pose.x-p.end.x,pose.y-p.end.y)<=.18
            v=min(p.speed_mps,max(.05,.5*max(0,remaining*p.radius_m)))
            error=angle(tangent+sign*math.atan2(1.2*radial,max(.1,v))-pose.yaw)
            w=max(-.25,min(.25,sign*v/p.radius_m+1.2*error-.25*twist.angular.z))
            if abs(error)>.5:v=0.
        if arrived and (not self.touched or results and results[-1].phase in WRITTEN):
            self.stop_boundary=len(results);self.touched=True
            return ActionDecision(ActionOutcome.RUNNING,(StopMotionEffect(self.stream),))
        if now>=self.refresh_ns:
            self.refresh_ns=now+200_000_000;self.touched=True
            return ActionDecision(ActionOutcome.RUNNING,(TwistTargetEffect('base_link',Twist3(Vector3(v,0,0),Vector3(0,0,w)),self.stream),))
        return ActionDecision(ActionOutcome.RUNNING)

    def exit(self,world,reason):return self.exit_with_results(world,reason,())

    def exit_with_results(self,world,reason,results):
        now=world.published_at.monotonic_ns
        if self.exit_ns is None:self.exit_ns=now
        if now-self.exit_ns>8_000_000_000:raise RuntimeError('maneuver_exit_stop_unconfirmed')
        if not self.touched:return ExitDecision(True)
        if self.stop_boundary is None and self.align_stop_boundary is not None:self.stop_boundary=self.align_stop_boundary
        if self.stop_boundary is None:
            self.stop_boundary=len(results)
            return ExitDecision(False,(StopMotionEffect(self.stream),))
        feedback=results[self.stop_boundary:]
        if feedback and feedback[-1].phase in BAD:raise RuntimeError('maneuver_exit_stop_rejected')
        try:_,twist=self._pose(world)
        except ValueError:return ExitDecision(False)
        steady=bool(feedback and feedback[-1].phase.value=='COMPLETED') and self._stopped(twist)
        self.stable_since=(self.stable_since if self.stable_since is not None else now) if steady else None
        return ExitDecision(self.stable_since is not None and now-self.stable_since>=500_000_000)

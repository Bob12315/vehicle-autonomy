"""Finite simulation Actions emitting only typed requests and reading results."""
from __future__ import annotations
from dataclasses import dataclass
import math
from uuid import uuid4
from contracts.core.geometry import Pose3, Quaternion, Twist3, Vector3
from contracts.core.quality import QualityState
from contracts.decision import ActionDecision, ActionOutcome, ActionSpec, EffectPhase, ExitDecision, ExitReason
from contracts.effects.vehicle import ArmEffect, DisarmEffect, LandEffect, PoseTargetEffect, StopMotionEffect, TakeoffEffect, TwistTargetEffect
from contracts.world.models import ResourceReference
from environments.resources import ResolvedTarget

BAD = (EffectPhase.REJECTED, EffectPhase.UNKNOWN, EffectPhase.CANCELLED)
WRITTEN = (EffectPhase.TRANSMITTED, EffectPhase.ACKNOWLEDGED, EffectPhase.COMPLETED)


@dataclass(frozen=True, slots=True)
class BasicParameters:
    vehicle_kind: str
    environment: ResourceReference
    target: ResolvedTarget | None = None
    arrival_margin_m: float = .75
    height_m: float = 1.5
    duration_ns: int = 2_000_000_000
    timeout_ns: int = 15_000_000_000

    def __post_init__(self):
        if self.vehicle_kind not in ('copter','rover'):
            raise ValueError('unsupported kind')
        if not math.isfinite(self.arrival_margin_m) or not .1<=self.arrival_margin_m<=.75:
            raise ValueError('invalid arrival margin')
        if not math.isfinite(self.height_m) or not 0 < self.height_m <= 2:
            raise ValueError('invalid height')
        if any(type(value) is not int for value in (self.duration_ns,self.timeout_ns)) or not 0 < self.duration_ns <= self.timeout_ns <= 45_000_000_000:
            raise ValueError('invalid finite Action deadline')
        if self.target is not None and self.target.environment != self.environment:
            raise ValueError('target belongs to another environment')


EFFECTS = {
    'arm': (ArmEffect,), 'disarm': (DisarmEffect,),
    'takeoff': (TakeoffEffect, TwistTargetEffect, StopMotionEffect), 'land': (LandEffect,),
    'goto': (PoseTargetEffect, TwistTargetEffect, StopMotionEffect),
    'return_home': (PoseTargetEffect, TwistTargetEffect, StopMotionEffect),
    'hold': (PoseTargetEffect, TwistTargetEffect, StopMotionEffect), 'stop': (TwistTargetEffect, StopMotionEffect),
}
CAPABILITY = {'arm':'arm', 'disarm':'disarm', 'takeoff':'takeoff', 'land':'land',
              'goto':'navigation', 'return_home':'navigation', 'hold':'hold', 'stop':'stop'}


def register_basic(registry):
    for name, effects in EFFECTS.items():
        registry.register_typed(ActionSpec('basic.'+name, BasicParameters,
            frozenset({CAPABILITY[name]}), effects, 1_000_000_000 if name in ('goto','return_home','hold','stop')
            else 5_000_000_000), BasicAction(name))


def yaw(pose):
    q = pose.orientation
    return math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))


def failed(reason):
    return ActionDecision(ActionOutcome.FAILED, error=reason)


class BasicAction:
    def __init__(self, name):
        if name not in EFFECTS:
            raise ValueError('unknown basic Action')
        self.name = name

    def start(self, parameters, snapshot):
        if parameters.vehicle_kind not in ('copter','rover') or not 0 < parameters.timeout_ns <= 45_000_000_000:
            raise ValueError('invalid vehicle/deadline')
        if not 0 < parameters.duration_ns <= parameters.timeout_ns:
            raise ValueError('invalid duration')
        if parameters.vehicle_kind == 'rover' and self.name in ('takeoff','land'):
            raise ValueError('Rover has no flight Action')
        if self.name in ('goto','return_home') and parameters.target is None:
            raise ValueError('resolved named target required')
        return BasicInstance(self.name, parameters, snapshot)


class BasicInstance:
    def __init__(self, name, parameters, snapshot):
        self.name, self.p = name, parameters
        self.start_ns = snapshot.published_at.monotonic_ns
        self.deadline_ns = self.start_ns + parameters.timeout_ns
        self.stream = 'action:'+uuid4().hex
        self.pose = None
        if snapshot.localization is not None:
            current = snapshot.localization.pose.value
            angle = yaw(current)
            self.pose = Pose3(current.position, Quaternion(0,0,math.sin(angle/2),math.cos(angle/2)))
        self.initial_height = 0 if self.pose is None else self.pose.position.z
        self.reverse = False
        if parameters.vehicle_kind == 'rover' and parameters.target is not None and self.pose is not None:
            destination=parameters.target.position
            heading=math.atan2(destination.y-self.pose.position.y,destination.x-self.pose.position.x)
            error=math.atan2(math.sin(heading-yaw(self.pose)),math.cos(heading-yaw(self.pose)))
            self.reverse=abs(error)>math.pi/2
        self.requested = False
        self.touched = False
        self.boundary = 0
        self.refresh_ns = 0
        self.stable_ns = None
        self.stage = 'align' if parameters.vehicle_kind == 'rover' and name in ('goto','return_home') else 'drive'
        self.stop_requested = False
        self.stop_boundary = 0
        self.exit_ns = None
        self.exit_zero_requested = False
        self.exit_zero_boundary = 0
        self.exit_stable_ns = None

    def _world_error(self, world, motion=False):
        if world.environment != self.p.environment:
            return 'environment_version_changed'
        state = world.vehicle
        if state is None or state.health.quality is not QualityState.VALID:
            return 'fresh_vehicle_required'
        if motion:
            loc = world.localization
            if (loc is None or loc.twist is None or loc.pose.frame_id != 'odom'
                    or loc.twist.frame_id != 'odom' or loc.quality is not QualityState.VALID):
                return 'fresh_localization_required'
            try:
                if any(not 0 <= world.published_at.elapsed_ns_since(stamp) <= 3_000_000_000
                       for stamp in (loc.pose.captured_at, loc.twist.captured_at)):
                    return 'localization_age_invalid'
            except ValueError:
                return 'localization_clock_invalid'
        return None

    def _heading_error(self, current, target):
        bearing=math.atan2(target.position.y-current.position.y,target.position.x-current.position.x)
        if self.reverse:bearing+=math.pi
        return math.atan2(math.sin(bearing-yaw(current)),math.cos(bearing-yaw(current)))

    def _yaw_request(self, world, error):
        measured=world.localization.twist.value.angular.z
        return max(-.2,min(.2,.25*error-.5*measured))

    def _steady(self, world, bound=None):
        loc = world.localization
        if loc is None or loc.twist is None:
            return False
        v, w = loc.twist.value.linear, loc.twist.value.angular
        limit = bound if bound is not None else (.1 if self.p.vehicle_kind=='rover' else .15)
        return math.hypot(v.x,v.y)<=limit and abs(v.z)<=.2 and abs(w.z)<=.15

    def tick(self, world):
        return self.tick_with_results(world, ())

    def tick_with_results(self, world, results):
        now = world.published_at.monotonic_ns
        if now > self.deadline_ns:
            return failed('action_deadline_exceeded')
        motion = self.name in ('takeoff','goto','return_home','hold','stop')
        error = self._world_error(world, motion)
        if error:
            return failed(error)
        state = world.vehicle
        if motion and (not state.operation.armed or state.operation.native_mode !=
                ('ARDUPILOT_CUSTOM_15' if self.p.vehicle_kind=='rover' else 'ARDUPILOT_CUSTOM_4')):
            return failed('armed_guided_state_required')
        if self.name in ('goto','return_home','hold','stop'):
            return self._motion(world, results)
        if not self.requested:
            if self.name == 'arm' and state.operation.armed:
                return failed('unexpected_initial_armed_state')
            self.requested = True
            self.boundary = len(results)
            effect = {'arm':ArmEffect, 'disarm':DisarmEffect, 'land':LandEffect}.get(self.name)
            value = TakeoffEffect(self.p.height_m) if self.name=='takeoff' else effect()
            return ActionDecision(ActionOutcome.RUNNING, (value,))
        feedback = results[self.boundary:]
        if feedback and feedback[-1].phase in BAD:
            return failed(feedback[-1].reason or feedback[-1].phase.value)
        phase = None if not feedback else feedback[-1].phase
        if self.name in ('arm','disarm'):
            if phase is EffectPhase.COMPLETED and state.operation.armed == (self.name=='arm'):
                return ActionDecision(ActionOutcome.SUCCEEDED)
            return ActionDecision(ActionOutcome.RUNNING)
        if phase not in (EffectPhase.ACKNOWLEDGED, EffectPhase.COMPLETED):
            return ActionDecision(ActionOutcome.RUNNING)
        loc = world.localization
        if loc is None or loc.pose.captured_at.monotonic_ns <= self.start_ns:
            return ActionDecision(ActionOutcome.RUNNING)
        height = loc.pose.value.position.z
        target = self.p.target
        reached = (abs(height-self.initial_height-self.p.height_m)<=.35 and self._steady(world, .2)
                   if self.name=='takeoff' else target is not None and height <= target.position.z+.2
                   and not state.operation.armed and self._steady(world, .15))
        self.stable_ns = (self.stable_ns if self.stable_ns is not None else now) if reached else None
        if self.stable_ns is not None and now-self.stable_ns >= 2_000_000_000:
            return ActionDecision(ActionOutcome.SUCCEEDED)
        return ActionDecision(ActionOutcome.RUNNING)

    def _motion(self, world, results):
        now = world.published_at.monotonic_ns
        loc = world.localization
        current = loc.pose.value
        target = self.p.target
        if target is not None and (target.environment != world.environment or target.frame != 'odom'):
            return failed('target_frame_or_environment_changed')
        if self.stage == 'align':
            dx,dy = target.position.x-current.position.x, target.position.y-current.position.y
            error = self._heading_error(current,target)
            if (abs(error)<=.25 and abs(loc.twist.value.angular.z)<=.1) or math.hypot(dx,dy)<=.45:
                self.stage = 'align_stop' if self.touched else 'drive'
                if not self.touched:
                    self.boundary = len(results)
                return ActionDecision(ActionOutcome.RUNNING)
            if results and results[-1].phase in (EffectPhase.REJECTED,EffectPhase.UNKNOWN):
                return failed(results[-1].reason or 'alignment_rejected')
            if now>=self.refresh_ns:
                self.refresh_ns=now+300_000_000
                self.touched=True
                return ActionDecision(ActionOutcome.RUNNING,(TwistTargetEffect('base_link',
                    Twist3(Vector3(0,0,0),Vector3(0,0,self._yaw_request(world,error))),self.stream),))
            return ActionDecision(ActionOutcome.RUNNING)
        if self.stage == 'align_stop':
            if not self.stop_requested:
                self.stop_requested=True
                self.stop_boundary=len(results)
                return ActionDecision(ActionOutcome.RUNNING,(StopMotionEffect(self.stream),))
            stop = results[self.stop_boundary:]
            if stop and stop[-1].phase in BAD:
                return failed('alignment_stop_unconfirmed')
            if stop and stop[-1].phase is EffectPhase.COMPLETED:
                self.stage='drive'
                self.stop_requested=False
                self.touched=False
                self.boundary=len(results)
            return ActionDecision(ActionOutcome.RUNNING)
        feedback = results[self.boundary:]
        if feedback and feedback[-1].phase in (EffectPhase.REJECTED,EffectPhase.UNKNOWN):
            return failed(feedback[-1].reason or 'motion_rejected')
        written = bool(feedback and feedback[-1].phase in WRITTEN)
        post_sample = loc.pose.captured_at.monotonic_ns > self.start_ns
        if self.name == 'stop':
            reached = self._steady(world)
        else:
            destination = self.pose if self.name=='hold' else Pose3(target.position, self.pose.orientation)
            p=destination.position
            reached=(math.hypot(current.position.x-p.x,current.position.y-p.y)<=(min(.45,self.p.arrival_margin_m) if self.p.vehicle_kind=="rover" and self.name in ("goto","return_home") else self.p.arrival_margin_m)
                     and (self.p.vehicle_kind=='rover' or abs(current.position.z-p.z)<=.35))
        good = written and post_sample and reached
        if self.name == 'stop':good = good and self._steady(world)
        self.stable_ns = (self.stable_ns if self.stable_ns is not None else now) if good else None
        duration = self.p.duration_ns if self.name=='hold' else 1_000_000_000
        if self.stable_ns is not None and now-self.stable_ns>=duration:
            return ActionDecision(ActionOutcome.SUCCEEDED)
        if now>=self.refresh_ns:
            if not self.touched:
                self.boundary=len(results)
            self.touched=True
            self.refresh_ns=now+300_000_000
            if self.p.vehicle_kind == 'rover' and self.name in ('goto','return_home'):
                dx,dy=target.position.x-current.position.x,target.position.y-current.position.y
                distance=math.hypot(dx,dy)
                angle=self._heading_error(current,target)
                speed=min(.35,max(0,distance-.4)*.5)*max(0,math.cos(angle)) if distance>.4 else 0
                if self.reverse:speed=-speed
                rate=self._yaw_request(world,angle) if distance>.4 else 0
                effect=TwistTargetEffect('base_link',Twist3(Vector3(speed,0,0),Vector3(0,0,rate)),self.stream)
            else:
                effect = (TwistTargetEffect('base_link' if self.p.vehicle_kind=='rover' else 'odom',
                    Twist3(Vector3(0,0,0),Vector3(0,0,0)),self.stream) if self.name=='stop' or self.p.vehicle_kind=='rover' and self.name=='hold' else
                    PoseTargetEffect('odom',self.pose if self.name=='hold' else Pose3(target.position,self.pose.orientation),self.stream))
            return ActionDecision(ActionOutcome.RUNNING,(effect,))
        return ActionDecision(ActionOutcome.RUNNING)

    def exit(self, world, reason):
        return self.exit_with_results(world, reason, ())

    def exit_with_results(self, world, reason, results):
        now=world.published_at.monotonic_ns
        if self.exit_ns is None:self.exit_ns=now
        if now-self.exit_ns>8_000_000_000:
            raise RuntimeError('stop_exit_deadline_unconfirmed')
        # Interrupted takeoff first establishes a controlled zero-velocity stream.
        if self.name=='takeoff' and reason is not ExitReason.SUCCEEDED and world.vehicle and world.vehicle.operation.armed:
            if not self.exit_zero_requested:
                self.exit_zero_requested=True
                self.exit_zero_boundary=len(results)
                self.touched=True
                return ExitDecision(False,(TwistTargetEffect('odom',Twist3(Vector3(0,0,0),Vector3(0,0,0)),self.stream),))
            zero=results[self.exit_zero_boundary:]
            if not self.stop_requested and (not zero or zero[-1].phase not in WRITTEN):
                if zero and zero[-1].phase in BAD:raise RuntimeError('takeoff_stop_unconfirmed')
                return ExitDecision(False)
        if not self.touched:
            return ExitDecision(True)
        if not self.stop_requested:
            self.stop_requested=True
            self.stop_boundary=len(results)
            return ExitDecision(False,(StopMotionEffect(self.stream),))
        feedback=results[self.stop_boundary:]
        if feedback and feedback[-1].phase in BAD:
            raise RuntimeError('stop_exit_unconfirmed')
        steady=(bool(feedback and feedback[-1].phase is EffectPhase.COMPLETED) and
                self._world_error(world, True) is None and self._steady(world))
        self.exit_stable_ns=(self.exit_stable_ns if self.exit_stable_ns is not None else now) if steady else None
        return ExitDecision(self.exit_stable_ns is not None and now-self.exit_stable_ns>=2_000_000_000)

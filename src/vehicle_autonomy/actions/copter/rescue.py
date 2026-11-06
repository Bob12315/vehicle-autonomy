"""Finite rescue flight Actions; requests still cross the existing Execution.

These deliberately require a separate rescue_flight capability. Registering an
Action does not widen the ordinary Copter profile or grant that capability.
"""
from dataclasses import dataclass, field, replace
import math

from vehicle_autonomy.actions.common.basic import BasicInstance, BasicParameters, BAD, WRITTEN, yaw
from vehicle_autonomy.actions.common.standard import ContextFactory
from vehicle_autonomy.contracts.core.geometry import Twist3, Vector3
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.decision import ActionDecision, ActionOutcome
from vehicle_autonomy.contracts.effects.vehicle import TakeoffEffect, TwistTargetEffect


@dataclass(frozen=True, slots=True)
class TakeoffParameters:
    height_m: float = field(default=4.5, metadata={'exclusiveMinimum':0, 'maximum':5})


@dataclass(frozen=True, slots=True)
class GotoParameters:
    x_m: float = field(metadata={'minimum':-5, 'maximum':5})
    y_m: float = field(metadata={'minimum':-2, 'maximum':62})
    z_m: float = field(default=3., metadata={'minimum':.3, 'maximum':5})
    speed_mps: float = field(default=1., metadata={'exclusiveMinimum':0, 'maximum':10})
    tolerance_xy_m: float = field(default=.3, metadata={'minimum':.1, 'maximum':.7})
    tolerance_z_m: float = field(default=.3, metadata={'minimum':.1, 'maximum':.5})
    settle_s: float = field(default=1., metadata={'minimum':.3, 'maximum':3})


@dataclass(frozen=True, slots=True)
class FlightParameters:
    """Private bound parameters for the existing physical takeoff/exit barrier."""
    vehicle_kind: str
    environment: object
    height_m: float
    timeout_ns: int = 45_000_000_000
    target: object = None
    duration_ns: int = 2_000_000_000
    arrival_margin_m: float = .3


def state_error(world, environment, generation):
    if world.environment != environment or world.version.generation_id != generation:
        return 'rescue_world_epoch_changed'
    state, loc = world.vehicle, world.localization
    if (state is None or state.health.quality is not QualityState.VALID or not state.operation.armed
            or state.operation.native_mode != 'ARDUPILOT_CUSTOM_4' or loc is None
            or loc.quality is not QualityState.VALID or loc.twist is None
            or loc.pose.frame_id != 'odom' or loc.twist.frame_id != 'odom'):
        return 'rescue_fresh_armed_guided_localization_required'
    try:
        if any(not 0 <= world.published_at.elapsed_ns_since(at) <= 1_000_000_000
               for at in (state.published_at, loc.pose.captured_at, loc.twist.captured_at)):
            return 'rescue_vehicle_stale'
    except ValueError:
        return 'rescue_vehicle_clock_mismatch'
    return None


class FlightFactory(ContextFactory):
    def __init__(self, name): self.name = name

    def validate_context(self, p, world, ctx):
        if not ctx.owned_simulation or ctx.target_kind != 'copter' or 'rescue_flight' not in ctx.capabilities:
            raise ValueError('explicit owned rescue Copter profile required')
        if world.environment is None or state_error(world, world.environment, world.version.generation_id):
            raise ValueError('fresh bound armed GUIDED rescue world required')

    def start_with_context(self, p, world, ctx):
        self.validate_context(p, world, ctx)
        if self.name == 'Takeoff':
            # Reuse the existing ACK + post-request physical climb predicate and
            # its interrupted-takeoff StopMotion exit. No general limit changes.
            return BasicInstance('takeoff', FlightParameters('copter', world.environment, p.height_m), world)
        return GotoInstance(p, world)


class MotionInstance:
    def __init__(self, world, *, speed_limit_mps=1.99):
        self.environment = world.environment
        self.generation = world.version.generation_id
        self.started = world.published_at
        self.stopper = BasicInstance('stop', BasicParameters('copter', world.environment), world)
        self.stream = self.stopper.stream
        self.stable = None
        self.refresh = 0
        self.speed_limit_mps = speed_limit_mps

    def request(self, world, velocity, yaw_rate=0.):
        now = world.published_at.monotonic_ns
        if now < self.refresh: return ActionDecision(ActionOutcome.RUNNING)
        self.refresh = now + 200_000_000
        self.stopper.touched = True
        length=math.sqrt(velocity.x**2+velocity.y**2+velocity.z**2)
        if length>self.speed_limit_mps:
            velocity=Vector3(*(v*self.speed_limit_mps/length for v in (velocity.x,velocity.y,velocity.z)))
        return ActionDecision(ActionOutcome.RUNNING, (TwistTargetEffect('odom',
            Twist3(velocity, Vector3(0, 0, yaw_rate)), self.stream),))

    def tick(self, world): return self.tick_with_results(world, ())
    def exit(self, world, reason): return self.exit_with_results(world, reason, ())
    def exit_with_results(self, world, reason, results):
        return self.stopper.exit_with_results(world, reason, results)

    def error(self, world, results):
        reason = state_error(world, self.environment, self.generation)
        if reason: return ActionDecision(ActionOutcome.FAILED, error=reason)
        if results and results[-1].phase in BAD:
            return ActionDecision(ActionOutcome.FAILED, error=results[-1].reason or 'rescue_motion_unconfirmed')
        return None

    def settled(self, world, reached, results, duration_s):
        now = world.published_at.monotonic_ns
        fresh = world.localization.pose.captured_at > self.started
        good = reached and fresh and bool(results and results[-1].phase in WRITTEN)
        self.stable = (now if self.stable is None else self.stable) if good else None
        return self.stable is not None and now-self.stable >= duration_s*1e9


class GotoInstance(MotionInstance):
    def __init__(self, p, world):
        super().__init__(world,speed_limit_mps=9.99); self.p = p

    def tick_with_results(self, world, results):
        error = self.error(world, results)
        if error: return error
        p = self.p; loc = world.localization
        position, velocity = loc.pose.value.position, loc.twist.value.linear
        dx, dy, dz = p.x_m-position.x, p.y_m-position.y, p.z_m-position.z
        reached = (math.hypot(dx, dy) <= p.tolerance_xy_m and abs(dz) <= p.tolerance_z_m
                   and math.hypot(velocity.x, velocity.y) <= .25 and abs(velocity.z) <= .15)
        if self.settled(world, reached, results, p.settle_s):
            return ActionDecision(ActionOutcome.SUCCEEDED, result={'physical_goal_observed':True})
        scale = min(.5, p.speed_mps/max(1e-9, math.hypot(dx, dy)))
        # All source field-heading targets face Gazebo +Y (ENU yaw pi/2).
        angle = math.atan2(math.sin(math.pi/2-yaw(loc.pose.value)), math.cos(math.pi/2-yaw(loc.pose.value)))
        return self.request(world, Vector3(dx*scale, dy*scale, max(-.3, min(.3, .5*dz))),
                            max(-.3, min(.3, .5*angle)))

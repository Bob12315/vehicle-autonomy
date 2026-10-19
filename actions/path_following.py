"""Rover path tracking Action: read-only inputs in, typed Effects out."""
from __future__ import annotations

from dataclasses import dataclass
from contracts.core.geometry import Twist3, Vector3
from contracts.decision import ActionDecision, ActionOutcome, ActionSpec
from contracts.effects.vehicle import StopMotionEffect, TwistTargetEffect
from contracts.world.models import ResourceReference
from guidance.path_following import PlanarBinding, PolylineTracker, drive_reference
from guidance.navigation_model import FRONT_AXLE,VehicleNavigationModel
from planning.models import Pose2D
from .basic import BAD, WRITTEN, BasicInstance, BasicParameters, failed, yaw


@dataclass(frozen=True, slots=True)
class TrackingParameters:
    environment: ResourceReference
    request_id: str
    frame_epoch: str
    source_generation: str
    file_sha256: str
    binding: PlanarBinding
    poses: tuple[Pose2D, ...]  # explicitly bound odom coordinates
    timeout_ns: int = 70_000_000_000
    stop_turn: bool = False
    model: VehicleNavigationModel = FRONT_AXLE

    def __post_init__(self):
        if type(self.timeout_ns) is not int or not 1_000_000_000 <= self.timeout_ns <= 70_000_000_000:
            raise ValueError("tracking deadline must be within 1..70 seconds")
        if type(self.stop_turn) is not bool:raise ValueError('invalid tracking strategy')
        if not isinstance(self.environment, ResourceReference) or not isinstance(self.binding, PlanarBinding):
            raise TypeError("typed environment and explicit frame binding required")
        PolylineTracker(self.poses,model=self.model)


SPEC = ActionSpec("navigation.follow_path", TrackingParameters, frozenset({"navigation"}),
                  (TwistTargetEffect, StopMotionEffect), 1_000_000_000)


class FollowPathAction:
    def __init__(self, reader):
        self.reader = reader

    def start(self, parameters, snapshot):
        return TrackingInstance(parameters, snapshot, self.reader)


class TrackingInstance:
    def __init__(self, parameters, world, reader):
        self.p, self.reader = parameters, reader
        self.stop = BasicInstance("hold", BasicParameters("rover", parameters.environment), world)
        self.tracker = PolylineTracker(parameters.poses,stop_turn=parameters.stop_turn,model=parameters.model)
        self.start_ns = world.published_at.monotonic_ns
        self.deadline_ns = self.start_ns+parameters.timeout_ns
        self.refresh_ns = 0
        self.stable_ns = None

    def tick(self, world):
        return self.tick_with_results(world, ())

    def tick_with_results(self, world, results):
        now = world.published_at.monotonic_ns
        if now > self.deadline_ns:
            return failed("navigation_deadline_exceeded")
        view = self.reader.snapshot()
        if view.request_id != self.p.request_id or view.error:
            return failed(view.error or "navigation_admission_changed")
        error = self.stop._world_error(world, True)
        if error:
            return failed(error)
        loc = world.localization
        if (world.vehicle.operation.native_mode != "ARDUPILOT_CUSTOM_15"
                or not world.vehicle.operation.armed):
            return failed("armed_guided_state_required")
        if any(not 0 <= world.published_at.elapsed_ns_since(sample.captured_at) <= 500_000_000
               for sample in (loc.pose, loc.twist)):
            return failed("navigation_localization_stale")
        if results and results[-1].phase in BAD:
            return failed(results[-1].reason or "navigation_effect_rejected")
        p = loc.pose.value
        output = self.tracker.update(drive_reference(Pose2D(p.position.x, p.position.y, yaw(p)),self.p.model), loc.twist.value.angular.z)
        if output.cross_track_m > self.p.model.cross_track_m:
            return failed("navigation_cross_track_exceeded")
        good = (output.arrived and self.stop.touched and bool(results and results[-1].phase in WRITTEN)
                and loc.pose.captured_at.monotonic_ns > self.start_ns and self.stop._steady(world))
        self.stable_ns = (self.stable_ns if self.stable_ns is not None else now) if good else None
        if self.stable_ns is not None and now-self.stable_ns >= 1_000_000_000:
            return ActionDecision(ActionOutcome.SUCCEEDED)
        if now < self.refresh_ns:
            return ActionDecision(ActionOutcome.RUNNING)
        self.refresh_ns = now+200_000_000
        self.stop.touched = True
        effect = TwistTargetEffect("base_link", Twist3(Vector3(output.speed_mps, 0, 0),
            Vector3(0, 0, output.yaw_rate_rps)), self.stop.stream)
        return ActionDecision(ActionOutcome.RUNNING, (effect,))

    def exit(self, world, reason):
        return self.exit_with_results(world, reason, ())

    def exit_with_results(self, world, reason, results):
        # Map validity must never gate this existing observed Stop barrier.
        return self.stop.exit_with_results(world, reason, results)

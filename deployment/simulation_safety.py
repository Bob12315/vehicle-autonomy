"""Extra motion-state checks for the explicit simulation composition."""

from __future__ import annotations

from contracts.core.time import TimePoint
from contracts.effects.vehicle import EffectEnvelope, PoseTargetEffect, TakeoffEffect, TwistTargetEffect
from contracts.world.models import WorldSnapshot
from core.vehicle_safety import SafetyLimits, VehicleSafetyPolicy


class SimulationSafetyPolicy(VehicleSafetyPolicy):
    """Require fresh position and velocity, beyond a fresh heartbeat."""

    def __init__(self, limits: SafetyLimits, *, motion_mode_id: int) -> None:
        super().__init__(limits)
        if type(motion_mode_id) is not int or motion_mode_id < 0:
            raise ValueError("audited Guided mode ID required")
        self.motion_mode_id = motion_mode_id

    def evaluate(self, envelope: EffectEnvelope, world: WorldSnapshot, now: TimePoint) -> str | None:
        reason = super().evaluate(envelope, world, now)
        if reason is not None or not isinstance(envelope.effect, (PoseTargetEffect, TwistTargetEffect, TakeoffEffect)):
            return reason
        vehicle = world.vehicle
        if vehicle is None or vehicle.reported_pose is None or vehicle.reported_twist is None:
            return "motion_state_unavailable"
        for sample in (vehicle.reported_pose, vehicle.reported_twist):
            try:
                age = now.elapsed_ns_since(sample.captured_at)
            except ValueError:
                return "motion_clock_domain_mismatch"
            if age < 0 or age > self.limits.max_snapshot_age_ns:
                return "motion_state_stale"
        if not vehicle.operation.armed:
            return "motion_requires_armed"
        if vehicle.operation.native_mode != f"ARDUPILOT_CUSTOM_{self.motion_mode_id}":
            return "motion_requires_guided_mode"
        return None

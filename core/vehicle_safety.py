"""Deterministic, explicitly configured vehicle Effect constraints."""

from __future__ import annotations

from dataclasses import dataclass
import math

from contracts.core.geometry import FrameId
from contracts.core.quality import FreshnessState, QualityState
from contracts.core.time import TimePoint
from contracts.effects.vehicle import (
    EffectEnvelope, ModeEffect, PoseTargetEffect, StopMotionEffect,
    TakeoffEffect, TwistTargetEffect,
)
from contracts.world.models import WorldSnapshot


@dataclass(frozen=True, slots=True)
class SafetyLimits:
    max_request_ttl_ns: int
    max_snapshot_age_ns: int
    deadman_ns: int
    min_altitude_m: float
    max_altitude_m: float
    max_takeoff_m: float
    max_linear_mps: float
    max_angular_rad_s: float
    allowed_frames: frozenset[FrameId]
    allowed_modes: frozenset[str]
    min_x_m: float
    max_x_m: float
    min_y_m: float
    max_y_m: float

    def __post_init__(self) -> None:
        for name in ("max_request_ttl_ns", "max_snapshot_age_ns", "deadman_ns"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be positive nanoseconds")
        for name in ("min_altitude_m", "max_altitude_m", "max_takeoff_m", "max_linear_mps", "max_angular_rad_s", "min_x_m", "max_x_m", "min_y_m", "max_y_m"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not (self.min_altitude_m < self.max_altitude_m and 0 < self.max_takeoff_m <= self.max_altitude_m):
            raise ValueError("invalid altitude limits")
        if self.max_linear_mps <= 0 or self.max_angular_rad_s <= 0:
            raise ValueError("motion limits must be positive")
        if self.min_x_m >= self.max_x_m or self.min_y_m >= self.max_y_m:
            raise ValueError("geofence bounds must be ordered")
        if not isinstance(self.allowed_frames, frozenset) or not self.allowed_frames or any(not isinstance(frame, FrameId) for frame in self.allowed_frames):
            raise ValueError("allowed_frames must contain FrameId values")
        if not isinstance(self.allowed_modes, frozenset) or any(not isinstance(mode, str) or not mode.strip() for mode in self.allowed_modes):
            raise ValueError("invalid mode allowlist")


class VehicleSafetyPolicy:
    def __init__(self, limits: SafetyLimits) -> None:
        if not isinstance(limits, SafetyLimits):
            raise TypeError("explicit SafetyLimits required")
        self.limits = limits

    def evaluate(self, envelope: EffectEnvelope, world: WorldSnapshot, now: TimePoint) -> str | None:
        try:
            age = now.elapsed_ns_since(envelope.created_at)
            ttl = envelope.deadline.elapsed_ns_since(envelope.created_at)
            remaining = envelope.deadline.elapsed_ns_since(now)
        except ValueError:
            return "clock_domain_mismatch"
        if age < 0 or remaining <= 0 or ttl > self.limits.max_request_ttl_ns:
            return "invalid_effect_time"
        if isinstance(envelope.effect, StopMotionEffect):
            return None
        try:
            world_age = now.elapsed_ns_since(world.published_at)
        except ValueError:
            return "world_clock_domain_mismatch"
        if world_age < 0 or world_age > self.limits.max_snapshot_age_ns:
            return "world_stale"
        if world.vehicle is None or world.vehicle.health.quality is not QualityState.VALID:
            return "vehicle_state_unavailable"
        try:
            vehicle_age = now.elapsed_ns_since(world.vehicle.published_at)
        except ValueError:
            return "vehicle_clock_domain_mismatch"
        if vehicle_age < 0 or vehicle_age > self.limits.max_snapshot_age_ns:
            return "vehicle_state_stale"
        if any(item.state is not FreshnessState.FRESH for item in world.freshness if item.component_id == "vehicle"):
            return "vehicle_freshness_invalid"
        effect = envelope.effect
        if isinstance(effect, ModeEffect) and effect.native_mode not in self.limits.allowed_modes:
            return "mode_not_allowed"
        if isinstance(effect, TakeoffEffect) and not 0 < effect.height_m <= self.limits.max_takeoff_m:
            return "takeoff_height_out_of_bounds"
        if isinstance(effect, (PoseTargetEffect, TwistTargetEffect)) and effect.frame_id not in self.limits.allowed_frames:
            return "frame_not_allowed"
        if isinstance(effect, PoseTargetEffect):
            p = effect.target_pose.position
            if not (self.limits.min_x_m <= p.x <= self.limits.max_x_m and self.limits.min_y_m <= p.y <= self.limits.max_y_m and self.limits.min_altitude_m <= p.z <= self.limits.max_altitude_m):
                return "target_outside_geofence"
        if isinstance(effect, TwistTargetEffect):
            linear = effect.target_twist.linear
            angular = effect.target_twist.angular
            if math.sqrt(linear.x**2 + linear.y**2 + linear.z**2) > self.limits.max_linear_mps or math.sqrt(angular.x**2 + angular.y**2 + angular.z**2) > self.limits.max_angular_rad_s:
                return "speed_limit_exceeded"
        return None

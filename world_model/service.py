from __future__ import annotations

import threading

from contracts.core.world import WorldHealth, WorldPose, WorldSnapshot, WorldVelocity
from contracts.platform.common import ClockStamp, SchemaVersion
from contracts.platform.perception import PerceptionFrameSnapshot, PerceptionHealthSnapshot
from contracts.platform.vehicle_state import VehicleStateSnapshot
from contracts.core.world import EnvironmentReference


class WorldModel:
    """Publish one immutable cut from already-normalized upstream snapshots."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: WorldSnapshot | None = None
        self._sequence = 0

    def publish(self, *, captured_at: ClockStamp,
                vehicle: VehicleStateSnapshot | None,
                perception: PerceptionFrameSnapshot | None,
                perception_health: PerceptionHealthSnapshot | None = None,
                environment_reference: EnvironmentReference | None = None) -> WorldSnapshot:
        vehicle_usable = vehicle is not None and vehicle.connected and not vehicle.stale
        perception_age_ns = (
            None if perception is None else
            captured_at.monotonic_ns - perception.received_at_monotonic_ns
        )
        perception_current = (
            perception_age_ns is not None and 0 <= perception_age_ns <= 2_000_000_000
        )
        perception_usable = (
            perception_current and perception_health is not None
            and perception_health.healthy
            and perception_health.active_session_id == perception.process_session_id
        )
        pose = None
        velocity = None
        if vehicle_usable:
            pose = WorldPose(
                vehicle.local_north_m if vehicle.local_valid else None,
                vehicle.local_east_m if vehicle.local_valid else None,
                vehicle.local_down_m if vehicle.local_valid else None,
                vehicle.latitude_deg if vehicle.global_valid else None,
                vehicle.longitude_deg if vehicle.global_valid else None,
                vehicle.altitude_msl_m if vehicle.global_valid else None,
                vehicle.yaw_rad,
            )
            if all(value is not None for value in (
                vehicle.velocity_north_mps, vehicle.velocity_east_mps,
                vehicle.velocity_down_mps,
            )):
                velocity = WorldVelocity(
                    float(vehicle.velocity_north_mps), float(vehicle.velocity_east_mps),
                    float(vehicle.velocity_down_mps),
                )
        if perception_usable:
            perception_reason = "ok"
        elif perception is not None and not perception_current:
            perception_reason = "stale_or_future_perception"
        elif perception_health is not None:
            perception_reason = perception_health.reason_code
        else:
            perception_reason = "perception_unavailable"
        health = WorldHealth(
            vehicle_usable, perception_usable,
            "ok" if vehicle_usable else "vehicle_unavailable_or_stale",
            perception_reason,
        )
        with self._lock:
            self._sequence += 1
            result = WorldSnapshot(
                SchemaVersion(1, 0), self._sequence, captured_at,
                vehicle, perception, perception_health, environment_reference,
                pose, velocity,
                (perception.target,) if perception_usable and perception.target is not None else (),
                health,
            )
            self._latest = result
            return result

    def snapshot(self) -> WorldSnapshot | None:
        with self._lock:
            return self._latest

"""Offline vehicle-reported state source with a read-only query surface."""

from __future__ import annotations

from threading import Lock

from contracts.core.geometry import GeoPoint, Pose3, Twist3
from contracts.core.primitives import ResourceVersion, SchemaVersion, VehicleId
from contracts.core.quality import QualityState
from contracts.core.stamped import Stamped
from contracts.core.time import TimePoint
from contracts.vehicle.models import (
    BatteryState, VehicleHealth, VehicleOperation, VehicleStateSnapshot,
)


class FakeVehicleStateSource:
    def __init__(self, vehicle_id: VehicleId, generation_id: str) -> None:
        self._vehicle_id = VehicleId(vehicle_id)
        self._generation_id = generation_id
        self._lock = Lock()
        self._latest: VehicleStateSnapshot | None = None
        self._revision = 0

    def publish(
        self, *, published_at: TimePoint, reported_pose: Stamped[Pose3] | None = None,
        reported_twist: Stamped[Twist3] | None = None,
        global_position: Stamped[GeoPoint] | None = None,
        quality: QualityState = QualityState.VALID,
        operation: VehicleOperation = VehicleOperation(),
        battery: BatteryState | None = None,
    ) -> VehicleStateSnapshot:
        with self._lock:
            candidate = VehicleStateSnapshot(
                SchemaVersion(1, 0), self._vehicle_id,
                ResourceVersion(self._generation_id, self._revision + 1),
                published_at, VehicleHealth(quality), reported_pose,
                reported_twist, global_position, operation, battery,
            )
            self._revision += 1
            self._latest = candidate
            return candidate

    def snapshot(self) -> VehicleStateSnapshot | None:
        with self._lock:
            return self._latest

    def clear(self) -> None:
        """Represent a missing offline state publication without resetting versioning."""
        with self._lock:
            self._latest = None

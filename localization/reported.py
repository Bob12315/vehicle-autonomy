"""Pure offline projection of vehicle-reported pose into an explicit estimate."""

from __future__ import annotations

from contracts.core.primitives import ProducerId, ResourceVersion, SchemaVersion
from contracts.core.quality import QualityState
from contracts.localization.models import LocalizationEstimate
from contracts.vehicle.models import VehicleStateSnapshot


class ReportedPoseLocalization:
    def __init__(self, producer_id: ProducerId = ProducerId("reported_pose_localization")) -> None:
        self.producer_id = ProducerId(producer_id)

    def estimate(self, vehicle: VehicleStateSnapshot | None) -> LocalizationEstimate | None:
        if vehicle is None or vehicle.reported_pose is None:
            return None
        if vehicle.health.quality in (QualityState.INVALID, QualityState.UNAVAILABLE):
            return None
        return LocalizationEstimate(
            SchemaVersion(1, 0),
            ResourceVersion(f"{self.producer_id}:{vehicle.vehicle_id}:{vehicle.version.generation_id}", vehicle.version.revision),
            self.producer_id, vehicle.published_at, vehicle.reported_pose,
            vehicle.health.quality, vehicle.reported_twist,
        )

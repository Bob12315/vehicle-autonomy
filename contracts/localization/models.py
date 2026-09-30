"""Independent localization estimates, separate from vehicle-reported state."""

from __future__ import annotations

from dataclasses import dataclass
import math

from contracts.core.geometry import Pose3, Twist3
from contracts.core.primitives import ProducerId, ResourceVersion, SchemaVersion
from contracts.core.quality import QualityState
from contracts.core.stamped import Stamped
from contracts.core.time import TimePoint


@dataclass(frozen=True, slots=True)
class LocalizationEstimate:
    schema_version: SchemaVersion
    version: ResourceVersion
    producer_id: ProducerId
    published_at: TimePoint
    pose: Stamped[Pose3]
    quality: QualityState
    twist: Stamped[Twist3] | None = None
    covariance: tuple[tuple[float, ...], ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, SchemaVersion) or not isinstance(self.version, ResourceVersion):
            raise TypeError("localization versions must be validated values")
        if not isinstance(self.published_at, TimePoint):
            raise TypeError("published_at must be TimePoint")
        if not isinstance(self.pose, Stamped) or (self.twist is not None and not isinstance(self.twist, Stamped)):
            raise TypeError("localization pose and twist must be Stamped")
        if not isinstance(self.quality, QualityState):
            raise TypeError("quality must be QualityState")
        if not isinstance(self.producer_id, ProducerId):
            object.__setattr__(self, "producer_id", ProducerId(self.producer_id))
        if not isinstance(self.pose.value, Pose3):
            raise TypeError("localization pose must contain Pose3")
        if self.twist is not None and not isinstance(self.twist.value, Twist3):
            raise TypeError("localization twist must contain Twist3")
        if self.covariance is not None:
            matrix = self.covariance
            if not isinstance(matrix, tuple) or not matrix or any(not isinstance(row, tuple) for row in matrix):
                raise TypeError("covariance must be a non-empty tuple of tuple rows")
            size = len(matrix)
            if any(len(row) != size for row in matrix):
                raise ValueError("covariance matrix must be square")
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                for row in matrix for value in row
            ):
                raise ValueError("covariance values must be finite numbers")

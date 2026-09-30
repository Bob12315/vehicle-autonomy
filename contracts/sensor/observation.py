"""Typed, provenance-carrying observations from sensor and state producers."""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from typing import Generic, TypeVar

from contracts.core.geometry import FrameId, SpatialValue
from contracts.core.primitives import ObservationId, ProducerId, SchemaVersion, is_deeply_immutable
from contracts.core.quality import QualityState
from contracts.core.time import TimePoint

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Observation(Generic[T]):
    observation_id: ObservationId
    schema_version: SchemaVersion
    producer_id: ProducerId
    sequence: int
    captured_at: TimePoint
    received_at: TimePoint
    quality: QualityState
    data: T
    frame_id: FrameId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, SchemaVersion) or not isinstance(self.quality, QualityState):
            raise TypeError("observation version and quality must be typed values")
        for field_name, identity_type in (
            ("observation_id", ObservationId),
            ("producer_id", ProducerId),
        ):
            value = getattr(self, field_name)
            if not isinstance(value, identity_type):
                object.__setattr__(self, field_name, identity_type(value))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise ValueError("observation sequence must be a non-negative integer")
        if isinstance(self.data, SpatialValue) and self.frame_id is None:
            raise ValueError("spatial observation data requires frame_id")
        if self.frame_id is not None and not isinstance(self.frame_id, FrameId):
            object.__setattr__(self, "frame_id", FrameId(self.frame_id))
        if not is_dataclass(self.data) or not is_deeply_immutable(self.data):
            raise TypeError("observation data must be a deeply immutable typed value")
        if not isinstance(self.captured_at, TimePoint) or not isinstance(self.received_at, TimePoint):
            raise TypeError("observation timestamps must be TimePoint values")

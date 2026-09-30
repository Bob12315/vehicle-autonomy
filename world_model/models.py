"""World objects projected from typed detections without implicit frame conversion."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.core.geometry import Vector3
from contracts.core.primitives import ObservationId, ProducerId
from contracts.core.quality import QualityState
from contracts.core.stamped import Stamped


@dataclass(frozen=True, slots=True)
class WorldObject:
    object_id: str
    label: str
    position: Stamped[Vector3]
    confidence: float
    quality: QualityState
    source_observation_id: ObservationId
    producer_id: ProducerId

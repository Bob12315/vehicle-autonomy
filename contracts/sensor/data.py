"""A minimal typed spatial detection for offline state-chain validation."""

from __future__ import annotations

from dataclasses import dataclass
import math

from contracts.core.geometry import Vector3
from contracts.core.primitives import Identifier


class ObjectId(Identifier):
    __slots__ = ()


@dataclass(frozen=True, slots=True)
class DetectedObject:
    object_id: ObjectId
    label: str
    position: Vector3
    confidence: float

    def __post_init__(self) -> None:
        if not isinstance(self.object_id, ObjectId):
            object.__setattr__(self, "object_id", ObjectId(self.object_id))
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("label must be non-empty")
        if not isinstance(self.position, Vector3):
            raise TypeError("position must be an SI Vector3")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be finite and within [0, 1]")

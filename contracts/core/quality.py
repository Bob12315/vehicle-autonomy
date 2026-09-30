"""Independent data quality and snapshot freshness dimensions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class QualityState(str, Enum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ComponentFreshness:
    component_id: str
    state: FreshnessState
    age_ns: int | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.component_id, str) or not self.component_id.strip():
            raise ValueError("component_id must be non-empty")
        if not isinstance(self.state, FreshnessState):
            raise TypeError("state must be FreshnessState")
        if self.age_ns is not None and (
            isinstance(self.age_ns, bool) or not isinstance(self.age_ns, int) or self.age_ns < 0
        ):
            raise ValueError("age_ns must be a non-negative integer or None")
        if self.reason is not None and (not isinstance(self.reason, str) or not self.reason.strip()):
            raise ValueError("reason must be non-empty when provided")

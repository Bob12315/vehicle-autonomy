from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SensorHealth:
    source_id: str
    healthy: bool
    reason_code: str
    last_capture_monotonic_ns: int | None = None

"""Clock-domain-aware time facts shared by core contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import total_ordering

from .primitives import Identifier


class ClockDomainId(Identifier):
    __slots__ = ()


@total_ordering
@dataclass(frozen=True, slots=True, eq=False)
class TimePoint:
    """A monotonic instant paired with UTC for logging and correlation."""

    monotonic_ns: int
    utc: datetime
    clock_domain_id: ClockDomainId

    def __post_init__(self) -> None:
        if isinstance(self.monotonic_ns, bool) or not isinstance(self.monotonic_ns, int):
            raise ValueError("monotonic_ns must be an integer")
        if self.monotonic_ns < 0:
            raise ValueError("monotonic_ns must be non-negative")
        if not isinstance(self.utc, datetime) or self.utc.tzinfo is None or self.utc.utcoffset() is None:
            raise ValueError("utc must be timezone-aware")
        object.__setattr__(self, "utc", self.utc.astimezone(timezone.utc))
        if not isinstance(self.clock_domain_id, ClockDomainId):
            object.__setattr__(self, "clock_domain_id", ClockDomainId(self.clock_domain_id))

    def elapsed_ns_since(self, earlier: "TimePoint") -> int:
        if not isinstance(earlier, TimePoint):
            raise TypeError("earlier must be a TimePoint")
        if self.clock_domain_id != earlier.clock_domain_id:
            raise ValueError("cannot compare different monotonic clock domains")
        return self.monotonic_ns - earlier.monotonic_ns

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, TimePoint):
            return NotImplemented
        return self.elapsed_ns_since(other) < 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TimePoint):
            return NotImplemented
        return (self.clock_domain_id, self.monotonic_ns) == (other.clock_domain_id, other.monotonic_ns)

    def __hash__(self) -> int:
        return hash((self.clock_domain_id, self.monotonic_ns))


@dataclass(frozen=True, slots=True)
class TimeFacts:
    """Distinct source, receive, and publication instants for one value."""

    captured_at: TimePoint | None = None
    received_at: TimePoint | None = None
    published_at: TimePoint | None = None

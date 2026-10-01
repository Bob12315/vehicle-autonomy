"""Explicit source-boot to host mapping for speed-one localhost SITL."""

from dataclasses import replace
from datetime import timedelta

from contracts.core.time import TimePoint


class SimulationSourceClock:
    """One mapping per link epoch; delayed/repeated poses keep their old age.

    This simulation composition requires speed-one SITL. Accelerated, reset,
    or excessively drifting source clocks fail closed and require a new epoch.
    No onboard timestamp is directly compared with host monotonic time.
    """

    def __init__(self):
        self.anchor: tuple[int, TimePoint] | None = None
        self.last_boot: dict[str, int] = {}

    def capture(self, message: object, received: TimePoint) -> TimePoint:
        kind = message.get_type()
        if kind not in ("LOCAL_POSITION_NED", "GLOBAL_POSITION_INT", "ATTITUDE"):
            return received
        boot = int(message.time_boot_ms)
        previous = self.last_boot.get(kind)
        if previous is not None and boot < previous:
            raise ValueError("SITL source boot time regressed; new epoch required")
        self.last_boot[kind] = boot
        if self.anchor is None:
            self.anchor = boot, received
        source0, host0 = self.anchor
        delta = (boot - source0) * 1_000_000
        capture_ns = host0.monotonic_ns + delta
        if capture_ns < 0 or capture_ns - received.monotonic_ns > 500_000_000:
            raise ValueError("SITL source clock outside speed-one mapping")
        capture_ns = min(capture_ns, received.monotonic_ns)
        return replace(received, monotonic_ns=capture_ns,
                       utc=received.utc + timedelta(microseconds=(capture_ns - received.monotonic_ns) // 1000))

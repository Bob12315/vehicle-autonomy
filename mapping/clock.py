"""Bounded interpolation between observed ROS /clock and host monotonic time.

Only a local simulated source is supported. This is not device clock sync.
Clock pauses and backwards jumps invalidate the old source epoch.
"""
from collections import deque
from uuid import uuid4


class RosClockBridge:
    def __init__(self, *, max_gap_ns=1_000_000_000):
        self.max_gap_ns = max_gap_ns
        self.pairs = deque(maxlen=2048)
        self.epoch = uuid4().hex

    def observe(self, ros_ns: int, host_ns: int) -> bool:
        if any(type(v) is not int or v < 0 for v in (ros_ns, host_ns)):
            raise ValueError("clock samples must be nonnegative integer nanoseconds")
        reset = False
        if self.pairs:
            previous_ros, previous_host = self.pairs[-1]
            if host_ns < previous_host:
                raise ValueError("host monotonic clock regressed")
            if ros_ns < previous_ros or host_ns - previous_host > self.max_gap_ns:
                self.pairs.clear()
                self.epoch = uuid4().hex
                reset = True
            elif ros_ns == previous_ros:
                return False  # Duplicate clock ticks must not refresh source age.
            elif ros_ns - previous_ros < 10_000_000:
                return False  # Bounded 100 Hz history even with a 1 kHz /clock.
        if ros_ns > 0:
            self.pairs.append((ros_ns, host_ns))
        return reset

    def _interpolate(self, value, axis):
        if type(value) is not int or value < 0:
            raise ValueError("invalid source timestamp")
        for sample in self.pairs:
            if sample[axis] == value:
                return sample[1 - axis]
        for first, second in zip(self.pairs, list(self.pairs)[1:]):
            if first[axis] < value < second[axis]:
                if max(second[i] - first[i] for i in (0, 1)) > self.max_gap_ns:
                    raise LookupError("clock interpolation gap")
                return first[1 - axis] + ((value - first[axis]) * (second[1 - axis] - first[1 - axis]) // (second[axis] - first[axis]))
        raise LookupError("clock is uninitialized or timestamp lies outside observed pairs")

    def to_host(self, ros_ns: int) -> int:
        return self._interpolate(ros_ns, 0)

    def to_ros(self, host_ns: int) -> int:
        return self._interpolate(host_ns, 1)

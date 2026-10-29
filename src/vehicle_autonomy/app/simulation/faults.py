"""Bounded faults on the owned Framework receive link, never fake EKF data.

Only incoming bytes are delayed/dropped/frozen. Writes are never queued beyond
the Execution fence: command-timeout injection fails before transport.write.
GPS/IMU/barometer faults require a separately qualified SITL mechanism.
"""
from collections import deque
from dataclasses import dataclass
import math
import random
from threading import RLock
import time


@dataclass(frozen=True)
class FaultSettings:
    delay_ms: float = 0
    loss: float = 0
    freeze: bool = False
    sensor_interruption: bool = False
    command_timeout: bool = False

    @classmethod
    def parse(cls, data):
        if type(data) is not dict or set(data) - set(cls.__dataclass_fields__):
            raise ValueError('unknown software fault fields')
        result = cls(**data)
        for name, upper in (('delay_ms', 2000), ('loss', 1)):
            value = getattr(result, name)
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= upper:
                raise ValueError('fault ' + name + ' out of range')
        for name in ('freeze', 'sensor_interruption', 'command_timeout'):
            if type(getattr(result, name)) is not bool:
                raise ValueError('fault switches require explicit booleans')
        return result


class SoftwareFaultLink:
    """Adapter around one already owned TCP stream; no vehicle command API."""
    def __init__(self, transport, *, seed=0, clock=time.monotonic):
        self.transport = transport
        self.clock = clock
        self.random = random.Random(seed)
        self.lock = RLock()
        self.settings = FaultSettings()
        self.queue = deque()
        self.last = None
        self.dropped = 0

    def configure(self, payload):
        settings = FaultSettings.parse(payload)
        with self.lock:
            self.settings = settings
            # Fault recovery cannot replay a backlog as new telemetry.
            self.queue.clear()
            self.last = None

    def read(self, max_bytes=4096):
        incoming = self.transport.read(max_bytes)
        with self.lock:
            settings = self.settings
            if settings.sensor_interruption:
                self.dropped += bool(incoming)
                return None
            if settings.freeze:
                # Replay the identical signed bytes; freshness/authentication
                # rejects them. No source timestamps are altered.
                if self.last is None:
                    self.last = incoming
                return self.last
            self.last = incoming
            if incoming:
                if self.random.random() < settings.loss:
                    self.dropped += 1
                elif len(self.queue) >= 256:
                    self.dropped += 1
                else:
                    self.queue.append((self.clock() + settings.delay_ms / 1000, incoming))
            if self.queue and self.queue[0][0] <= self.clock():
                return self.queue.popleft()[1]
            return None

    def write(self, data):
        with self.lock:
            if self.settings.command_timeout:
                raise TimeoutError('injected command timeout before write; no retry')
        self.transport.write(data)

    def close(self):
        self.transport.close()

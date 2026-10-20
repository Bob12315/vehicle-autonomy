"""Bounded PointCloud-to-planar-scan adapter and explicit health semantics."""
from __future__ import annotations

from dataclasses import dataclass
import math

from contracts.core.primitives import SchemaVersion
from contracts.core.quality import QualityState
from contracts.sensor import Observation


@dataclass(frozen=True, slots=True)
class ScanConfig:
    frame: str
    bins: int = 720
    range_min: float = .2
    range_max: float = 30.
    z_min: float = -.2
    z_max: float = 1.
    self_box: tuple = ()  # explicit lidar-frame xmin,xmax,ymin,ymax,zmin,zmax
    ground_z: float | None = None
    ground_tolerance: float = .1

    def __post_init__(self):
        object.__setattr__(self, 'self_box', tuple(self.self_box))
        values = (self.range_min, self.range_max, self.z_min, self.z_max, self.ground_tolerance)
        if (type(self.frame) is not str or not self.frame or type(self.bins) is not int or not 90 <= self.bins <= 4096
                or not all(type(v) in (int, float) and math.isfinite(v) for v in values)
                or not 0 < self.range_min < self.range_max <= 200 or self.z_min >= self.z_max
                or self.ground_tolerance < 0):
            raise ValueError('invalid explicit scan configuration')
        if self.ground_z is not None and (type(self.ground_z) not in (int,float) or not math.isfinite(self.ground_z)):
            raise ValueError('ground height must be finite')
        if self.self_box and (len(self.self_box) != 6 or not all(math.isfinite(v) for v in self.self_box)
                              or any(self.self_box[i] >= self.self_box[i+1] for i in (0, 2, 4))):
            raise ValueError('self box needs ordered finite lidar-frame bounds')


@dataclass(frozen=True, slots=True)
class PlanarScan:
    angle_min: float
    angle_increment: float
    range_min: float
    range_max: float
    ranges: tuple[float | None, ...]  # None means unobserved, never free space.


class ScanProcessor:
    def __init__(self, config, producer, epoch):
        self.config = config
        self.producer = producer
        self.epoch = epoch
        self.previous_sequence = None
        self.previous_capture = None
        self.last_received = None
        self.accepted = self.dropped = self.invalid_points = 0
        self.error = 'no cloud received'

    def convert(self, points, *, frame, sequence, captured_at, received_at, epoch):
        try:
            if frame != self.config.frame or epoch != self.epoch:
                raise ValueError('lidar frame/source epoch changed')
            if type(sequence) is not int or sequence < 0:
                raise ValueError('invalid cloud sequence')
            age = received_at.elapsed_ns_since(captured_at)
            if not 0 <= age <= 500_000_000:
                raise ValueError('cloud late or timestamp in future')
            if self.previous_sequence is not None:
                if sequence <= self.previous_sequence or captured_at <= self.previous_capture:
                    raise ValueError('duplicate/out-of-order cloud or timestamp regression')
                self.dropped += max(0, sequence - self.previous_sequence - 1)
            ranges = [None] * self.config.bins
            increment = 2 * math.pi / self.config.bins
            count = valid = 0
            for point in points:
                count += 1
                if count > 200_000:
                    raise ValueError('cloud point budget exceeded')
                if len(point) < 3 or not all(math.isfinite(v) for v in point[:3]):
                    self.invalid_points += 1
                    continue
                x, y, z = point[:3]
                valid += 1
                cfg = self.config
                if z < cfg.z_min or z > cfg.z_max:
                    continue
                if cfg.ground_z is not None and abs(z - cfg.ground_z) <= cfg.ground_tolerance:
                    continue
                if cfg.self_box and all(cfg.self_box[2*i] <= v <= cfg.self_box[2*i+1] for i, v in enumerate((x, y, z))):
                    continue
                radius = math.hypot(x, y)
                if not cfg.range_min <= radius <= cfg.range_max:
                    continue
                index = min(cfg.bins - 1, int((math.atan2(y, x) + math.pi) / increment))
                if ranges[index] is None or radius < ranges[index]:
                    ranges[index] = radius
            if not valid or not any(r is not None for r in ranges):
                raise ValueError('empty/invalid cloud after configured filtering')
            self.previous_sequence = sequence
            self.previous_capture = captured_at
            self.last_received = received_at
            self.accepted += 1
            self.error = None
            return Observation(f'{self.producer}:{epoch}:{sequence}', SchemaVersion(1, 0),
                self.producer, sequence, captured_at, received_at, QualityState.VALID,
                PlanarScan(-math.pi, increment, cfg.range_min, cfg.range_max, tuple(ranges)), frame)
        except (ValueError, TypeError, OverflowError) as exc:
            self.error = str(exc)
            raise ValueError(self.error) from exc

    def health(self, now):
        age = None if self.last_received is None else now.elapsed_ns_since(self.last_received)
        return {'accepted': self.accepted, 'dropped_clouds': self.dropped,
                'invalid_points': self.invalid_points, 'error': self.error,
                'receive_age_ns': age, 'online': self.error is None and age is not None and 0 <= age <= 500_000_000,
                'frame': self.config.frame, 'epoch': self.epoch}

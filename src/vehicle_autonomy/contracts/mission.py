"""Versioned, immutable graph and read-only observation ports (no device access)."""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from vehicle_autonomy.contracts.core.primitives import FrozenJson, freeze_json, thaw_json
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.world.models import WorldSnapshot


class Truth(str, Enum):
    TRUE = 'TRUE'
    FALSE = 'FALSE'
    UNKNOWN = 'UNKNOWN'


class WorldSnapshotProvider(Protocol):
    def snapshot(self) -> WorldSnapshot | None: ...


class EventSource(Protocol):
    @property
    def cursor(self) -> int: ...
    def read(self, after: int, name: str, now: TimePoint) -> tuple: ...


@dataclass(frozen=True, slots=True)
class BlackboardValue:
    value: FrozenJson
    observed_at: TimePoint
    valid_for_ns: int
    quality: str = 'VALID'
    frame: str | None = None
    source: str = 'mission'

    def __post_init__(self):
        if type(self.valid_for_ns) is not int or not 0 < self.valid_for_ns <= 3_600_000_000_000:
            raise ValueError('bounded value lifetime required')
        object.__setattr__(self, 'value', freeze_json(self.value))


@dataclass(frozen=True, slots=True)
class MissionSpec:
    document: FrozenJson

    def __post_init__(self):
        object.__setattr__(self, 'document', freeze_json(self.document))

    def to_dict(self):
        return thaw_json(self.document)

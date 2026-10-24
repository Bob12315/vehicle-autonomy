"""Standalone Action lifecycle and resource contracts, independent of devices."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from vehicle_autonomy.contracts.core.geometry import Pose3
from vehicle_autonomy.contracts.core.primitives import FrozenJson, freeze_json


class ActionKind(str, Enum):
    ONE_SHOT = 'OneShot'
    GOAL = 'Goal'
    CONTINUOUS = 'Continuous'
    QUERY = 'Query'


class ActionState(str, Enum):
    CREATED = 'CREATED'
    VALIDATING = 'VALIDATING'
    WAITING_RESOURCE = 'WAITING_RESOURCE'
    RUNNING = 'RUNNING'
    CANCELLING = 'CANCELLING'
    SUCCEEDED = 'SUCCEEDED'
    FAILED = 'FAILED'
    REJECTED = 'REJECTED'
    CANCELLED = 'CANCELLED'
    TIMED_OUT = 'TIMED_OUT'
    UNKNOWN = 'UNKNOWN'


TERMINAL_ACTION_STATES = frozenset({ActionState.SUCCEEDED, ActionState.FAILED,
    ActionState.REJECTED, ActionState.CANCELLED, ActionState.TIMED_OUT, ActionState.UNKNOWN})


class ResourceMode(str, Enum):
    SHARED = 'shared'
    EXCLUSIVE = 'exclusive'


@dataclass(frozen=True, slots=True)
class ActionResource:
    name: str
    mode: ResourceMode = ResourceMode.EXCLUSIVE
    conflict_group: str = ''

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip() or not isinstance(self.mode, ResourceMode):
            raise ValueError('resource name and access mode required')
        if not isinstance(self.conflict_group, str):
            raise TypeError('resource conflict group must be text')


@dataclass(frozen=True, slots=True)
class ActionContext:
    target_id: str
    target_kind: str
    capabilities: frozenset[str]
    owned_simulation: bool = False
    home: Pose3 | None = None
    metadata: FrozenJson = None

    def __post_init__(self):
        if not self.target_id or not self.target_kind or not isinstance(self.capabilities, frozenset):
            raise ValueError('immutable Action target context required')
        if type(self.owned_simulation) is not bool:
            raise TypeError('ownership must be an explicit bool')
        object.__setattr__(self, 'metadata', freeze_json(self.metadata))


@dataclass(frozen=True, slots=True)
class ActionSafety:
    release_safe: bool
    continuation_allowed: bool = False
    reason: str | None = None
    evidence: FrozenJson = None

    def __post_init__(self):
        if type(self.release_safe) is not bool or type(self.continuation_allowed) is not bool:
            raise TypeError('safety assessments require explicit booleans')
        if self.release_safe and self.continuation_allowed:
            raise ValueError('released resources cannot require a retained continuation')
        object.__setattr__(self, 'evidence', freeze_json(self.evidence))

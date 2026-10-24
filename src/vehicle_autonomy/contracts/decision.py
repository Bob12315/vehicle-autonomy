"""Typed, command-free Mission and Action decision contracts."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import re
from types import UnionType
from typing import Any, Literal, Protocol, Union, get_args, get_origin, get_type_hints

from vehicle_autonomy.contracts.core.primitives import FrozenJson, freeze_json, thaw_json, is_deeply_immutable
from vehicle_autonomy.contracts.action import ActionKind, ActionResource, ActionSafety
from vehicle_autonomy.contracts.effects.vehicle import (
    ArmEffect, DisarmEffect, LandEffect, ModeEffect, PoseTargetEffect,
    StopMotionEffect, TakeoffEffect, TwistTargetEffect, VehicleEffect, FixedWingTargetEffect,
)
from vehicle_autonomy.contracts.world.models import WorldSnapshot
from vehicle_autonomy.contracts.effects.payload import ReleasePayloadEffect

DecisionEffect = VehicleEffect | ReleasePayloadEffect


VEHICLE_EFFECT_TYPES = (
    ArmEffect, DisarmEffect, TakeoffEffect, LandEffect,
    ModeEffect, PoseTargetEffect, TwistTargetEffect, StopMotionEffect, FixedWingTargetEffect,
)

DECISION_EFFECT_TYPES = VEHICLE_EFFECT_TYPES + (ReleasePayloadEffect,)

def _matches_type(value: object, annotation: object) -> bool:
    """Check the small, explicit annotation grammar used by Action parameters."""
    if annotation is Any or annotation is object:
        return False
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (Union, UnionType):
        return any(_matches_type(value, option) for option in args)
    if origin is Literal:
        return value in args
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        if len(args) == 2 and args[1] is Ellipsis:
            return all(_matches_type(item, args[0]) for item in value)
        return len(value) == len(args) and all(_matches_type(item, kind) for item, kind in zip(value, args))
    if origin is frozenset:
        return isinstance(value, frozenset) and len(args) == 1 and all(_matches_type(item, args[0]) for item in value)
    if annotation is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if annotation in (int, bool, str):
        return type(value) is annotation
    if annotation is type(None):
        return value is None
    if isinstance(annotation, type):
        return isinstance(value, annotation)
    return False


@dataclass(frozen=True, slots=True)
class ActionSpec:
    name: str
    parameters_type: type
    required_capabilities: frozenset[str] = frozenset()
    effect_types: tuple[type, ...] = ()
    effect_ttl_ns: int = 1_000_000_000
    version: str = '1.0.0'
    description: str = ''
    kind: ActionKind = ActionKind.ONE_SHOT
    vehicle_types: frozenset[str] = frozenset()
    resources: tuple[ActionResource, ...] = ()
    required_state: tuple[str, ...] = ()
    max_snapshot_age_ns: int = 3_000_000_000
    default_timeout_ns: int = 15_000_000_000
    max_timeout_ns: int = 600_000_000_000
    exit_timeout_ns: int = 8_000_000_000
    output_schema: FrozenJson = None
    vehicle_parameter_overrides: FrozenJson = None
    vehicle_timeout_overrides: FrozenJson = None
    effect_ttl_overrides: FrozenJson = None
    implementation_ref: str = ''
    success_semantics: str = ''
    cancel_semantics: str = 'Exit barrier; uncertain physical effects retain resources.'

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Action name must be non-empty")
        if not isinstance(self.parameters_type, type) or not is_dataclass(self.parameters_type):
            raise TypeError("parameters_type must be a dataclass type")
        if not self.parameters_type.__dataclass_params__.frozen:
            raise TypeError("Action parameters must use a frozen dataclass")
        if not isinstance(self.required_capabilities, frozenset) or any(
            not isinstance(name, str) or not name.strip() for name in self.required_capabilities
        ):
            raise ValueError("required_capabilities must be non-empty names")
        if not isinstance(self.effect_types, tuple) or any(effect_type not in DECISION_EFFECT_TYPES for effect_type in self.effect_types):
            raise TypeError("effect_types must be registered typed decision effects")
        if isinstance(self.effect_ttl_ns, bool) or not isinstance(self.effect_ttl_ns, int) or self.effect_ttl_ns <= 0:
            raise ValueError("effect_ttl_ns must be positive")
        if re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', self.version) is None:
            raise ValueError('Action version must be MAJOR.MINOR.PATCH')
        if not isinstance(self.kind, ActionKind) or not isinstance(self.vehicle_types, frozenset):
            raise TypeError('typed Action kind and immutable vehicle types required')
        if any(not isinstance(v, str) or not v for v in self.vehicle_types):
            raise ValueError('invalid vehicle kind')
        if not isinstance(self.resources, tuple) or any(not isinstance(r, ActionResource) for r in self.resources):
            raise TypeError('immutable Action resource declarations required')
        if self.kind is ActionKind.QUERY and self.effect_types:
            raise ValueError('Query Actions cannot declare vehicle or payload effects')
        if not isinstance(self.required_state, tuple) or any(not isinstance(v,str) or not v for v in self.required_state):
            raise ValueError('required state names must be immutable nonempty strings')
        times = (self.max_snapshot_age_ns, self.default_timeout_ns, self.max_timeout_ns, self.exit_timeout_ns)
        if any(type(v) is not int or v <= 0 for v in times) or self.default_timeout_ns > self.max_timeout_ns:
            raise ValueError('bounded positive Action times required')
        for name in ('description','implementation_ref','success_semantics','cancel_semantics'):
            if not isinstance(getattr(self,name), str):raise TypeError('Action metadata must be text')
        object.__setattr__(self,'output_schema',freeze_json(self.output_schema))
        object.__setattr__(self,'vehicle_parameter_overrides',freeze_json(self.vehicle_parameter_overrides))
        object.__setattr__(self,'vehicle_timeout_overrides',freeze_json(self.vehicle_timeout_overrides))
        object.__setattr__(self,'effect_ttl_overrides',freeze_json(self.effect_ttl_overrides))
        ttls=thaw_json(self.effect_ttl_overrides) or {}
        if not isinstance(ttls,dict) or ttls.keys()-{t.__name__ for t in self.effect_types} or any(type(v) is not int or v<=0 for v in ttls.values()):
            raise ValueError('declared positive per-effect TTLs required')
        overrides=thaw_json(self.vehicle_timeout_overrides) or {}
        if not isinstance(overrides,dict):raise TypeError('vehicle timeouts must be an object')
        for kind,limits in overrides.items():
            if not isinstance(limits,dict) or limits.keys()-{'default_timeout_ns','max_timeout_ns'}:raise ValueError('unknown Action timeout override')
            default=limits.get('default_timeout_ns',self.default_timeout_ns);maximum=limits.get('max_timeout_ns',self.max_timeout_ns)
            if type(default) is not int or type(maximum) is not int or not 0<default<=maximum<=self.max_timeout_ns:
                raise ValueError('vehicle-specific Action timeout outside global bounds')

    def validate_parameters(self, parameters: object) -> None:
        if type(parameters) is not self.parameters_type or not is_deeply_immutable(parameters):
            raise TypeError(f"parameters for {self.name} must be immutable {self.parameters_type.__name__}")
        annotations = get_type_hints(self.parameters_type)
        for field in fields(parameters):
            if field.name not in annotations or not _matches_type(getattr(parameters, field.name), annotations[field.name]):
                raise TypeError(f"parameter {field.name} for {self.name} violates its declared type")


class ActionOutcome(str, Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class EffectPhase(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    TRANSMITTED = "TRANSMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class EffectResult:
    effect_id: str
    action_instance_id: str
    phase: EffectPhase
    command_id: str | None = None
    link_session_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.effect_id or not self.action_instance_id or not isinstance(self.phase, EffectPhase):
            raise ValueError("effect result requires IDs and a phase")


class ExitReason(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class ActionDecision:
    outcome: ActionOutcome
    effects: tuple[DecisionEffect, ...] = ()
    result: FrozenJson = None
    error: str | None = None
    feedback: FrozenJson = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ActionOutcome):
            raise TypeError("outcome must be ActionOutcome")
        if not isinstance(self.effects, tuple) or any(not isinstance(effect, DECISION_EFFECT_TYPES) for effect in self.effects):
            raise TypeError("effects must be typed effect values")
        object.__setattr__(self, "result", freeze_json(self.result))
        object.__setattr__(self, "feedback", freeze_json(self.feedback))
        if self.outcome is ActionOutcome.RUNNING and (self.result is not None or self.error is not None):
            raise ValueError("running Action cannot have a result or error")
        if self.outcome is ActionOutcome.FAILED and (not isinstance(self.error, str) or not self.error.strip()):
            raise ValueError("failed Action requires an error")
        if self.outcome is ActionOutcome.SUCCEEDED and self.error is not None:
            raise ValueError("successful Action cannot have an error")


@dataclass(frozen=True, slots=True)
class ExitDecision:
    complete: bool
    effects: tuple[DecisionEffect, ...] = ()
    safety: ActionSafety | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be bool")
        if not isinstance(self.effects, tuple) or any(not isinstance(effect, DECISION_EFFECT_TYPES) for effect in self.effects):
            raise TypeError("exit effects must be typed effect values")
        if self.safety is not None and not isinstance(self.safety,ActionSafety):raise TypeError('typed exit safety required')


class ActionInstance(Protocol):
    def tick(self, snapshot: WorldSnapshot) -> ActionDecision:
        """Read one stable snapshot and request typed effects."""

    def exit(self, snapshot: WorldSnapshot, reason: ExitReason) -> ExitDecision:
        """Report completion of the exit barrier, optionally requesting stop effects."""


class ActionFactory(Protocol):
    def start(self, parameters: object, snapshot: WorldSnapshot) -> ActionInstance:
        """Create one Action attempt without receiving a command port."""


class FailurePolicy(str, Enum):
    STOP = "STOP"
    CONTINUE = "CONTINUE"


@dataclass(frozen=True, slots=True)
class MissionStep:
    step_id: str
    action: str
    parameters: object
    max_attempts: int = 1
    on_failure: FailurePolicy = FailurePolicy.STOP

    def __post_init__(self) -> None:
        if not isinstance(self.step_id, str) or not self.step_id.strip():
            raise ValueError("step_id must be non-empty")
        if not isinstance(self.action, str) or not self.action.strip():
            raise ValueError("action must be non-empty")
        if not is_deeply_immutable(self.parameters):
            raise TypeError("Mission parameters must be deeply immutable")
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if not isinstance(self.on_failure, FailurePolicy):
            raise TypeError("on_failure must be FailurePolicy")


@dataclass(frozen=True, slots=True)
class MissionPlan:
    name: str
    steps: tuple[MissionStep, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Mission name must be non-empty")
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ValueError("Mission requires steps")
        if any(not isinstance(step, MissionStep) for step in self.steps):
            raise TypeError("Mission steps must be MissionStep")
        ids = tuple(step.step_id for step in self.steps)
        if len(ids) != len(set(ids)):
            raise ValueError("Mission step IDs must be unique")

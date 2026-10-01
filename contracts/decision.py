"""Typed, command-free Mission and Action decision contracts."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from types import UnionType
from typing import Any, Literal, Protocol, Union, get_args, get_origin, get_type_hints

from contracts.core.primitives import FrozenJson, freeze_json, is_deeply_immutable
from contracts.effects.vehicle import (
    ArmEffect, DisarmEffect, LandEffect, ModeEffect, PoseTargetEffect,
    StopMotionEffect, TakeoffEffect, TwistTargetEffect, VehicleEffect,
)
from contracts.world.models import WorldSnapshot


VEHICLE_EFFECT_TYPES = (
    ArmEffect, DisarmEffect, TakeoffEffect, LandEffect,
    ModeEffect, PoseTargetEffect, TwistTargetEffect, StopMotionEffect,
)


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
        if not isinstance(self.effect_types, tuple) or any(effect_type not in VEHICLE_EFFECT_TYPES for effect_type in self.effect_types):
            raise TypeError("effect_types must be registered typed vehicle effects")
        if isinstance(self.effect_ttl_ns, bool) or not isinstance(self.effect_ttl_ns, int) or self.effect_ttl_ns <= 0:
            raise ValueError("effect_ttl_ns must be positive")

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
    effects: tuple[VehicleEffect, ...] = ()
    result: FrozenJson = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ActionOutcome):
            raise TypeError("outcome must be ActionOutcome")
        if not isinstance(self.effects, tuple) or any(not isinstance(effect, VEHICLE_EFFECT_TYPES) for effect in self.effects):
            raise TypeError("effects must be typed effect values")
        object.__setattr__(self, "result", freeze_json(self.result))
        if self.outcome is ActionOutcome.RUNNING and (self.result is not None or self.error is not None):
            raise ValueError("running Action cannot have a result or error")
        if self.outcome is ActionOutcome.FAILED and (not isinstance(self.error, str) or not self.error.strip()):
            raise ValueError("failed Action requires an error")
        if self.outcome is ActionOutcome.SUCCEEDED and self.error is not None:
            raise ValueError("successful Action cannot have an error")


@dataclass(frozen=True, slots=True)
class ExitDecision:
    complete: bool
    effects: tuple[VehicleEffect, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be bool")
        if not isinstance(self.effects, tuple) or any(not isinstance(effect, VEHICLE_EFFECT_TYPES) for effect in self.effects):
            raise TypeError("exit effects must be typed effect values")


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

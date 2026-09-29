"""Contracts used to compose vehicle-specific behavior at the application edge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar, runtime_checkable

from contracts.core.effects import Effect
from contracts.core.execution import SafetyEvaluator
from contracts.platform.vehicle_commands import VehicleCommand


@dataclass(frozen=True, slots=True)
class VehicleCapabilities:
    vehicle_type: str
    supported: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.supported, frozenset):
            raise TypeError("supported capabilities must be a frozenset")
        if not self.vehicle_type or any(not isinstance(item, str) or not item for item in self.supported):
            raise ValueError("vehicle type and capability names must be non-empty")

    def missing(self, required: frozenset[str]) -> frozenset[str]:
        return required - self.supported


@dataclass(frozen=True, slots=True)
class VehicleHealth:
    connected: bool
    stale: bool
    control_allowed: bool
    reason_code: str | None = None


ActionDefinitionT = TypeVar("ActionDefinitionT", covariant=True)


@runtime_checkable
class VehiclePlugin(Protocol[ActionDefinitionT]):
    @property
    def capabilities(self) -> VehicleCapabilities: ...

    @property
    def actions(self) -> tuple[ActionDefinitionT, ...]: ...

    def health(self) -> VehicleHealth: ...

    def translate_effect(self, effect: Effect) -> VehicleCommand: ...

    def safety_policy(self) -> SafetyEvaluator: ...

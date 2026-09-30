"""Explicit Action registration; there is no global application catalog."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.decision import ActionFactory, ActionSpec
from contracts.core.models import ActionDefinition
from contracts.core.ports import Action


@dataclass(frozen=True)
class RegisteredAction:
    definition: ActionDefinition
    implementation: Action


@dataclass(frozen=True)
class RegisteredTypedAction:
    spec: ActionSpec
    factory: ActionFactory


class ActionRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, RegisteredAction] = {}
        self._typed_entries: dict[str, RegisteredTypedAction] = {}

    def register(self, definition: ActionDefinition, implementation: Action) -> None:
        if not definition.name or definition.name in self._entries or definition.name in self._typed_entries:
            raise ValueError(f"Action name is empty or already registered: {definition.name!r}")
        self._entries[definition.name] = RegisteredAction(definition, implementation)

    def register_typed(self, spec: ActionSpec, factory: ActionFactory) -> None:
        if spec.name in self._entries or spec.name in self._typed_entries:
            raise ValueError(f"Action name is already registered: {spec.name!r}")
        self._typed_entries[spec.name] = RegisteredTypedAction(spec, factory)

    def resolve(self, name: str) -> RegisteredAction:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise ValueError(f"Action is not registered: {name}") from exc

    def resolve_typed(self, name: str) -> RegisteredTypedAction:
        try:
            return self._typed_entries[name]
        except KeyError as exc:
            raise ValueError(f"Typed Action is not registered: {name}") from exc

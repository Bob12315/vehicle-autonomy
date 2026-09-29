"""Explicit Action registration; there is no global application catalog."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.core.models import ActionDefinition
from contracts.core.ports import Action


@dataclass(frozen=True)
class RegisteredAction:
    definition: ActionDefinition
    implementation: Action


class ActionRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, RegisteredAction] = {}

    def register(self, definition: ActionDefinition, implementation: Action) -> None:
        if not definition.name or definition.name in self._entries:
            raise ValueError(f"Action name is empty or already registered: {definition.name!r}")
        self._entries[definition.name] = RegisteredAction(definition, implementation)

    def resolve(self, name: str) -> RegisteredAction:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise ValueError(f"Action is not registered: {name}") from exc

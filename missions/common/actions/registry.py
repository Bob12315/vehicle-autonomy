from __future__ import annotations

from typing import TYPE_CHECKING

from .base import ActionModule

if TYPE_CHECKING:
    from missions.definitions import ActionDefinition


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, type[ActionModule]] = {}
        self._definitions: dict[str, ActionDefinition] = {}

    def register(
        self,
        name: str,
        action_cls: type[ActionModule],
        *,
        overwrite: bool = False,
        definition: ActionDefinition | None = None,
    ) -> None:
        normalized = self._validate_name(name)
        if not isinstance(action_cls, type) or not issubclass(action_cls, ActionModule):
            raise TypeError("action_cls must be an ActionModule subclass")
        if normalized in self._actions and not overwrite:
            raise ValueError(f"action already registered: {normalized}")
        if definition is not None and (definition.name != normalized or definition.factory is not action_cls):
            raise ValueError("Action definition must match registered name and factory")
        self._actions[normalized] = action_cls
        if definition is None and not overwrite:
            self._definitions.pop(normalized, None)
        elif definition is not None:
            self._definitions[normalized] = definition

    def definition(self, name: str) -> ActionDefinition | None:
        return self._definitions.get(self._validate_name(name))

    def get(self, name: str) -> type[ActionModule]:
        normalized = self._validate_name(name)
        try:
            return self._actions[normalized]
        except KeyError as exc:
            raise KeyError(f"unknown action: {normalized}") from exc

    def create(self, name: str) -> ActionModule:
        return self.get(name)()

    def list(self) -> list[str]:
        return sorted(self._actions)

    def clear(self) -> None:
        self._actions.clear()
        self._definitions.clear()

    def _validate_name(self, name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("action name must be a non-empty string")
        return name.strip()


default_registry = ActionRegistry()

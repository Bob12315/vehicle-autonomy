"""Small immutable descriptions used by the new framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class Effect:
    """A requested operation; it grants no authority to send a command."""

    operation: str
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    required_capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ActionStep:
    step_id: str
    action: str
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MissionDefinition:
    name: str
    steps: tuple[ActionStep, ...]

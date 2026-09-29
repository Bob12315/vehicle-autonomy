"""Ports available to Actions and Execution."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from contracts.core.models import Effect
from contracts.world.models import WorldSnapshot


class Action(Protocol):
    def plan(self, snapshot: WorldSnapshot, parameters: Mapping[str, object]) -> Sequence[Effect]:
        """Produce effects without access to a vehicle command port."""


class SafetyPolicy(Protocol):
    def evaluate(self, effect: Effect, snapshot: WorldSnapshot) -> bool:
        """Return true only if this effect is explicitly allowed."""

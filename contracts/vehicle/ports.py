"""Vehicle facing contracts; concrete adapters are not part of Core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from contracts.core.models import Effect


@dataclass(frozen=True)
class VehicleCapabilities:
    names: frozenset[str] = frozenset()


class VehicleCommandPort(Protocol):
    def submit(self, effect: Effect) -> None:
        """Submit one previously authorized and safety checked effect."""

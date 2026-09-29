"""Minimal world snapshot for future perception and environment adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class WorldSnapshot:
    revision: int
    observations: Mapping[str, object] = field(default_factory=dict)

"""Read-only World and Localization access plus the unified transform contract."""

from __future__ import annotations

from typing import Protocol, TypeVar

from contracts.core.geometry import FrameId
from contracts.core.time import TimePoint
from contracts.localization.models import LocalizationEstimate
from .models import WorldSnapshot

T = TypeVar("T")


class LocalizationPort(Protocol):
    def current(self) -> LocalizationEstimate | None:
        """Return the latest immutable localization estimate, if available."""


class WorldQueryPort(Protocol):
    def snapshot(self) -> WorldSnapshot[object] | None:
        """Return one immutable, versioned world snapshot."""


class TransformResolver(Protocol):
    def transform(
        self,
        value: T,
        *,
        from_frame: FrameId,
        to_frame: FrameId,
        at_time: TimePoint,
    ) -> T:
        """Transform a typed spatial value at the requested time."""

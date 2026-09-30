"""Spatial values paired with the frame and sampling time they belong to."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from .geometry import FrameId
from .primitives import is_deeply_immutable
from .time import TimePoint

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Stamped(Generic[T]):
    frame_id: FrameId
    captured_at: TimePoint
    value: T

    def __post_init__(self) -> None:
        if not isinstance(self.frame_id, FrameId):
            object.__setattr__(self, "frame_id", FrameId(self.frame_id))
        if not isinstance(self.captured_at, TimePoint):
            raise TypeError("captured_at must be a TimePoint")
        if not is_deeply_immutable(self.value):
            raise TypeError("stamped value must be deeply immutable")

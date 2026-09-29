"""In-process camera frames; no OpenCV or device-specific type crosses the port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from contracts.platform.common import ClockStamp

from .health import SensorHealth


@dataclass(frozen=True, slots=True)
class CameraFrame:
    source_id: str
    frame_id: int
    captured_at: ClockStamp
    width_px: int
    height_px: int
    pixel_format: str
    pixels: memoryview
    wait_frame_ms: float = 0.0
    source_read_ms: float = 0.0

    def __post_init__(self) -> None:
        if not self.source_id or self.frame_id < 0 or self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("invalid camera frame identity or geometry")
        if self.pixel_format != "BGR8":
            raise ValueError("unsupported camera pixel format")
        if not self.pixels.readonly or not self.pixels.c_contiguous:
            raise ValueError("camera pixels must be a contiguous read-only view")
        if self.pixels.nbytes != self.width_px * self.height_px * 3:
            raise ValueError("camera pixel buffer size mismatch")


@runtime_checkable
class CameraPort(Protocol):
    def read(self) -> CameraFrame | None: ...
    def close(self) -> None: ...
    def health(self) -> SensorHealth: ...

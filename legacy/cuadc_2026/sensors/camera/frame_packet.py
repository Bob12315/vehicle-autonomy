"""Raw capture packet produced by the existing VideoSource."""

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FramePacket:
    frame: Any
    frame_id: int
    timestamp: float
    captured_at_monotonic_ns: int = 0
    wait_frame_ms: float = 0.0
    source_read_ms: float = 0.0

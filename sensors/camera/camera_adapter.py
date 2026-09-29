"""Compatibility CameraPort around the existing VideoSource capture behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
import uuid

import numpy as np

from contracts.platform.common import ClockStamp
from contracts.sensors import CameraFrame, SensorHealth

try:
    from .video_source import VideoSource
except ImportError:  # direct yolo_app/main.py execution
    from video_source import VideoSource


class VideoSourceCameraAdapter:
    def __init__(self, source: str, *, camera_width: int = 640,
                 camera_height: int = 480, camera_fps: int = 30,
                 camera_fourcc: str = "MJPG", latest_frame: bool = False,
                 source_factory: Callable[..., VideoSource] = VideoSource) -> None:
        self.source_id = source
        self.clock_domain_id = f"camera:{uuid.uuid4().hex}"
        self._source = source_factory(
            source, camera_width=camera_width, camera_height=camera_height,
            camera_fps=camera_fps, camera_fourcc=camera_fourcc,
            latest_frame=latest_frame,
        )
        self._closed = False
        self._exhausted = False
        self._last_capture_ns: int | None = None
        self._last_error: str | None = None

    def read(self) -> CameraFrame | None:
        if self._closed:
            raise RuntimeError("camera_closed")
        try:
            packet = self._source.read()
            if packet is None:
                self._exhausted = True
                return None
            self._exhausted = False
            pixels = np.ascontiguousarray(packet.frame)
            if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
                raise ValueError("camera source must produce BGR8 frames")
            height, width = pixels.shape[:2]
            self._last_capture_ns = int(packet.captured_at_monotonic_ns)
            self._last_error = None
            return CameraFrame(
                self.source_id, int(packet.frame_id),
                ClockStamp(datetime.fromtimestamp(packet.timestamp, timezone.utc),
                           self._last_capture_ns, self.clock_domain_id),
                width, height, "BGR8", memoryview(pixels).toreadonly(),
                float(packet.wait_frame_ms), float(packet.source_read_ms),
            )
        except Exception as exc:
            self._last_error = type(exc).__name__
            raise

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._source.release()

    def health(self) -> SensorHealth:
        return SensorHealth(self.source_id,
                            not self._closed and not self._exhausted and self._last_error is None,
                            "closed" if self._closed else self._last_error or (
                                "end_of_stream" if self._exhausted else "ok"),
                            self._last_capture_ns)

    @property
    def capture(self):
        """Legacy video-writer FPS lookup during the compatibility period."""
        return self._source.cap


def camera_frame_to_bgr(frame: CameraFrame) -> np.ndarray:
    if frame.pixel_format != "BGR8":
        raise ValueError("unsupported camera pixel format")
    return np.frombuffer(frame.pixels, dtype=np.uint8).reshape(
        frame.height_px, frame.width_px, 3)

"""RKNN detection, tracking and result assembly; no UDP or camera ownership."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from contracts.platform.perception import Detection, PerceptionResult, PerceptionTarget
from contracts.sensors import CameraFrame

try:
    from .models import CurrentTarget, SceneDetections, Track
    from .target_manager import TargetManager, build_scene_detections
    from .tracker_runner import TrackerRunner
except ImportError:  # direct yolo_app/main.py execution
    from models import CurrentTarget, SceneDetections, Track
    from target_manager import TargetManager, build_scene_detections
    from tracker_runner import TrackerRunner


@dataclass(frozen=True, slots=True)
class PipelineResult:
    perception: PerceptionResult
    target: CurrentTarget
    scene: SceneDetections


class YoloPerceptionPipeline:
    def __init__(self, cfg, *, tracker_factory: Callable = TrackerRunner,
                 target_factory: Callable = TargetManager) -> None:
        self.tracker = tracker_factory(cfg)
        self.target_manager = target_factory(cfg)

    def submit(self, frame, *, valid_mask=None):
        return self.tracker.submit(frame, valid_mask=valid_mask)

    def complete(self, ticket) -> list[Track]:
        return self.tracker.complete(ticket)

    def cancel(self, ticket) -> None:
        self.tracker.cancel(ticket)

    def reset(self) -> None:
        self.tracker.reset()
        self.target_manager.invalidate()

    def apply_command(self, command, tracks: list[Track]) -> bool:
        return self.target_manager.apply_command(command, tracks)

    @property
    def locked_track_id(self) -> int | None:
        return self.target_manager.locked_track_id

    @property
    def last_metrics_ms(self) -> dict[str, float]:
        return self.tracker.last_metrics_ms

    def finish(self, tracks: list[Track], camera_frame: CameraFrame,
               *, image_width: int, image_height: int) -> PipelineResult:
        timestamp = camera_frame.captured_at.utc.timestamp()
        target = self.target_manager.update(
            tracks=tracks, image_width=image_width, image_height=image_height,
            frame_id=camera_frame.frame_id, timestamp=timestamp,
        )
        scene = build_scene_detections(
            tracks=tracks, image_width=image_width, image_height=image_height,
            frame_id=camera_frame.frame_id, timestamp=timestamp,
        )
        perception = PerceptionResult(
            camera_frame.frame_id, camera_frame.captured_at,
            image_width, image_height,
            PerceptionTarget(target.track_id, target.class_name,
                             target.confidence, target.cx, target.cy)
            if target.target_valid else None,
            tuple(Detection(item.track_id, item.class_id, item.class_name,
                            item.confidence, item.x1, item.y1, item.x2, item.y2)
                  for item in scene.detections),
        )
        return PipelineResult(perception, target, scene)

    def release(self) -> None:
        self.tracker.release()

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import numpy as np
import pytest

from contracts.sensors import CameraFrame, CameraPort, PointCloudFrame
from yolo_app.camera_adapter import VideoSourceCameraAdapter, camera_frame_to_bgr
from yolo_app.models import FramePacket
from yolo_app.models import Track
from yolo_app.perception_pipeline import YoloPerceptionPipeline
from yolo_app.udp_publisher import UdpPublisher


class FakeVideoSource:
    def __init__(self, source, **_kwargs):
        self.source = source
        self.cap = None
        self.released = False

    def read(self):
        return FramePacket(np.zeros((3, 4, 3), dtype=np.uint8), 7, 123.0, 456)

    def release(self):
        self.released = True


def test_existing_video_source_is_exposed_as_camera_port() -> None:
    camera = VideoSourceCameraAdapter("/dev/video0", source_factory=FakeVideoSource)
    assert isinstance(camera, CameraPort)
    frame = camera.read()
    assert isinstance(frame, CameraFrame)
    assert frame.source_id == "/dev/video0"
    assert (frame.frame_id, frame.width_px, frame.height_px) == (7, 4, 3)
    assert frame.captured_at.monotonic_ns == 456
    assert frame.pixels.readonly
    image = camera_frame_to_bgr(frame)
    assert image.shape == (3, 4, 3) and not image.flags.writeable
    with pytest.raises(FrozenInstanceError):
        frame.frame_id = 8
    assert camera.health().healthy
    camera.close()
    assert not camera.health().healthy and camera._source.released
    with pytest.raises(RuntimeError, match="camera_closed"):
        camera.read()


def test_point_cloud_is_only_a_contract() -> None:
    frame = VideoSourceCameraAdapter("/dev/video0", source_factory=FakeVideoSource).read()
    cloud = PointCloudFrame("lidar-future", 1, frame.captured_at, "sensor", 1,
                            ((1.0, 2.0, 3.0),))
    assert cloud.point_count == 1
    with pytest.raises(ValueError, match="point count"):
        PointCloudFrame("lidar-future", 1, frame.captured_at, "sensor", 2,
                        ((1.0, 2.0, 3.0),))


def test_camera_health_reports_end_of_stream() -> None:
    class EmptyVideoSource(FakeVideoSource):
        def read(self): return None

    camera = VideoSourceCameraAdapter("file.mp4", source_factory=EmptyVideoSource)
    assert camera.read() is None
    assert not camera.health().healthy
    assert camera.health().reason_code == "end_of_stream"
    camera.close()


def test_pipeline_produces_typed_result_and_legacy_udp_projection() -> None:
    camera = VideoSourceCameraAdapter("/dev/video0", source_factory=FakeVideoSource)
    frame = camera.read()

    class Tracker:
        def __init__(self, _cfg): pass
        def release(self): pass

    cfg = SimpleNamespace(max_lost_frames=3, selection_mode="center", target_class="")
    pipeline = YoloPerceptionPipeline(cfg, tracker_factory=Tracker)
    result = pipeline.finish([Track(3, 1, "target", .9, 1, 0, 3, 2)], frame,
                             image_width=4, image_height=3)
    assert result.perception.frame_id == result.target.frame_id == result.scene.frame_id
    assert result.perception.target.track_id == 3
    assert result.perception.detections[0].class_name == "target"
    assert result.target.target_valid
    publisher = object.__new__(UdpPublisher)
    calls = []
    publisher.publish = lambda *args: calls.append(args)
    publisher.publish_result(result)
    assert calls[0][0] is result.target and calls[0][1] is result.scene
    assert calls[0][3] == frame.captured_at.monotonic_ns
    pipeline.release()
    camera.close()

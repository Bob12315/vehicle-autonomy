"""Deterministic offline detector source; no camera or process connection."""

from __future__ import annotations

from contracts.core.geometry import FrameId, Vector3
from contracts.core.primitives import ProducerId, SchemaVersion
from contracts.core.quality import QualityState
from contracts.core.time import TimePoint
from contracts.sensor import DetectedObject, Observation


class FakeDetectionSensor:
    def __init__(self, producer_id: ProducerId, schema_version: SchemaVersion = SchemaVersion(1, 0)) -> None:
        self.producer_id = ProducerId(producer_id)
        self.schema_version = schema_version
        self._sequence = 0

    def observe(
        self, *, object_id: str, label: str, position: Vector3, confidence: float,
        frame_id: FrameId, captured_at: TimePoint, received_at: TimePoint,
        quality: QualityState = QualityState.VALID,
    ) -> Observation[DetectedObject]:
        if captured_at.clock_domain_id == received_at.clock_domain_id and received_at < captured_at:
            raise ValueError("received_at cannot precede captured_at")
        data = DetectedObject(object_id, label, position, confidence)
        sequence = self._sequence + 1
        observation = Observation(
            f"{self.producer_id}:{sequence}", self.schema_version,
            self.producer_id, sequence, captured_at, received_at,
            quality, data, frame_id,
        )
        self._sequence = sequence
        return observation

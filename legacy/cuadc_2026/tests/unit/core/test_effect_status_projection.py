from datetime import datetime, timezone

from application.core.effect_delivery import EffectStatusQuery
from application.core.effect_status_projection import PlatformEffectStatusProjection
from contracts.core.action import (
    EffectAckFeedbackState,
    EffectCompletionFeedbackState,
    EffectTransportFeedbackState,
)
from contracts.core.common import EffectId
from contracts.core.effects import EffectKind
from contracts.core.time import CoreTime
from contracts.platform.common import LeaseGeneration, RunExecutionGeneration
from contracts.platform.perception import RecordingState, VisionCommandStatus, VisionResultState
from contracts.platform.vehicle_commands import (
    AckState, CommandStatusSnapshot, CompletionState, QueueState,
    SubmissionState, TransportState,
)


class StatusPort:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def status(self, command_id):
        assert command_id == self.snapshot.command_id
        return self.snapshot


def _query(kind: EffectKind, command_id: str, revision=None) -> EffectStatusQuery:
    return EffectStatusQuery(
        EffectId("effect-1"), command_id, kind, "local-1", 1,
        RunExecutionGeneration(1), LeaseGeneration(1), revision,
    )


def _now() -> CoreTime:
    return CoreTime(1, datetime(2026, 1, 1, tzinfo=timezone.utc), "test")


def test_vehicle_status_projects_transport_ack_and_completion() -> None:
    vehicle = CommandStatusSnapshot(
        "vehicle-1", SubmissionState.ACCEPTED, QueueState.DEQUEUED,
        TransportState.TRANSMITTED, AckState.ACKED, CompletionState.OBSERVED,
        2, "completed",
    )
    projection = PlatformEffectStatusProjection(StatusPort(vehicle), StatusPort(None))
    observations = projection.observe((_query(EffectKind.ARM, "vehicle-1"),), _now())
    assert len(observations) == 1
    lifecycle = observations[0].lifecycle
    assert lifecycle.transport is EffectTransportFeedbackState.TRANSMITTED
    assert lifecycle.ack is EffectAckFeedbackState.ACKNOWLEDGED
    assert lifecycle.completion is EffectCompletionFeedbackState.COMPLETED
    assert projection.observe((_query(EffectKind.ARM, "vehicle-1", 2),), _now()) == ()


def test_vision_status_projects_applied_revision() -> None:
    vision = VisionCommandStatus(
        "vision-1", VisionResultState.APPLIED, False, "applied", None,
        RecordingState.UNKNOWN, None, None, 0, None,
    )
    projection = PlatformEffectStatusProjection(StatusPort(None), StatusPort(vision))
    observations = projection.observe(
        (_query(EffectKind.SET_VISION_TARGET, "vision-1"),), _now(),
    )
    assert len(observations) == 1
    assert observations[0].resource_revision == 3
    assert observations[0].lifecycle.completion is EffectCompletionFeedbackState.COMPLETED

"""One device-independent Action used to exercise the P3 decision lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from contracts.decision import ActionDecision, ActionOutcome, ActionSpec, ExitDecision, ExitReason
from contracts.world.models import WorldSnapshot


@dataclass(frozen=True, slots=True)
class WorldSummaryParameters:
    require_localization: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.require_localization, bool):
            raise TypeError("require_localization must be bool")


WORLD_SUMMARY_SPEC = ActionSpec("world.summary", WorldSummaryParameters)


class _WorldSummaryInstance:
    def tick(self, snapshot: WorldSnapshot) -> ActionDecision:
        if self._parameters.require_localization and snapshot.localization is None:
            return ActionDecision(ActionOutcome.FAILED, error="localization unavailable")
        return ActionDecision(ActionOutcome.SUCCEEDED, result={
            "snapshot_id": str(snapshot.snapshot_id),
            "object_count": len(snapshot.objects),
            "has_vehicle": snapshot.vehicle is not None,
            "has_localization": snapshot.localization is not None,
        })

    def exit(self, snapshot: WorldSnapshot, reason: ExitReason) -> ExitDecision:
        return ExitDecision(True)

    def __init__(self, parameters: WorldSummaryParameters) -> None:
        self._parameters = parameters


class WorldSummaryAction:
    def start(self, parameters: WorldSummaryParameters, snapshot: WorldSnapshot) -> _WorldSummaryInstance:
        return _WorldSummaryInstance(parameters)

"""In-memory Rover state/command ports; no physical device or sender."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from contracts.platform.common import ClockStamp, SchemaVersion
from contracts.platform.vehicle_commands import (
    AckState, BarrierDisposition, CancelRequest, CancellationReceipt,
    CommandStatusSnapshot, CommandSubmissionReceipt, CompletionState,
    QueueState, SubmissionState, TransportState, VehicleCommandEnvelope,
)
from contracts.platform.vehicle_state import VehicleStateSnapshot

from .state import RoverState, project_rover_state


class FakeRoverAdapter:
    def __init__(self, state: RoverState | None = None) -> None:
        self._state = state or RoverState(
            0, ClockStamp(datetime.now(timezone.utc), time.monotonic_ns(), "fake-rover"),
            False, True, False, 0.0, 0.0, 0.0, 0.0,
        )
        self._rejected: dict[str, CommandStatusSnapshot] = {}

    def set_state(self, state: RoverState) -> None:
        if state.sequence <= self._state.sequence:
            raise ValueError("Rover state sequence must advance")
        self._state = state

    def snapshot(self, source=None) -> VehicleStateSnapshot:
        return project_rover_state(self._state)

    def wait_next(self, *, after_session_id: str, after_sequence: int,
                  timeout_s: float, source=None) -> VehicleStateSnapshot | None:
        state = self.snapshot()
        if after_session_id != state.link_session_id or state.sequence > after_sequence:
            return state
        return None

    def submit(self, command: VehicleCommandEnvelope) -> CommandSubmissionReceipt:
        self._rejected[command.command_id] = CommandStatusSnapshot(
            command.command_id, SubmissionState.REJECTED, QueueState.NOT_QUEUED,
            TransportState.NOT_ATTEMPTED, AckState.NOT_EXPECTED,
            CompletionState.NOT_OBSERVED, 0, "fake_rover_no_physical_writer",
        )
        return CommandSubmissionReceipt(command.command_id, SubmissionState.REJECTED,
                                        "fake_rover_no_physical_writer")

    def cancel(self, request: CancelRequest) -> CancellationReceipt:
        found = request.command_id in self._rejected if request.command_id else False
        return CancellationReceipt(
            SchemaVersion(2, 0), request.cancellation_id,
            (), (), () if found or not request.command_id else (request.command_id,),
            None,
            (BarrierDisposition.STOP_UNDELIVERABLE if request.emit_stop_barrier
             else BarrierDisposition.NOT_REQUIRED),
            "sitl", "fake-rover", time.monotonic_ns(),
            "fake_rover_no_physical_writer",
        )

    def status(self, command_id: str) -> CommandStatusSnapshot:
        return self._rejected[command_id]

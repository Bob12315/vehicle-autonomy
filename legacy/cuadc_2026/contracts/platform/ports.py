from __future__ import annotations

from typing import Protocol

from .common import OperationReceipt, SourceId
from .vehicle_state import LinkControlSnapshot, SourceSwitchReceipt, VehicleStateSnapshot
from .vehicle_commands import CancelRequest, CancellationReceipt, CommandStatusSnapshot, CommandSubmissionReceipt, VehicleCommandEnvelope
from .perception import (
    PerceptionPort, VisionCommandEnvelope,
    VisionCommandStatus, VisionSubmissionReceipt,
)


class VehicleStatePort(Protocol):
    def snapshot(self, source: SourceId | None = None) -> VehicleStateSnapshot: ...
    def wait_next(
        self,
        *,
        after_session_id: str,
        after_sequence: int,
        timeout_s: float,
        source: SourceId | None = None,
    ) -> VehicleStateSnapshot | None: ...


class LinkControlPort(Protocol):
    def status(self) -> LinkControlSnapshot: ...
    def activate_source(self, source: SourceId, expected_revision: int) -> SourceSwitchReceipt: ...
    def reconnect(self, source: SourceId | None = None) -> OperationReceipt: ...


class VehicleCommandPort(Protocol):
    def submit(self, command: VehicleCommandEnvelope) -> CommandSubmissionReceipt: ...
    def cancel(self, request: CancelRequest) -> CancellationReceipt: ...
    def status(self, command_id: str) -> CommandStatusSnapshot: ...


class VisionCommandPort(Protocol):
    def submit(self, command: VisionCommandEnvelope) -> VisionSubmissionReceipt: ...
    def status(self, command_id: str) -> VisionCommandStatus: ...

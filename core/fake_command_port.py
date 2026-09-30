"""Offline queue and sole simulated writer for P4 fence tests."""

from __future__ import annotations

from contracts.core.primitives import CommandId, IdempotencyKey
from contracts.core.time import TimePoint
from contracts.vehicle.command import (
    CancelCommandRequest, CommandPhase, CommandReceipt, CommandStatus,
    StopMotionCommand, VehicleCommandEnvelope,
)

from .control_authority import ControlAuthority


class FakeVehicleCommandPort:
    """No transport. `transmit_next` models the physical write checkpoint."""

    def __init__(self, authority: ControlAuthority) -> None:
        self._authority = authority
        self._queue: list[CommandId] = []
        self._commands: dict[CommandId, VehicleCommandEnvelope] = {}
        self._statuses: dict[CommandId, CommandStatus] = {}
        self._keys: dict[IdempotencyKey, CommandId] = {}
        self.rejection_reasons: dict[CommandId, str] = {}
        self.transmitted: list[VehicleCommandEnvelope] = []
        self.simulated_zero_writes: list[str] = []

    def submit(self, command: VehicleCommandEnvelope) -> CommandReceipt:
        with self._authority.lock:
            existing = self._keys.get(command.idempotency_key)
            if existing is not None:
                if self._commands[existing] != command:
                    raise ValueError("idempotency key reused for a different command")
                return CommandReceipt(existing, self._statuses[existing].phase)
            if command.command_id in self._commands:
                raise ValueError("command ID reused")
            reason = self._authority.write_reason(command, command.created_at)
            if reason is not None:
                self.rejection_reasons[command.command_id] = reason
                phase = CommandPhase.REJECTED
            else:
                self._queue.append(command.command_id)
                phase = CommandPhase.ACCEPTED
            self._commands[command.command_id] = command
            self._keys[command.idempotency_key] = command.command_id
            self._statuses[command.command_id] = CommandStatus(command.command_id, phase, command.created_at)
            return CommandReceipt(command.command_id, phase)

    def cancel(self, request: CancelCommandRequest) -> CommandStatus:
        with self._authority.lock:
            status = self._statuses.get(request.command_id)
            if status is None:
                raise KeyError(request.command_id)
            if request.requested_at.elapsed_ns_since(status.observed_at) < 0:
                raise ValueError("cancel time cannot precede the last status")
            if status.phase in (CommandPhase.ACCEPTED, CommandPhase.TRANSMITTED, CommandPhase.ACKNOWLEDGED):
                status = CommandStatus(request.command_id, CommandPhase.CANCELLED, request.requested_at)
                self._statuses[request.command_id] = status
            return status

    def status(self, command_id: CommandId) -> CommandStatus | None:
        with self._authority.lock:
            return self._statuses.get(command_id)

    def transmit_next(self, now: TimePoint) -> CommandStatus | None:
        with self._authority.lock:
            while self._queue:
                command_id = self._queue.pop(0)
                status = self._statuses[command_id]
                if status.phase is not CommandPhase.ACCEPTED:
                    continue
                command = self._commands[command_id]
                reason = self._authority.write_reason(command, now)
                phase = CommandPhase.REJECTED if reason else CommandPhase.TRANSMITTED
                if reason:
                    self.rejection_reasons[command_id] = reason
                else:
                    self.transmitted.append(command)
                    if isinstance(command.command, StopMotionCommand):
                        self.simulated_zero_writes.append(command.command.stream_id)
                status = CommandStatus(command_id, phase, now)
                self._statuses[command_id] = status
                return status
            return None

    def acknowledge(self, command_id: CommandId, now: TimePoint) -> CommandStatus:
        return self._advance(command_id, now, CommandPhase.TRANSMITTED, CommandPhase.ACKNOWLEDGED)

    def observe_completed(self, command_id: CommandId, now: TimePoint) -> CommandStatus:
        return self._advance(command_id, now, CommandPhase.ACKNOWLEDGED, CommandPhase.COMPLETED)

    def _advance(self, command_id: CommandId, now: TimePoint, expected: CommandPhase, phase: CommandPhase) -> CommandStatus:
        with self._authority.lock:
            if self._statuses[command_id].phase is not expected:
                raise ValueError(f"{phase.value} requires {expected.value}")
            if now.elapsed_ns_since(self._statuses[command_id].observed_at) < 0:
                raise ValueError("status time cannot go backwards")
            status = CommandStatus(command_id, phase, now)
            self._statuses[command_id] = status
            return status

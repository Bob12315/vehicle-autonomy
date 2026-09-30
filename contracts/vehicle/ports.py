"""Vehicle facing contracts; concrete adapters are not part of Core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from contracts.core.primitives import CommandId
from .command import (
    CancelCommandRequest, CommandReceipt, CommandStatus, VehicleCommandEnvelope,
)
from .models import VehicleStateSnapshot


@dataclass(frozen=True)
class VehicleCapabilities:
    names: frozenset[str] = frozenset()


class VehicleCommandPort(Protocol):
    def submit(self, command: VehicleCommandEnvelope) -> CommandReceipt:
        """Submit a command approved by a later Execution boundary."""

    def cancel(self, request: CancelCommandRequest) -> CommandStatus:
        """Request cancellation; a reply does not imply physical stop."""

    def status(self, command_id: CommandId) -> CommandStatus | None:
        """Read the known submission phase, if any."""


class VehicleStatePort(Protocol):
    def snapshot(self) -> VehicleStateSnapshot | None:
        """Read the latest vehicle-reported state without control authority."""

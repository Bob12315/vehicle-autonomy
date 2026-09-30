"""Narrow ArduCopter adapter for an unarmed controller-only check."""

from __future__ import annotations

from contracts.vehicle.command import ModeCommand, VehicleCommand
from protocols.mavlink.codec import Instruction

from .ardupilot_commands import ArduPilotCommandTranslator


class CopterStabilizeDiagnosticTranslator(ArduPilotCommandTranslator):
    """Expose only the already active STABILIZE mode; reject arm and motion."""

    def __init__(self) -> None:
        super().__init__(mode_ids={"STABILIZE": 0})

    def translate(self, command: VehicleCommand, *, stop_frame: int | None = None) -> Instruction:
        if not isinstance(command, ModeCommand) or command.native_mode != "STABILIZE":
            raise ValueError("Copter diagnostic supports only STABILIZE mode")
        return super().translate(command)

"""Narrow ArduRover adapter for a non-moving controller-only check."""

from __future__ import annotations

from contracts.vehicle.command import ModeCommand, VehicleCommand
from protocols.mavlink.codec import Instruction
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator


class RoverHoldDiagnosticTranslator(ArduPilotCommandTranslator):
    """Only HOLD mode is exposed; motion, arm and takeoff are rejected."""

    def __init__(self) -> None:
        super().__init__(mode_ids={"HOLD": 4})

    def translate(self, command: VehicleCommand, *, stop_frame: int | None = None) -> Instruction:
        if not isinstance(command, ModeCommand) or command.native_mode != "HOLD":
            raise ValueError("Rover diagnostic supports only HOLD mode")
        return super().translate(command)

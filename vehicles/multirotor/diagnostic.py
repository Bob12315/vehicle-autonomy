"""Narrow ArduCopter adapter for an unarmed controller-only check."""

from __future__ import annotations

from contracts.vehicle.command import ArmCommand, DisarmCommand, ModeCommand, VehicleCommand
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


class CopterBenchArmDiagnosticTranslator(ArduPilotCommandTranslator):
    """Expose arm/disarm and current STABILIZE only for a bare-controller bench."""

    def __init__(self) -> None:
        super().__init__(mode_ids={"STABILIZE": 0})

    def translate(self, command: VehicleCommand, *, stop_frame: int | None = None) -> Instruction:
        if not isinstance(command, (ArmCommand, DisarmCommand)) and not (
            isinstance(command, ModeCommand) and command.native_mode == "STABILIZE"
        ):
            raise ValueError("Copter bench diagnostic supports only arm, disarm and STABILIZE")
        return super().translate(command)


class CopterBenchModeDiagnosticTranslator(ArduPilotCommandTranslator):
    """Only a disarmed STABILIZE/ACRO round trip; no arm or motion."""

    def __init__(self) -> None:
        super().__init__(mode_ids={"STABILIZE": 0, "ACRO": 1})

    def translate(self, command: VehicleCommand, *, stop_frame: int | None = None) -> Instruction:
        if not isinstance(command, ModeCommand) or command.native_mode not in ("STABILIZE", "ACRO"):
            raise ValueError("Copter mode bench supports only STABILIZE and ACRO")
        return super().translate(command)

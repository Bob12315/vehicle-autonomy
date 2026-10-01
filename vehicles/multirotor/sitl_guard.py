"""Final write guard and command translator for loopback, disarmed SITL."""

from __future__ import annotations

from contracts.core.quality import QualityState
from contracts.vehicle.command import ModeCommand, VehicleCommandEnvelope
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator


class SitlModeTranslator(ArduPilotCommandTranslator):
    def translate(self, command, *, stop_frame=None):
        if not isinstance(command, ModeCommand):
            raise ValueError("SITL profile permits only a mode command")
        return super().translate(command, stop_frame=stop_frame)


def disarmed_mode_write_guard(command: VehicleCommandEnvelope, state, allowed_mode: str) -> str | None:
    if not isinstance(command.command, ModeCommand) or command.command.native_mode != allowed_mode:
        return "sitl_mode_only"
    if state is None or state.health.quality is not QualityState.VALID:
        return "fresh_vehicle_state_required"
    if state.operation.armed:
        return "vehicle_armed"
    return None

"""Final write guard and command translator for loopback, disarmed SITL."""

from __future__ import annotations

from contracts.core.quality import QualityState
from contracts.vehicle.command import ArmCommand, DisarmCommand, ModeCommand, VehicleCommandEnvelope
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator


class SitlModeTranslator(ArduPilotCommandTranslator):
    def translate(self, command, *, stop_frame=None):
        if not isinstance(command, ModeCommand):
            raise ValueError("SITL profile permits only a mode command")
        return super().translate(command, stop_frame=stop_frame)


class SitlArmTranslator(ArduPilotCommandTranslator):
    def translate(self, command, *, stop_frame=None):
        if not isinstance(command, (ModeCommand, ArmCommand, DisarmCommand)):
            raise ValueError("SITL arm profile permits only mode, arm and disarm")
        return super().translate(command, stop_frame=stop_frame)


def disarmed_mode_write_guard(command: VehicleCommandEnvelope, state, allowed_mode: str) -> str | None:
    if not isinstance(command.command, ModeCommand) or command.command.native_mode != allowed_mode:
        return "sitl_mode_only"
    if state is None or state.health.quality is not QualityState.VALID:
        return "fresh_vehicle_state_required"
    if state.operation.armed:
        return "vehicle_armed"
    return None


def sitl_arm_write_guard(command: VehicleCommandEnvelope, state, allowed_mode: str,
                         allowed_mode_id: int) -> str | None:
    if isinstance(command.command, ModeCommand):
        return disarmed_mode_write_guard(command, state, allowed_mode)
    if not isinstance(command.command, (ArmCommand, DisarmCommand)):
        return "sitl_arm_profile_command_denied"
    if state is None or state.health.quality is not QualityState.VALID:
        return "fresh_vehicle_state_required"
    if isinstance(command.command, ArmCommand):
        if state.operation.armed:
            return "already_armed"
        if state.operation.native_mode != f"ARDUPILOT_CUSTOM_{allowed_mode_id}":
            return "target_mode_required"
    elif not state.operation.armed:
        return "already_disarmed"
    return None

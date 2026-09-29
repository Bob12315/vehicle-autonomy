from __future__ import annotations

import time

from contracts.platform.vehicle_commands import StopMotion, VehicleCommandEnvelope
from protocols.mavlink.commands import ack_command_id
from vehicles.multirotor.adapter.mavlink import translate_multirotor_mavlink_command
from .command_sender import CommandSender
from .models import ActionCommand, ControlCommand, GimbalRateCommand
from .ack_router import AckRouter, AckSlot


class MavlinkEnvelopeWriter:
    """Typed, exactly-one writer that reuses the characterized MAVLink encoders."""

    def __init__(self, encoder: CommandSender, *, ack_router: AckRouter | None = None,
                 link_session_id=lambda: "", target_system=lambda: 0,
                 target_component=lambda: 0, local_system=lambda: 0,
                 local_component=lambda: 0, source=lambda: "") -> None:
        if not encoder.propagate_errors:
            raise ValueError("typed writer requires propagate_errors=True")
        self.encoder = encoder
        self.ack_router = ack_router
        self.link_session_id = link_session_id
        self.target_system = target_system
        self.target_component = target_component
        self.local_system = local_system
        self.local_component = local_component
        self.source = source

    def write(self, value: object) -> None:
        payload = getattr(value, "payload", None)
        if isinstance(value, VehicleCommandEnvelope):
            payload = value.payload
            self._register_ack(value)
        elif isinstance(payload, StopMotion) and hasattr(value, "safety_generation"):
            if time.monotonic_ns() >= int(getattr(value, "deadline_monotonic_ns", 0)):
                raise RuntimeError("safety_barrier_deadline_expired")
            if str(getattr(value, "link_session_id", "")) != str(self.link_session_id()):
                raise RuntimeError("safety_barrier_session_mismatch")
            if str(getattr(value, "source", "")) != str(self.source()):
                raise RuntimeError("safety_barrier_source_mismatch")
        translated = translate_multirotor_mavlink_command(payload)
        if isinstance(translated, ActionCommand):
            self.encoder._send_action(translated)
        elif isinstance(translated, ControlCommand):
            self.encoder._send_control(translated)
        elif isinstance(translated, GimbalRateCommand):
            self.encoder._send_gimbal_rate(translated)

    def mark_transmitted(self, command: VehicleCommandEnvelope) -> None:
        if self.ack_router is not None:
            self.ack_router.mark_transmitted(command.command_id)

    def mark_write_failed(self, command: VehicleCommandEnvelope) -> None:
        if self.ack_router is not None:
            self.ack_router.abort(command.command_id)

    def _register_ack(self, command: VehicleCommandEnvelope) -> None:
        if self.ack_router is None:
            return
        mav_command = ack_command_id(command.payload.kind)
        if mav_command is None:
            return
        self.ack_router.register(AckSlot(
            command.command_id, command.expected_link_session_id, mav_command,
            self.target_system(), self.target_component(),
            discard=command.ack_policy.value == "DISABLED",
            ack_deadline_monotonic_ns=time.monotonic_ns() + command.ack_timeout_ms * 1_000_000,
            total_deadline_monotonic_ns=command.deadline_monotonic_ns,
            local_system=self.local_system(), local_component=self.local_component(),
        ))

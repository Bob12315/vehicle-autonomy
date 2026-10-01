"""Single fenced ArduPilot writer over an injected byte transport."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from contracts.core.primitives import CommandId, IdempotencyKey, LinkSessionId
from contracts.core.quality import QualityState
from contracts.core.time import TimePoint
from contracts.vehicle.command import (
    ArmCommand, CancelCommandRequest, CommandPhase, CommandReceipt, CommandStatus,
    DisarmCommand, ModeCommand, PoseTargetCommand, StopMotionCommand,
    TwistTargetCommand, VehicleCommandEnvelope,
)
from contracts.vehicle.models import VehicleStateSnapshot
from core.control_authority import ControlAuthority
from infrastructure.transports.bytes import ByteTransport
from protocols.mavlink.codec import CommandLong, LocalSetpoint, MavlinkCodec
from protocols.mavlink import constants as mavlink

from .ardupilot_commands import ArduPilotCommandTranslator


class ArduPilotCommandPort:
    """The only P5 transport writer. An external scheduler calls `write_next`."""

    def __init__(self, *, authority: ControlAuthority, transport: ByteTransport,
                 codec: MavlinkCodec, translator: ArduPilotCommandTranslator,
                 now: Callable[[], TimePoint], stop_speed_tolerance: float = 0.05,
                 write_guard: Callable[[VehicleCommandEnvelope], str | None] | None = None) -> None:
        if not isinstance(authority, ControlAuthority) or not isinstance(codec, MavlinkCodec) or not isinstance(translator, ArduPilotCommandTranslator):
            raise TypeError("authority, codec and translator are required")
        if not callable(now) or not 0 <= stop_speed_tolerance < 1:
            raise ValueError("clock and stop speed tolerance are required")
        self._authority = authority
        self._transport = transport
        self._codec = codec
        self._translator = translator
        self._now = now
        self._stop_speed_tolerance = stop_speed_tolerance
        self._write_guard = write_guard
        self._commands: dict[CommandId, VehicleCommandEnvelope] = {}
        self._statuses: dict[CommandId, CommandStatus] = {}
        self._keys: dict[IdempotencyKey, CommandId] = {}
        self._queue: list[CommandId] = []
        self._encoded: dict[CommandId, bytes] = {}
        self._ack_id: dict[CommandId, int] = {}
        self._inflight: dict[int, CommandId] = {}
        self._ambiguous: set[int] = set()
        self._streams: dict[str, tuple[int, LinkSessionId, str]] = {}
        self.reasons: dict[CommandId, str] = {}
        self._write_uncertain = False

    def uses(self, *, authority: ControlAuthority, transport: ByteTransport, codec: MavlinkCodec) -> bool:
        return self._authority is authority and self._transport is transport and self._codec is codec

    def submit(self, command: VehicleCommandEnvelope) -> CommandReceipt:
        with self._authority.lock:
            existing = self._keys.get(command.idempotency_key)
            if existing is not None:
                if self._commands[existing] != command:
                    raise ValueError("idempotency key conflict")
                return CommandReceipt(existing, self._statuses[existing].phase)
            if command.command_id in self._commands:
                raise ValueError("command ID reused")
            now = self._now()
            reason = self._authority.write_reason(command, now)
            instruction = None
            if reason is None:
                try:
                    stop_frame = None
                    if isinstance(command.command, StopMotionCommand):
                        current = self._streams.get(command.command.stream_id)
                        if current is None or current[1] != command.expected_link_session_id or current[2] != command.lease_id:
                            raise ValueError("stop stream has no current session/lease")
                        stop_frame = current[0]
                    instruction = self._translator.translate(command.command, stop_frame=stop_frame)
                    if isinstance(instruction, LocalSetpoint):
                        instruction = replace(instruction, time_boot_ms=(now.monotonic_ns // 1_000_000) & 0xFFFFFFFF)
                    data = self._codec.encode(instruction)
                except (TypeError, ValueError) as exc:
                    reason = str(exc)
            self._commands[command.command_id] = command
            self._keys[command.idempotency_key] = command.command_id
            phase = CommandPhase.REJECTED if reason else CommandPhase.ACCEPTED
            self._statuses[command.command_id] = CommandStatus(command.command_id, phase, now)
            if reason:
                self.reasons[command.command_id] = reason
            else:
                self._encoded[command.command_id] = data
                self._queue.append(command.command_id)
                if isinstance(instruction, CommandLong):
                    self._ack_id[command.command_id] = instruction.command
                if isinstance(command.command, (PoseTargetCommand, TwistTargetCommand)):
                    self._streams[command.command.stream_id] = (
                        instruction.frame, command.expected_link_session_id, command.lease_id,
                    )
            return CommandReceipt(command.command_id, phase)

    def cancel(self, request: CancelCommandRequest) -> CommandStatus:
        with self._authority.lock:
            status = self._statuses.get(request.command_id)
            if status is None:
                raise KeyError(request.command_id)
            if request.requested_at.elapsed_ns_since(status.observed_at) < 0:
                raise ValueError("cancel time regressed")
            if status.phase in (CommandPhase.ACCEPTED, CommandPhase.TRANSMITTED, CommandPhase.ACKNOWLEDGED):
                status = CommandStatus(request.command_id, CommandPhase.CANCELLED, request.requested_at)
                self._statuses[request.command_id] = status
            return status

    def status(self, command_id: CommandId) -> CommandStatus | None:
        with self._authority.lock:
            return self._statuses.get(command_id)

    def write_next(self, now: TimePoint) -> CommandStatus | None:
        with self._authority.lock:
            if self._write_uncertain:
                return None
            for command_id in tuple(self._queue):
                if self._statuses[command_id].phase is not CommandPhase.ACCEPTED:
                    self._queue.remove(command_id)
                    continue
                ack_id = self._ack_id.get(command_id)
                if ack_id is not None and (ack_id in self._inflight or ack_id in self._ambiguous):
                    continue
                self._queue.remove(command_id)
                command = self._commands[command_id]
                reason = self._authority.write_reason(command, now)
                if reason is None and self._write_guard is not None:
                    reason = self._write_guard(command)
                if reason is not None:
                    self.reasons[command_id] = reason
                    phase = CommandPhase.REJECTED
                else:
                    try:
                        # Fence and transport write stay under the same authority lock.
                        self._transport.write(self._encoded[command_id])
                    except (OSError, ConnectionError) as exc:
                        self._write_uncertain = True
                        self.reasons[command_id] = f"transport_write_uncertain:{type(exc).__name__}"
                        phase = CommandPhase.UNKNOWN
                    else:
                        phase = CommandPhase.TRANSMITTED
                        if ack_id is not None:
                            self._inflight[ack_id] = command_id
                status = CommandStatus(command_id, phase, now)
                self._statuses[command_id] = status
                return status
            return None

    def handle_ack(self, message: object, now: TimePoint) -> CommandStatus | None:
        if message.get_type() != "COMMAND_ACK":
            return None
        if (message.get_srcSystem(), message.get_srcComponent()) != (self._codec.target_system, self._codec.target_component):
            return None
        command_number = int(message.command)
        with self._authority.lock:
            command_id = self._inflight.get(command_number)
            if command_id is None:
                return None
            command = self._commands[command_id]
            if command.expected_link_session_id != self._authority.link_session_id:
                return None
            current = self._statuses[command_id]
            if current.phase is not CommandPhase.TRANSMITTED:
                del self._inflight[command_number]
                return None
            result = int(message.result)
            if result == mavlink.RESULT_IN_PROGRESS:
                return current
            del self._inflight[command_number]
            if result == mavlink.RESULT_ACCEPTED:
                phase = CommandPhase.ACKNOWLEDGED
            else:
                phase = CommandPhase.REJECTED
                self.reasons[command_id] = f"mav_result_{result}"
            status = CommandStatus(command_id, phase, now)
            self._statuses[command_id] = status
            return status

    def expire_unknown(self, now: TimePoint) -> tuple[CommandStatus, ...]:
        """A lost ACK leaves the outcome unknown; never match a later stale ACK."""
        results = []
        with self._authority.lock:
            for command_number, command_id in tuple(self._inflight.items()):
                command = self._commands[command_id]
                if command.deadline.clock_domain_id == now.clock_domain_id and command.deadline <= now:
                    del self._inflight[command_number]
                    self._ambiguous.add(command_number)
                    if self._statuses[command_id].phase is CommandPhase.TRANSMITTED:
                        self.reasons[command_id] = "ack_timeout_outcome_unknown"
                        status = CommandStatus(command_id, CommandPhase.UNKNOWN, now)
                        self._statuses[command_id] = status
                        results.append(status)
            for command_id, status in tuple(self._statuses.items()):
                command = self._commands[command_id]
                if (status.phase is CommandPhase.ACKNOWLEDGED
                        and isinstance(command.command, (ArmCommand, DisarmCommand, ModeCommand))
                        and command.deadline.clock_domain_id == now.clock_domain_id
                        and command.deadline <= now):
                    self.reasons[command_id] = "state_confirmation_timeout_outcome_unknown"
                    final = CommandStatus(command_id, CommandPhase.UNKNOWN, now)
                    self._statuses[command_id] = final
                    results.append(final)
        return tuple(results)

    def observe_heartbeat(self, message: object, received_at: TimePoint) -> tuple[CommandStatus, ...]:
        """A later heartbeat, rather than an ACK, confirms arm/mode state."""
        if message.get_type() != "HEARTBEAT" or (
            message.get_srcSystem(), message.get_srcComponent()
        ) != (self._codec.target_system, self._codec.target_component):
            return ()
        completed = []
        with self._authority.lock:
            for command_id, status in tuple(self._statuses.items()):
                if status.phase is not CommandPhase.ACKNOWLEDGED:
                    continue
                if self._commands[command_id].expected_link_session_id != self._authority.link_session_id:
                    continue
                try:
                    if received_at.elapsed_ns_since(status.observed_at) <= 0:
                        continue
                except ValueError:
                    continue
                command = self._commands[command_id].command
                observed = (
                    isinstance(command, ArmCommand) and bool(message.base_mode & 128)
                    or isinstance(command, DisarmCommand) and not bool(message.base_mode & 128)
                    or isinstance(command, ModeCommand) and message.custom_mode == self._translator.mode_id(command.native_mode)
                )
                if observed:
                    final = CommandStatus(command_id, CommandPhase.COMPLETED, received_at)
                    self._statuses[command_id] = final
                    completed.append(final)
        return tuple(completed)

    def observe_state(self, state: VehicleStateSnapshot) -> tuple[CommandStatus, ...]:
        """Only a fresh post-write zero-motion sample confirms a stop."""
        completed = []
        with self._authority.lock:
            if state.health.quality is not QualityState.VALID:
                return ()
            for command_id, status in tuple(self._statuses.items()):
                command = self._commands[command_id].command
                if status.phase is not CommandPhase.TRANSMITTED or not isinstance(command, StopMotionCommand):
                    continue
                if self._commands[command_id].expected_link_session_id != self._authority.link_session_id:
                    continue
                if state.published_at.clock_domain_id != status.observed_at.clock_domain_id or state.published_at < status.observed_at:
                    continue
                observed = False
                if state.reported_twist is not None:
                    sample = state.reported_twist
                    if sample.captured_at.clock_domain_id == status.observed_at.clock_domain_id and sample.captured_at >= status.observed_at:
                        linear = sample.value.linear
                        angular = sample.value.angular
                        observed = max(abs(linear.x), abs(linear.y), abs(linear.z), abs(angular.x), abs(angular.y), abs(angular.z)) <= self._stop_speed_tolerance
                if observed:
                    final = CommandStatus(command_id, CommandPhase.COMPLETED, state.published_at)
                    self._statuses[command_id] = final
                    completed.append(final)
                    self._streams.pop(command.stream_id, None)
        return tuple(completed)

    def reset_session(self, now: TimePoint) -> None:
        with self._authority.lock:
            for command_id, status in tuple(self._statuses.items()):
                if status.phase is CommandPhase.ACCEPTED:
                    self._statuses[command_id] = CommandStatus(command_id, CommandPhase.REJECTED, now)
                    self.reasons[command_id] = "link_session_lost"
                elif status.phase in (CommandPhase.TRANSMITTED, CommandPhase.ACKNOWLEDGED):
                    self._statuses[command_id] = CommandStatus(command_id, CommandPhase.UNKNOWN, now)
                    self.reasons[command_id] = "link_session_lost_outcome_unknown"
            self._queue.clear()
            self._inflight.clear()
            self._ambiguous.clear()
            self._streams.clear()
            self._write_uncertain = False

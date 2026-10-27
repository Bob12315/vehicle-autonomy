"""Single fenced ArduPilot writer over an injected byte transport."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import time
import math

from vehicle_autonomy.contracts.core.primitives import CommandId, IdempotencyKey, LinkSessionId
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.vehicle.command import (
    ArmCommand, FixedWingTargetCommand, CancelCommandRequest, CommandPhase, CommandReceipt, CommandStatus,
    DisarmCommand, ModeCommand, PoseTargetCommand, StopMotionCommand,
    TwistTargetCommand, VehicleCommandEnvelope,
)
from vehicle_autonomy.contracts.vehicle.models import VehicleStateSnapshot
from vehicle_autonomy.engine.control.control_authority import ControlAuthority
from vehicle_autonomy.vehicles.ardupilot.transports.bytes import ByteTransport
from vehicle_autonomy.vehicles.ardupilot.mavlink.codec import CommandLong, CommandInt, Instruction, LocalSetpoint, MavlinkCodec, TimesyncQuery
from vehicle_autonomy.vehicles.ardupilot.mavlink import constants as mavlink

from vehicle_autonomy.vehicles.ardupilot.commands import ArduPilotCommandTranslator


@dataclass(frozen=True, slots=True)
class WriteGuardApproval:
    """Bound the lifetime of the immutable facts examined by a guard."""
    valid_until: TimePoint

    def __post_init__(self):
        if not isinstance(self.valid_until, TimePoint):
            raise TypeError("guard approval requires a qualified expiry TimePoint")


class ArduPilotCommandPort:
    """The only P5 transport writer. An external scheduler calls `write_next`."""

    def __init__(self, *, authority: ControlAuthority, transport: ByteTransport,
                 codec: MavlinkCodec, translator: ArduPilotCommandTranslator,
                 now: Callable[[], TimePoint], stop_speed_tolerance: float = 0.05,
                 write_guard: Callable[[VehicleCommandEnvelope], str | WriteGuardApproval | None] | None = None,
                 max_guard_duration_ns: int = 50_000_000) -> None:
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
        if isinstance(max_guard_duration_ns, bool) or not isinstance(max_guard_duration_ns, int) or max_guard_duration_ns <= 0:
            raise ValueError("positive synchronous guard budget required")
        self._write_guard = write_guard
        self._max_guard_duration_ns = max_guard_duration_ns
        self._commands: dict[CommandId, VehicleCommandEnvelope] = {}
        self._statuses: dict[CommandId, CommandStatus] = {}
        self._keys: dict[IdempotencyKey, CommandId] = {}
        self._queue: list[CommandId] = []
        self._instructions: dict[CommandId, Instruction] = {}
        self._ack_id: dict[CommandId, int] = {}
        self._inflight: dict[int, CommandId] = {}
        self._state_pending: dict[int, CommandId] = {}
        self._ambiguous: set[int] = set()
        self._streams: dict[str, tuple[int, LinkSessionId, str]] = {}
        self.reasons: dict[CommandId, str] = {}
        self._write_uncertain = False
        self._wire_attempted_bytes=0
        self._receive_ticket = -1
        self._sent_ticket: dict[CommandId, int] = {}
        self._sent_signature: dict[CommandId, int] = {}
        self._transmitted_at: dict[CommandId, TimePoint] = {}
        self._state_matches: dict[CommandId, int] = {}
        self._native_target_evidence = {}
        self._native_guided_signature = {}
        self._last_match_signature: dict[CommandId, int] = {}
        self.ack_evidence: dict[CommandId, dict] = {}

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
                except (TypeError, ValueError) as exc:
                    reason = str(exc)
            self._commands[command.command_id] = command
            self._keys[command.idempotency_key] = command.command_id
            phase = CommandPhase.REJECTED if reason else CommandPhase.ACCEPTED
            self._statuses[command.command_id] = CommandStatus(command.command_id, phase, now)
            if reason:
                self.reasons[command.command_id] = reason
            else:
                self._instructions[command.command_id] = instruction
                self._queue.append(command.command_id)
                if isinstance(instruction, (CommandLong, CommandInt)):
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

    @property
    def protocol_query_slot_available(self):
        # Optional read-only queries must not compete with queued control or
        # its ACK. After ACK they resume: fresh source bounds are still
        # needed while waiting for independently authenticated vehicle state.
        with self._authority.lock:
            pending=set(self._inflight.values())|set(self._state_pending.values())|{i for i in self._queue if self._ack_id.get(i) is not None}
            return not any(self._statuses[i].phase in (CommandPhase.ACCEPTED,CommandPhase.TRANSMITTED) for i in pending)

    def write_timesync(self,nonce):
        """Whitelisted read-only protocol query through this SAME sole writer.

        Only the optional authenticated simulation Session uses this method.
        It cannot encode an actuator, mode, parameter or arbitrary raw frame.
        """
        with self._authority.lock:
            if self._write_uncertain:raise ConnectionError('writer transport outcome uncertain')
            if self._authority.link_session_id is None or self._codec.receive_signing is None:raise ConnectionError('authenticated protocol session required')
            started=self._now();data=self._codec.encode(TimesyncQuery(nonce),advance_sequence=False)
            at=self._now()
            if not 0<=at.elapsed_ns_since(started)<=self._max_guard_duration_ns:raise TimeoutError('clock query preparation exceeded writer budget')
            self._codec.commit_sequence()
            self._wire_attempted_bytes+=len(data)
            try:self._transport.write(data)
            except (OSError,ConnectionError):self._write_uncertain=True;raise
            return at,self._wire_attempted_bytes

    @property
    def wire_attempted_bytes(self):
        with self._authority.lock:return self._wire_attempted_bytes

    def write_next(self, now: TimePoint | None = None) -> CommandStatus | None:
        """The caller's time is a scheduling hint, never the write fence.

        Synchronous guards execute under the authority lock. An over-budget or
        non-returning guard cannot send; no orphan background guard is spawned.
        Transport.write must have its own bounded timeout (TCP/serial do).
        A partial/late/failed transport call is UNKNOWN, never execution proof.
        """
        with self._authority.lock:
            if self._write_uncertain:
                return None
            for command_id in tuple(self._queue):
                if self._statuses[command_id].phase is not CommandPhase.ACCEPTED:
                    self._queue.remove(command_id)
                    continue
                checked_at = self._now()  # after acquiring the lock
                command = self._commands[command_id]
                ack_id = self._ack_id.get(command_id)
                reason = self._authority.write_reason(command, checked_at)
                state_pending = self._state_pending.get(ack_id)
                waiting_state = state_pending is not None and self._statuses[state_pending].phase is CommandPhase.ACKNOWLEDGED
                if reason is None and ack_id is not None and (ack_id in self._inflight or ack_id in self._ambiguous or waiting_state):
                    continue
                self._queue.remove(command_id)
                approval = None
                if reason is None and self._write_guard is not None:
                    wall_start = time.monotonic_ns()
                    try:
                        decision = self._write_guard(command)
                        if isinstance(decision, WriteGuardApproval):
                            approval = decision
                        elif decision is not None:
                            reason = decision if isinstance(decision, str) and decision else "invalid_write_guard_result"
                    except Exception as exc:
                        reason = f"write_guard_exception:{type(exc).__name__}"
                    if time.monotonic_ns() - wall_start > self._max_guard_duration_ns:
                        reason = "write_guard_timeout"
                if reason is None:
                    instruction = self._instructions[command_id]
                    if isinstance(instruction, LocalSetpoint):
                        instruction = replace(instruction, time_boot_ms=(self._now().monotonic_ns // 1_000_000) & 0xFFFFFFFF)
                    try:
                        # Prepare, without consuming a packet sequence. A rejected
                        # or cancelled queue entry never allocates a wire number.
                        data = self._codec.encode(instruction, advance_sequence=False)
                    except Exception as exc:
                        reason = f"encode_failed:{type(exc).__name__}"
                final_at = self._now()  # after guard AND encoding, immediately before write
                if reason is None:
                    try:
                        elapsed = final_at.elapsed_ns_since(checked_at)
                        if elapsed < 0:
                            reason = "write_clock_regressed"
                        elif self._write_guard is not None and elapsed > self._max_guard_duration_ns:
                            reason = "write_guard_timeout"
                        elif approval is not None and final_at.elapsed_ns_since(approval.valid_until) > 0:
                            reason = "write_guard_evidence_expired"
                    except ValueError:
                        reason = "write_clock_domain_changed"
                if reason is None:
                    reason = self._authority.write_reason(command, final_at)
                observed_at = final_at
                if reason is not None:
                    self.reasons[command_id] = reason
                    phase = CommandPhase.REJECTED
                else:
                    try:
                        # No user callback between final fence and physical call;
                        # the entire operation remains under the authority lock.
                        self._codec.commit_sequence()
                        if self._codec.receive_signing is not None:
                            self._sent_signature[command_id] = self._codec.receive_signing.watermark
                        self._wire_attempted_bytes+=len(data)
                        self._transport.write(data)
                    except (OSError, ConnectionError) as exc:
                        self._write_uncertain = True
                        self.reasons[command_id] = f"transport_write_uncertain:{type(exc).__name__}"
                        phase = CommandPhase.UNKNOWN
                    else:
                        observed_at = self._now()
                        reason = self._authority.write_reason(command, observed_at)
                        if reason is not None:
                            self._write_uncertain = True
                            self.reasons[command_id] = "transport_returned_after_fence:" + reason
                            phase = CommandPhase.UNKNOWN
                        else:
                            phase = CommandPhase.TRANSMITTED
                            self._sent_ticket[command_id] = self._receive_ticket
                            self._transmitted_at[command_id] = observed_at
                            if ack_id is not None:
                                self._inflight[ack_id] = command_id
                status = CommandStatus(command_id, phase, observed_at)
                self._statuses[command_id] = status
                return status
            return None

    def observe_receive_ticket(self, ticket: int) -> None:
        with self._authority.lock:
            self._receive_ticket = ticket

    def handle_ack(self, message: object, now: TimePoint, *, ticket: int | None = None) -> CommandStatus | None:
        if message.get_type() != "COMMAND_ACK":
            return None
        if (message.get_srcSystem(), message.get_srcComponent()) != (self._codec.target_system, self._codec.target_component):
            return None
        # MAVLink2 ACK target extensions identify the requester; zero means
        # broadcast/old dialect. Another controller's ACK cannot complete ours.
        if (int(getattr(message, "target_system", 0)) not in (0, self._codec.source_system)
                or int(getattr(message, "target_component", 0)) not in (0, self._codec.source_component)):
            return None
        command_number = int(message.command)
        with self._authority.lock:
            command_id = self._inflight.get(command_number)
            if command_id is None:
                return None
            command = self._commands[command_id]
            if command.expected_link_session_id != self._authority.link_session_id:
                return None
            current_time = self._now()
            try:
                expired = current_time.elapsed_ns_since(command.deadline) >= 0
            except ValueError:
                expired = True
            if expired:
                self.expire_unknown(current_time)
                return None
            current = self._statuses[command_id]
            signature = getattr(message, '_vaf_signature_timestamp', None)
            if (signature is None or signature <= self._sent_signature.get(command_id, 2**48)):
                return None
            # ACK has no request UUID, particularly shared ARM/DISARM command 400.
            # Record a candidate, never infer goal completion from ACK ordering.
            self.ack_evidence[command_id] = {"packet_ticket": ticket,
                "correlation": "unproven_mav_cmd_only", "signature_timestamp": signature,
                "command": command_number, "result": int(message.result)}
            if current.phase is not CommandPhase.TRANSMITTED:
                del self._inflight[command_number]
                return None
            result = int(message.result)
            if result == mavlink.RESULT_IN_PROGRESS:
                return current
            del self._inflight[command_number]
            if result == mavlink.RESULT_ACCEPTED:
                phase = CommandPhase.ACKNOWLEDGED
                if isinstance(command.command, (ArmCommand, DisarmCommand, ModeCommand, FixedWingTargetCommand)):
                    self._state_pending[command_number] = command_id
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
                        and isinstance(command.command, (ArmCommand, DisarmCommand, ModeCommand, FixedWingTargetCommand))
                        and command.deadline.clock_domain_id == now.clock_domain_id
                        and command.deadline <= now):
                    self.reasons[command_id] = "state_confirmation_timeout_outcome_unknown"
                    self._ambiguous.add(self._ack_id[command_id])
                    final = CommandStatus(command_id, CommandPhase.UNKNOWN, now)
                    self._statuses[command_id] = final
                    results.append(final)
        return tuple(results)

    def observe_heartbeat(self, message: object, received_at: TimePoint, *,
                          ticket: int | None = None, before_capture: TimePoint | None = None,
                          after_capture: TimePoint | None = None, before_boot: int | None = None,
                          after_boot: int | None = None) -> tuple[CommandStatus, ...]:
        """Require independently authenticated ACK and newer authenticated state.

        Packet sequence, neighboring source clocks and receive time are NOT
        evidence of heartbeat generation. Counts only retain the existing
        debounce; they never qualify an unauthenticated observation.
        """
        if message.get_type() != "HEARTBEAT" or (
            message.get_srcSystem(), message.get_srcComponent()
        ) != (self._codec.target_system, self._codec.target_component):
            return ()
        completed = []
        with self._authority.lock:
            for command_id, status in tuple(self._statuses.items()):
                if status.phase is not CommandPhase.ACKNOWLEDGED:
                    continue
                envelope = self._commands[command_id]
                if envelope.expected_link_session_id != self._authority.link_session_id:
                    continue
                current_time = self._now()
                try:
                    expired = current_time.elapsed_ns_since(envelope.deadline) >= 0
                except ValueError:
                    expired = True
                if expired:
                    self.expire_unknown(current_time)
                    continue
                command = envelope.command
                if not isinstance(command, (ArmCommand, DisarmCommand, ModeCommand, FixedWingTargetCommand)):
                    continue
                signature = getattr(message, '_vaf_signature_timestamp', None)
                ack_signature = self.ack_evidence.get(command_id, {}).get('signature_timestamp')
                if (signature is None or ack_signature is None or signature <= ack_signature
                        or signature <= self._sent_signature.get(command_id, 2**48)):
                    continue
                if isinstance(command, FixedWingTargetCommand):
                    if message.custom_mode == self._translator.mode_id('GUIDED') and message.base_mode & 128:
                        self._native_guided_signature[command_id] = signature
                        final = self._complete_native_target(command_id, received_at)
                        if final is not None:
                            completed.append(final)
                    else:
                        self._native_guided_signature.pop(command_id, None)
                        self._native_target_evidence.pop(command_id, None)
                    continue
                observed = (
                    isinstance(command, ArmCommand) and bool(message.base_mode & 128)
                    or isinstance(command, DisarmCommand) and not bool(message.base_mode & 128)
                    or isinstance(command, ModeCommand) and message.custom_mode == self._translator.mode_id(command.native_mode)
                )
                if signature <= self._last_match_signature.get(command_id, -1):
                    continue
                self._last_match_signature[command_id] = signature
                self._state_matches[command_id] = self._state_matches.get(command_id, 0) + 1 if observed else 0
                if self._state_matches[command_id] >= 2:
                    final = CommandStatus(command_id, CommandPhase.COMPLETED, received_at)
                    self._statuses[command_id] = final
                    completed.append(final)
        return tuple(completed)

    def _complete_native_target(self, command_id, at):
        if command_id not in self._native_target_evidence or command_id not in self._native_guided_signature:
            return None
        if self._native_guided_signature[command_id] <= self._native_target_evidence[command_id]["signature_timestamp"]:
            return None  # require mode evidence AFTER the current target echo
        final = CommandStatus(command_id, CommandPhase.COMPLETED, at)
        self._statuses[command_id] = final
        self.ack_evidence[command_id]['native_target'] = dict(self._native_target_evidence[command_id])
        return final

    def observe_native_target(self, message, at):
        """Only authenticated, post-ACK target echo + GUIDED HB configures a goal.

        This confirms lat/lon/AMSL target adoption, not arrival or stopping.
        """
        if message.get_type() != 'POSITION_TARGET_GLOBAL_INT' or (
                message.get_srcSystem(), message.get_srcComponent()) != (self._codec.target_system, self._codec.target_component):
            return ()
        signature = getattr(message, '_vaf_signature_timestamp', None)
        if signature is None:
            return ()
        valid = int(message.coordinate_frame) == 0 and not int(message.type_mask) & 7 and math.isfinite(float(message.alt))
        completed = []
        with self._authority.lock:
            self.expire_unknown(self._now())
            for command_id,status in tuple(self._statuses.items()):
                envelope = self._commands[command_id]
                command = envelope.command
                if not isinstance(command, FixedWingTargetCommand) or status.phase is not CommandPhase.ACKNOWLEDGED:
                    continue
                if envelope.expected_link_session_id != self._authority.link_session_id:
                    continue
                ack = self.ack_evidence.get(command_id,{}).get('signature_timestamp')
                if ack is None or signature <= ack or signature <= self._sent_signature.get(command_id,2**48):
                    continue
                # A newer authenticated contradiction supersedes an older
                # matching echo. Never combine stale goal A with later mode
                # evidence after the source has already reported goal B.
                self._native_target_evidence.pop(command_id, None)
                if not valid:
                    continue
                target = command.center
                if (abs(int(message.lat_int)-round(target.latitude_deg*1e7)) > 1
                        or abs(int(message.lon_int)-round(target.longitude_deg*1e7)) > 1
                        or abs(float(message.alt)-target.altitude_m) > .02):
                    continue
                self._native_target_evidence[command_id] = dict(signature_timestamp=signature,
                    latitude_e7=int(message.lat_int),longitude_e7=int(message.lon_int),altitude_amsl_m=float(message.alt),
                    scope='native_target_configuration_only_not_arrival')
                final = self._complete_native_target(command_id,at)
                if final is not None:
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
            self._state_pending.clear()
            self._ambiguous.clear()
            self._streams.clear()
            self._receive_ticket = -1
            self._native_target_evidence.clear()
            self._native_guided_signature.clear()
            self._state_matches.clear()
            self._last_match_signature.clear()
            self._sent_ticket.clear()
            self._sent_signature.clear()
            self._transmitted_at.clear()
            self._write_uncertain = False

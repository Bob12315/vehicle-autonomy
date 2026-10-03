"""P4 offline Execution boundary for typed vehicle Effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Callable

from contracts.core.primitives import CommandId, IdempotencyKey, SchemaVersion
from contracts.core.time import TimePoint
from contracts.effects.vehicle import (
    ArmEffect, DisarmEffect, EffectEnvelope, LandEffect, ModeEffect,
    PoseTargetEffect, StopMotionEffect, TakeoffEffect, TwistTargetEffect,
)
from contracts.vehicle.command import (
    ArmCommand, CancelCommandRequest, CommandPhase, CommandReceipt,
    DisarmCommand, LandCommand, ModeCommand, PoseTargetCommand,
    StopMotionCommand, TakeoffCommand, TwistTargetCommand,
    VehicleCommandEnvelope,
)
from contracts.vehicle.ports import VehicleCommandPort
from contracts.world.models import WorldSnapshot

from .control_authority import ControlAuthority
from .vehicle_safety import VehicleSafetyPolicy


class StopState(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    TRANSMITTED = "TRANSMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONFIRMED = "CONFIRMED"
    UNCONFIRMED = "UNCONFIRMED"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    receipt: CommandReceipt | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class StopResult:
    stream_id: str
    state: StopState
    command_id: CommandId | None = None
    reason: str | None = None


@dataclass(slots=True)
class _Stream:
    envelope: EffectEnvelope
    last_refresh: TimePoint
    command_id: CommandId
    stop_command_id: CommandId | None = None


class VehicleExecution:
    """The sole Core caller of VehicleCommandPort; no device is constructed here."""

    def __init__(self, commands: VehicleCommandPort, authority: ControlAuthority,
                 safety: VehicleSafetyPolicy, command_ids: Callable[[], CommandId]) -> None:
        if not isinstance(authority, ControlAuthority) or not isinstance(safety, VehicleSafetyPolicy):
            raise TypeError("explicit authority and SafetyPolicy required")
        self._commands = commands
        self._authority = authority
        self._safety = safety
        self._command_ids = command_ids
        self._streams: dict[str, _Stream] = {}
        self._effect_results: dict[str, tuple[EffectEnvelope, DispatchResult]] = {}

    def active_stream_ids(self) -> tuple[str, ...]:
        """Expose active motion streams for bounded runtime shutdown."""
        return tuple(stream_id for stream_id, stream in self._streams.items()
                     if stream.stop_command_id is None
                     or self.stop_status(stream_id).state is not StopState.CONFIRMED)

    def cancel_pending(self, run_id, action_id, now: TimePoint) -> tuple[str, ...]:
        """Cancel queued requests while preserving the lease for an exit Stop.

        Already transmitted one-shot commands cannot be undone; their observed
        results stay visible and are never relabelled as cancelled.
        """
        cancelled=[]
        with self._authority.lock:
            for effect_id,(envelope,result) in self._effect_results.items():
                if envelope.run_id!=run_id or envelope.action_instance_id!=action_id or result.receipt is None:
                    continue
                status=self._commands.status(result.receipt.command_id)
                if status is not None and status.phase is CommandPhase.ACCEPTED:
                    self._commands.cancel(CancelCommandRequest(result.receipt.command_id,now))
                    cancelled.append(str(effect_id))
        return tuple(cancelled)

    def dispatch(self, envelope: EffectEnvelope, world: WorldSnapshot, now: TimePoint) -> DispatchResult:
        if not isinstance(envelope, EffectEnvelope) or not isinstance(world, WorldSnapshot) or not isinstance(now, TimePoint):
            raise TypeError("typed Effect, WorldSnapshot and TimePoint required")
        with self._authority.lock:
            existing = self._effect_results.get(envelope.effect_id)
            if existing is not None:
                if existing[0] != envelope:
                    raise ValueError("effect ID reused for different content")
                return existing[1]
            reason = self._authority.admission_reason(envelope.run_id, envelope.action_instance_id, now)
            if reason is None:
                reason = self._safety.evaluate(envelope, world, now)
            if reason is not None:
                result = DispatchResult(None, reason)
            elif isinstance(envelope.effect, StopMotionEffect):
                stop = self.stop_stream(envelope.effect.stream_id, now, requested_by=envelope)
                result = DispatchResult(
                    None if stop.command_id is None else CommandReceipt(
                        stop.command_id, self._commands.status(stop.command_id).phase,
                    ),
                    stop.reason,
                )
            else:
                if isinstance(envelope.effect, (PoseTargetEffect, TwistTargetEffect)):
                    previous = self._streams.get(envelope.effect.stream_id)
                    if previous is not None:
                        if previous.stop_command_id is not None:
                            stop = self._commands.status(previous.stop_command_id)
                            if stop is None or stop.phase is not CommandPhase.COMPLETED:
                                result = DispatchResult(None, "stream_stop_unconfirmed")
                                self._effect_results[envelope.effect_id] = (envelope, result)
                                return result
                            del self._streams[envelope.effect.stream_id]
                        self._commands.cancel(CancelCommandRequest(previous.command_id, now))
                command = self._make_command(envelope, now)
                receipt = self._commands.submit(command)
                result = DispatchResult(receipt, None if receipt.phase is CommandPhase.ACCEPTED else "port_rejected")
                if receipt.phase is CommandPhase.ACCEPTED and isinstance(envelope.effect, (PoseTargetEffect, TwistTargetEffect)):
                    self._streams[envelope.effect.stream_id] = _Stream(envelope, now, receipt.command_id)
            self._effect_results[envelope.effect_id] = (envelope, result)
            return result

    def _make_command(self, envelope: EffectEnvelope, now: TimePoint) -> VehicleCommandEnvelope:
        effect = envelope.effect
        if isinstance(effect, ArmEffect):
            payload = ArmCommand()
        elif isinstance(effect, DisarmEffect):
            payload = DisarmCommand()
        elif isinstance(effect, TakeoffEffect):
            payload = TakeoffCommand(effect.height_m)
        elif isinstance(effect, LandEffect):
            payload = LandCommand()
        elif isinstance(effect, ModeEffect):
            payload = ModeCommand(effect.native_mode)
        elif isinstance(effect, PoseTargetEffect):
            payload = PoseTargetCommand(effect.frame_id, effect.target_pose, effect.stream_id)
        elif isinstance(effect, TwistTargetEffect):
            payload = TwistTargetCommand(effect.frame_id, effect.target_twist, effect.stream_id)
        elif isinstance(effect, StopMotionEffect):
            payload = StopMotionCommand(effect.stream_id)
        else:
            raise TypeError("unsupported vehicle effect")
        lease = self._authority.lease
        session = self._authority.link_session_id
        if lease is None or session is None:
            raise RuntimeError("authorization disappeared before command construction")
        return VehicleCommandEnvelope(
            SchemaVersion(1, 0), self._command_ids(), envelope.run_id, lease.lease_id,
            self._authority.authorization_generation, self._authority.send_generation,
            session, now, envelope.deadline, 0, IdempotencyKey(envelope.effect_id), payload,
        )

    def stop_stream(self, stream_id: str, now: TimePoint, *, requested_by: EffectEnvelope | None = None) -> StopResult:
        with self._authority.lock:
            stream = self._streams.get(stream_id)
            if stream is None:
                return StopResult(stream_id, StopState.UNCONFIRMED, reason="unknown_stream")
            self._commands.cancel(CancelCommandRequest(stream.command_id, now))
            if stream.stop_command_id is not None:
                return self.stop_status(stream_id)
            reason = self._authority.admission_reason(stream.envelope.run_id, stream.envelope.action_instance_id, now)
            if reason is not None:
                return StopResult(stream_id, StopState.UNCONFIRMED, reason=reason)
            deadline_ns = min(
                now.monotonic_ns + self._safety.limits.max_request_ttl_ns,
                self._authority.lease.expires_at.monotonic_ns,
            )
            if deadline_ns <= now.monotonic_ns:
                return StopResult(stream_id, StopState.UNCONFIRMED, reason="stop_deadline_expired")
            deadline = TimePoint(
                deadline_ns,
                now.utc + timedelta(microseconds=(deadline_ns - now.monotonic_ns) // 1000),
                now.clock_domain_id,
            )
            origin = requested_by or stream.envelope
            stop_effect = EffectEnvelope(
                SchemaVersion(1, 0),
                origin.effect_id if requested_by else f"stop:{stream.command_id}",
                stream.envelope.run_id, stream.envelope.action_instance_id,
                now, deadline, StopMotionEffect(stream_id),
            )
            receipt = self._commands.submit(self._make_command(stop_effect, now))
            stream.stop_command_id = receipt.command_id
            if receipt.phase is not CommandPhase.ACCEPTED:
                return StopResult(stream_id, StopState.UNCONFIRMED, receipt.command_id, "port_rejected")
            return StopResult(stream_id, StopState.ACCEPTED, receipt.command_id)

    def stop_status(self, stream_id: str) -> StopResult:
        stream = self._streams.get(stream_id)
        if stream is None or stream.stop_command_id is None:
            return StopResult(stream_id, StopState.UNCONFIRMED, reason="stop_not_submitted")
        status = self._commands.status(stream.stop_command_id)
        phase_states = {
            CommandPhase.ACCEPTED: StopState.ACCEPTED,
            CommandPhase.TRANSMITTED: StopState.TRANSMITTED,
            CommandPhase.ACKNOWLEDGED: StopState.ACKNOWLEDGED,
            CommandPhase.COMPLETED: StopState.CONFIRMED,
        }
        return StopResult(stream_id, phase_states.get(status.phase, StopState.UNCONFIRMED), status.command_id)

    def tick(self, now: TimePoint) -> tuple[StopResult, ...]:
        """Caller must schedule this watchdog; no background process is implied."""
        results = []
        for stream_id, stream in tuple(self._streams.items()):
            if stream.stop_command_id is not None:
                continue
            try:
                overdue = now.elapsed_ns_since(stream.last_refresh) > self._safety.limits.deadman_ns
            except ValueError:
                overdue = True
            if overdue:
                results.append(self.stop_stream(stream_id, now))
        return tuple(results)

"""Explicit dual-vehicle simulation loop around one Execution and one writer.

The P6 diagnostic remains a narrow compatibility entry. This composition is
shared by both simulation vehicles; the injected translator is the only
vehicle-specific command mapping. It never reads Gazebo truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time
from typing import Callable
from uuid import uuid4

from contracts.core.primitives import RunId, SchemaVersion
from contracts.core.quality import QualityState
from contracts.core.time import TimePoint
from contracts.effects.vehicle import EffectEnvelope, StopMotionEffect, VehicleEffect
from contracts.vehicle.command import CommandStatus, PoseTargetCommand, StopMotionCommand, TakeoffCommand, TwistTargetCommand, VehicleCommandEnvelope
from core.control_authority import ControlAuthority, ControlLease
from core.vehicle_execution import DispatchResult, StopState, VehicleExecution
from infrastructure.transports.bytes import TcpByteTransport
from protocols.mavlink.codec import MavlinkCodec
from localization.online import OnlineLocalization
from runtime.simulation_profile import SimulationProfile
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator
from vehicles.multirotor.mavlink_port import ArduPilotCommandPort
from vehicles.multirotor.mavlink_state import ArduPilotTelemetryState
from vehicles.multirotor.session import ArduPilotSession
from vehicles.rover.mavlink_state import RoverTelemetryState
from world_model import FreshnessLimits, WorldModel

from .simulation_safety import RoverSimulationSafetyPolicy, SimulationSafetyPolicy
from .simulation_clock import SimulationSourceClock


def _later(point: TimePoint, ns: int) -> TimePoint:
    return TimePoint(point.monotonic_ns + ns,
                     point.utc + timedelta(microseconds=ns // 1000), point.clock_domain_id)


@dataclass(frozen=True, slots=True)
class SimulationCycle:
    received_count: int
    written: CommandStatus | None
    session_id: str | None
    vehicle_fresh: bool
    fault: str | None


class SimulationRuntime:
    """Caller-scheduled loop. `connect` and `begin_run` are both explicit."""

    def __init__(self, profile: SimulationProfile, *, translator: ArduPilotCommandTranslator,
                 transport_factory: Callable[..., object] | None = None,
                 clock: Callable[[], TimePoint] | None = None,
                 event_sink: Callable[[dict], None] | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not isinstance(profile, SimulationProfile):
            raise TypeError("validated SimulationProfile required")
        if not isinstance(translator, ArduPilotCommandTranslator):
            raise TypeError("vehicle translator required")
        if translator.vehicle_kind != profile.kind:
            raise ValueError("translator and vehicle profile must match")
        self.profile = profile
        self.clock = clock or (lambda: TimePoint(time.monotonic_ns(), datetime.now(timezone.utc),
                                                 profile.clock_domain_id))
        self._transport_factory = transport_factory or TcpByteTransport.connect
        self._event_sink = event_sink
        self._sleep = sleep
        self.authority = ControlAuthority()
        self._translator = translator
        self._transport = None
        self._session: ArduPilotSession | None = None
        self._port: ArduPilotCommandPort | None = None
        self._execution: VehicleExecution | None = None
        self._world = self._new_world()
        self.localization = OnlineLocalization(self.profile.safety.max_snapshot_age_ns)
        self._run_id: RunId | None = None
        self._action_id: str | None = None
        self._effects: dict[str, str | None] = {}
        self._effect_requests: dict[str, VehicleEffect] = {}
        self._envelopes: dict[str, EffectEnvelope] = {}
        self._dispatch_results: dict[str, DispatchResult] = {}
        self._results: dict[str, dict] = {}
        self._active_stream_ids: set[str] = set()
        self._last_cycle: TimePoint | None = None
        self._had_session = False
        self._fault: str | None = None
        self._closed = False

    def _new_world(self) -> WorldModel:
        age = self.profile.safety.max_snapshot_age_ns
        return WorldModel(uuid4().hex, FreshnessLimits(age, age, age))

    def _emit(self, event: str, **fields) -> None:
        if self._event_sink is not None:
            self._event_sink({"event": event, "at_monotonic_ns": self.clock().monotonic_ns,
                              "run_id": None if self._run_id is None else str(self._run_id), **fields})

    @property
    def session_id(self) -> str | None:
        return None if self._session is None or self._session.session_id is None else str(self._session.session_id)

    @property
    def connected(self) -> bool:
        return self._transport is not None

    def snapshot(self):
        """WorldQueryPort view for decision consumers."""
        return self.world_snapshot()

    def world_snapshot(self):
        """Return the immutable framework snapshot; no Gazebo truth enters here."""
        return self._world.snapshot()

    def connect(self) -> None:
        """Open one new TCP/codec/session epoch with SEND disabled."""
        if self._closed or self._transport is not None:
            raise RuntimeError("runtime closed or already connected")
        self.authority.set_system_send(False)
        self.authority.set_action_send(False)
        self.authority.revoke()
        self.authority.set_link_session(None)
        transport = self._transport_factory(self.profile.host, self.profile.port,
                                            timeout_s=self.profile.period_ns / 2e9)
        codec = MavlinkCodec(source_system=250, source_component=191,
                             target_system=1, target_component=1)
        port = ArduPilotCommandPort(authority=self.authority, transport=transport, codec=codec,
                                    translator=self._translator, now=self.clock,
                                    stop_speed_tolerance=0.1 if self.profile.kind == "rover" else 0.05,
                                    write_guard=self._write_guard)
        capture_clock = SimulationSourceClock()
        session = ArduPilotSession(
            transport=transport, codec=codec, authority=self.authority,
            commands=port, link_timeout_ns=self.profile.link_timeout_ns,
            expected_vehicle_type=self.profile.mav_type,
            state_factory=lambda session_id: (RoverTelemetryState if self.profile.kind == "rover" else ArduPilotTelemetryState)(
                vehicle_id=self.profile.vehicle_id, generation_id=str(session_id),
                link_session_id=session_id, source_system=1, source_component=1,
                max_sample_skew_ns=500_000_000,
                max_field_age_ns=self.profile.safety.max_snapshot_age_ns,
                link_timeout_ns=self.profile.link_timeout_ns),
            captured_at=lambda message, received: self._capture(capture_clock, message, received),
        )
        self._transport, self._port, self._session = transport, port, session
        safety_class = RoverSimulationSafetyPolicy if self.profile.kind == "rover" else SimulationSafetyPolicy
        self._execution = VehicleExecution(port, self.authority,
                                           safety_class(self.profile.safety,
                                                        motion_mode_id=self.profile.mode_ids["GUIDED"]),
                                           lambda: f"command:{uuid4().hex}")
        self._world = self._new_world()
        self.localization = OnlineLocalization(self.profile.safety.max_snapshot_age_ns)
        self._last_cycle = None
        self._had_session = False
        self._run_id = None
        self._action_id = None
        self._fault = None
        self._active_stream_ids.clear()
        self._emit("connected_transport", host=self.profile.host, port=self.profile.port)

    def _capture(self, source_clock, message, received):
        captured = source_clock.capture(message, received)
        if message.get_type() in ("LOCAL_POSITION_NED", "GLOBAL_POSITION_INT", "ATTITUDE"):
            self._emit("source_time", message_type=message.get_type(), boot_ms=int(message.time_boot_ms),
                       capture_ns=captured.monotonic_ns, receive_ns=received.monotonic_ns,
                       clock_domain=str(received.clock_domain_id))
        return captured

    def _write_guard(self, command: VehicleCommandEnvelope) -> str | None:
        if self._session is None or self._session.session_id is None:
            return "link_disconnected"
        state = self._session.snapshot()
        if state is None or state.health.quality is not QualityState.VALID:
            return "fresh_vehicle_state_required"
        now = self.clock()
        heartbeat = self._session.last_heartbeat_received_at
        try:
            if heartbeat is None or not 0 <= now.elapsed_ns_since(heartbeat) <= self.profile.link_timeout_ns:
                return "heartbeat_stale"
            if not 0 <= now.elapsed_ns_since(state.published_at) <= self.profile.safety.max_snapshot_age_ns:
                return "vehicle_state_stale"
        except ValueError:
            return "vehicle_clock_domain_mismatch"
        if isinstance(command.command, StopMotionCommand):
            return None  # A connected stop remains possible if localization is stale.
        if isinstance(command.command, (PoseTargetCommand, TwistTargetCommand, TakeoffCommand)):
            if state.reported_pose is None or state.reported_twist is None:
                return "motion_state_unavailable"
            for sample in (state.reported_pose, state.reported_twist):
                try:
                    if not 0 <= now.elapsed_ns_since(sample.captured_at) <= self.profile.safety.max_snapshot_age_ns:
                        return "motion_state_stale"
                except ValueError:
                    return "motion_clock_domain_mismatch"
            if not state.operation.armed:
                return "motion_requires_armed"
            if state.operation.native_mode != f"ARDUPILOT_CUSTOM_{self.profile.mode_ids['GUIDED']}":
                return "motion_requires_guided_mode"
        return None

    def _close_link(self, reason: str) -> None:
        self._fault = reason
        self.authority.set_system_send(False)
        self.authority.set_action_send(False)
        self.authority.revoke()
        if self._session is not None:
            self._session.close(self.clock())
        self._record_results()
        self._session = None
        self._transport = None
        self._execution = None
        self._port = None
        self._run_id = None
        self._action_id = None
        for stream_id in self._active_stream_ids:
            self._emit("stream_outcome_unconfirmed", stream_id=stream_id, reason=reason)
        self._emit("link_closed", reason=reason)

    def _record_results(self) -> None:
        if self._port is None:
            return
        for effect_id, command_id in self._effects.items():
            if command_id is None:
                continue
            status = self._port.status(command_id)
            if status is None:
                continue
            value = {"phase": status.phase.value, "command_id": str(command_id),
                     "reason": self._port.reasons.get(command_id)}
            if self._results.get(effect_id) != value:
                self._results[effect_id] = value
                self._emit("effect_status", effect_id=effect_id, **value)

    def cycle(self) -> SimulationCycle:
        if self._closed or self._session is None or self._execution is None:
            raise RuntimeError("runtime is not connected")
        now = self.clock()
        if self._last_cycle is not None:
            try:
                elapsed = now.elapsed_ns_since(self._last_cycle)
                if elapsed < 0:
                    self._close_link("cycle_clock_regressed")
                    return SimulationCycle(0, None, None, False, self._fault)
                if elapsed > 2 * self.profile.period_ns:
                    self._close_link("cycle_deadline_missed")
                    return SimulationCycle(0, None, None, False, self._fault)
            except ValueError:
                self._close_link("cycle_clock_domain_mismatch")
                return SimulationCycle(0, None, None, False, self._fault)
        self._last_cycle = now
        try:
            messages = self._session.poll(now)
        except (OSError, ConnectionError, ValueError) as exc:
            self._close_link(f"receive_fault:{type(exc).__name__}")
            return SimulationCycle(0, None, None, False, self._fault)
        now = self.clock()
        if self._session.session_id is not None:
            self._had_session = True
        elif self._had_session:
            self._close_link("link_session_lost")
            return SimulationCycle(len(messages), None, None, False, self._fault)
        try:
            state = self._session.snapshot()
            self._world.update_vehicle(state)
            estimate, transform_dependency = self.localization.update(state, now)
            self._world.update_localization(estimate)
            self._world.update_transform_dependency(transform_dependency)
            world = self._world.publish(now)
        except ValueError as exc:
            self._close_link(f"world_state_fault:{type(exc).__name__}")
            return SimulationCycle(len(messages), None, None, False, self._fault)
        if self._run_id is not None and (self._session.session_id is None or world.vehicle is None):
            self._close_link("vehicle_state_or_link_stale")
            return SimulationCycle(len(messages), None, None, False, self._fault)
        self._execution.tick(now)
        written = self._session.write_next(self.clock()) if self._session.session_id is not None else None
        self._record_results()
        if written is not None and written.phase.value == "UNKNOWN":
            self._close_link("transport_write_uncertain")
            return SimulationCycle(len(messages), written, None, False, self._fault)
        for stream_id in tuple(self._active_stream_ids):
            if self._execution.stop_status(stream_id).state is StopState.CONFIRMED:
                self._active_stream_ids.discard(stream_id)
        state = world.vehicle
        if world.localization is not None and state is not None:
            if world.localization.pose != state.reported_pose or world.localization.version.revision != state.version.revision:
                self._close_link("localization_source_mismatch")
                return SimulationCycle(len(messages), written, None, False, self._fault)
            self._emit("state_cut", world_generation=world.version.generation_id,
                       world_revision=world.version.revision, source_generation=state.version.generation_id,
                       source_revision=state.version.revision, transform_epoch=self.localization.epoch,
                       capture_ns=world.localization.pose.captured_at.monotonic_ns,
                       publish_ns=now.monotonic_ns, frame=str(world.localization.pose.frame_id))
        fresh = (state is not None and state.health.quality is QualityState.VALID
                 and state.reported_pose is not None and state.reported_twist is not None)
        return SimulationCycle(len(messages), written, self.session_id, fresh, self._fault)

    def begin_run(self, *, allow_send: bool = False, run_id: str | None = None,
                  action_id: str | None = None) -> str:
        if self._closed or self._session is None or self._session.session_id is None or self._run_id is not None:
            raise RuntimeError("fresh link and idle runtime required")
        world = self._world.snapshot()
        if world is None or world.vehicle is None or world.vehicle.health.quality is not QualityState.VALID:
            raise RuntimeError("fresh vehicle state required")
        now = self.clock()
        if not 0 <= now.elapsed_ns_since(world.vehicle.published_at) <= self.profile.safety.max_snapshot_age_ns:
            raise RuntimeError("vehicle state stale")
        self._run_id = RunId(run_id or f"simulation:{uuid4().hex}")
        self._action_id = action_id or f"{self._run_id}:control:1"
        if allow_send:
            self.authority.grant(ControlLease(f"lease:{uuid4().hex}", self._run_id,
                                               self._action_id, _later(now, self.profile.lease_ns)), now)
            self.authority.set_system_send(True)
            self.authority.set_action_send(True)
        self._emit("run_started", allow_send=allow_send, session_id=self.session_id)
        return str(self._run_id)

    def submit_effect(self, effect: VehicleEffect, *, effect_id: str | None = None) -> DispatchResult:
        if self._closed or self._run_id is None or self._action_id is None or self._execution is None:
            raise RuntimeError("active run required")
        selected_id = effect_id or f"effect:{uuid4().hex}"
        if selected_id in self._effect_requests:
            if self._effect_requests[selected_id] != effect:
                raise ValueError("effect ID reused for different content")
            return self._dispatch_results[selected_id]
        now = self.clock()
        envelope = EffectEnvelope(SchemaVersion(1, 0), selected_id,
                                  self._run_id, self._action_id, now,
                                  _later(now, self.profile.effect_ttl_ns), effect)
        return self.dispatch_envelope(envelope)

    def authorize_action(self, action_id: str, *, allow_send: bool) -> None:
        """Deployment selects a compiled step; a client cannot create a lease."""
        if self._run_id is None or self._execution is None or self.session_id is None:
            raise RuntimeError("active connected run required")
        if self._execution.active_stream_ids():
            raise RuntimeError("previous Action stop barrier incomplete")
        self.authority.set_system_send(False)
        self.authority.revoke()
        self._action_id = action_id
        if allow_send:
            now = self.clock()
            self.authority.grant(ControlLease(f"lease:{uuid4().hex}", self._run_id,
                                             action_id, _later(now, self.profile.lease_ns)), now)
            self.authority.set_system_send(True)
            self.authority.set_action_send(True)

    def dispatch_envelope(self, envelope: EffectEnvelope) -> DispatchResult:
        """Preserve the Mission identity and deadline at the Execution boundary."""
        if not isinstance(envelope, EffectEnvelope):
            raise TypeError("typed envelope required")
        if (self._run_id is None or self._execution is None or self.session_id is None
                or envelope.run_id != self._run_id or envelope.action_instance_id != self._action_id):
            return DispatchResult(None, "inactive_mission_scope")
        selected_id = str(envelope.effect_id)
        if selected_id in self._envelopes:
            if self._envelopes[selected_id] != envelope:
                raise ValueError("effect ID reused for different envelope")
            return self._dispatch_results[selected_id]
        world = self._world.snapshot()
        if world is None:
            return DispatchResult(None, "world_state_unavailable")
        result = self._execution.dispatch(envelope, world, self.clock())
        self._envelopes[selected_id] = envelope
        self._effect_requests[selected_id] = envelope.effect
        self._dispatch_results[selected_id] = result
        command_id = None if result.receipt is None else str(result.receipt.command_id)
        self._effects[selected_id] = command_id
        from contracts.effects.vehicle import PoseTargetEffect, TwistTargetEffect
        if result.receipt is not None and isinstance(envelope.effect, (PoseTargetEffect, TwistTargetEffect)):
            self._active_stream_ids.add(envelope.effect.stream_id)
        self._results[selected_id] = {
            "phase": "REJECTED" if result.receipt is None else result.receipt.phase.value,
            "command_id": command_id, "reason": result.reason,
        }
        self._emit("effect_submitted", effect_id=selected_id, action_id=str(envelope.action_instance_id),
                   deadline_ns=envelope.deadline.monotonic_ns, command_id=command_id, reason=result.reason)
        return result

    def effect_status(self, effect_id: str) -> dict | None:
        self._record_results()
        result = self._results.get(effect_id)
        return None if result is None else dict(result)

    def end_run(self) -> dict[str, str]:
        """Request a bounded stop before revoking the run's send authority."""
        stops: dict[str, str] = {}
        if self._active_stream_ids:
            if self._execution is None or self._session is None or self.session_id is None:
                stops = {stream_id: StopState.UNCONFIRMED.value for stream_id in self._active_stream_ids}
            else:
                for stream_id in tuple(self._active_stream_ids):
                    result = self._execution.stop_stream(stream_id, self.clock())
                    stops[stream_id] = result.state.value
                deadline = time.monotonic_ns() + self.profile.effect_ttl_ns
                while (any(value != StopState.CONFIRMED.value for value in stops.values())
                       and time.monotonic_ns() < deadline and self._session is not None):
                    cycle = self.cycle()
                    for stream_id in tuple(stops):
                        result = self._execution.stop_status(stream_id) if self._execution is not None else None
                        if result is not None:
                            stops[stream_id] = result.state.value
                    if cycle.fault is not None:
                        break
                    if any(value != StopState.CONFIRMED.value for value in stops.values()):
                        self._sleep(self.profile.period_ns / 1e9)
                for stream_id, value in tuple(stops.items()):
                    if value != StopState.CONFIRMED.value:
                        stops[stream_id] = StopState.UNCONFIRMED.value
        self.authority.set_action_send(False)
        self.authority.set_system_send(False)
        self.authority.revoke()
        self._run_id = None
        self._action_id = None
        self._emit("run_ended", stops=stops)
        if any(value == StopState.UNCONFIRMED.value for value in stops.values()) and self._session is not None:
            self._close_link("stop_unconfirmed")
        return stops

    def shutdown(self) -> dict[str, str]:
        if self._closed:
            return {}
        stops = self.end_run() if self._run_id is not None else {}
        if self._session is not None:
            self._close_link("shutdown")
        self._closed = True
        self._emit("shutdown", stops=stops)
        return stops

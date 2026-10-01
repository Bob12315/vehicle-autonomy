"""Explicit ArduPilot link composition; no connection is opened here."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from contracts.core.primitives import LinkSessionId
from contracts.core.time import TimePoint
from contracts.vehicle.command import CommandStatus
from contracts.vehicle.models import VehicleStateSnapshot
from core.control_authority import ControlAuthority
from infrastructure.transports.bytes import ByteTransport
from protocols.mavlink.codec import MavlinkCodec
from protocols.mavlink import constants as mavlink

from .mavlink_port import ArduPilotCommandPort
from .mavlink_state import ArduPilotTelemetryState


class ArduPilotSession:
    """One receiver and one writer over an injected transport.

    Capture timing is mandatory for state publication. A caller may leave it
    absent for ACK/link handling, so unknown vehicle sample age never becomes
    a fresh VehicleState by assumption.
    """

    def __init__(self, *, transport: ByteTransport, codec: MavlinkCodec,
                 authority: ControlAuthority, commands: ArduPilotCommandPort,
                 state_factory: Callable[[LinkSessionId], ArduPilotTelemetryState],
                 link_timeout_ns: int,
                 expected_vehicle_type: int,
                 captured_at: Callable[[object, TimePoint], TimePoint | None] | None = None) -> None:
        if isinstance(link_timeout_ns, bool) or not isinstance(link_timeout_ns, int) or link_timeout_ns <= 0:
            raise ValueError("link timeout must be positive nanoseconds")
        if not commands.uses(authority=authority, transport=transport, codec=codec):
            raise ValueError("session and command writer must share authority, transport and codec")
        if isinstance(expected_vehicle_type, bool) or not isinstance(expected_vehicle_type, int) or not 0 <= expected_vehicle_type <= 255:
            raise ValueError("expected MAVLink vehicle type is required")
        self._transport = transport
        self._codec = codec
        self._authority = authority
        self._commands = commands
        self._state_factory = state_factory
        self._link_timeout_ns = link_timeout_ns
        self._expected_vehicle_type = expected_vehicle_type
        self._captured_at = captured_at
        self._session_id: LinkSessionId | None = None
        self._state: ArduPilotTelemetryState | None = None
        self._last_heartbeat: TimePoint | None = None
        self.last_rejected_vehicle_type: int | None = None

    @property
    def session_id(self) -> LinkSessionId | None:
        return self._session_id

    @property
    def last_heartbeat_received_at(self) -> TimePoint | None:
        return self._last_heartbeat

    def poll(self, received_at: TimePoint) -> tuple[object, ...]:
        self.tick(received_at)
        try:
            chunk = self._transport.read()
        except (OSError, ConnectionError):
            self._disconnect(received_at)
            raise
        if chunk is None:
            return ()
        messages = self._codec.feed(chunk)
        ingested = False
        for message in messages:
            if (message.get_srcSystem(), message.get_srcComponent()) != (
                self._codec.target_system, self._codec.target_component,
            ):
                continue
            if message.get_type() == "HEARTBEAT":
                if (message.autopilot != mavlink.AUTOPILOT_ARDUPILOT
                        or message.type != self._expected_vehicle_type):
                    self.last_rejected_vehicle_type = int(message.type)
                    self._disconnect(received_at)
                    continue
                if self._session_id is None:
                    self._session_id = LinkSessionId(uuid4().hex)
                    self._state = self._state_factory(self._session_id)
                    self._commands.reset_session(received_at)
                    self._authority.set_link_session(self._session_id)
                self._last_heartbeat = received_at
            if self._session_id is None:
                continue
            if message.get_type() == "COMMAND_ACK":
                self._commands.handle_ack(message, received_at)
            elif message.get_type() == "HEARTBEAT":
                self._commands.observe_heartbeat(message, received_at)
            if self._captured_at is not None and self._state is not None:
                sample_time = self._captured_at(message, received_at)
                if sample_time is not None:
                    ingested |= self._state.ingest(
                        message, captured_at=sample_time, received_at=received_at,
                    )
        if ingested and self._state is not None:
            state = self._state.publish(received_at)
            self._commands.observe_state(state)
        return messages

    def tick(self, now: TimePoint) -> tuple[CommandStatus, ...]:
        if self._last_heartbeat is not None:
            try:
                age = now.elapsed_ns_since(self._last_heartbeat)
            except ValueError:
                age = self._link_timeout_ns + 1
            if age < 0 or age > self._link_timeout_ns:
                self._disconnect(now)
        return self._commands.expire_unknown(now)

    def write_next(self, now: TimePoint) -> CommandStatus | None:
        self.tick(now)
        return self._commands.write_next(now)

    def snapshot(self) -> VehicleStateSnapshot | None:
        return None if self._state is None else self._state.snapshot()

    def _disconnect(self, now: TimePoint) -> None:
        # Link loss invalidates a run's authority, not just its command queue.
        # A later heartbeat may establish a new session, but cannot revive the
        # previous SEND gates or Action lease.
        self._authority.set_system_send(False)
        self._authority.set_action_send(False)
        self._authority.revoke()
        self._authority.set_link_session(None)
        self._commands.reset_session(now)
        self._session_id = None
        self._last_heartbeat = None
        self._state = None

    def close(self, now: TimePoint) -> None:
        self._disconnect(now)
        self._transport.close()

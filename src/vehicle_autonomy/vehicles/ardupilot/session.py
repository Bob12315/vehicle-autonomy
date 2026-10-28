"""Explicit ArduPilot link composition; no connection is opened here."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from vehicle_autonomy.contracts.core.primitives import LinkSessionId
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.vehicle.command import CommandStatus
from vehicle_autonomy.contracts.vehicle.models import VehicleStateSnapshot
from vehicle_autonomy.engine.control.control_authority import ControlAuthority
from vehicle_autonomy.vehicles.ardupilot.transports.bytes import ByteTransport
from vehicle_autonomy.vehicles.ardupilot.mavlink.codec import MavlinkCodec
from vehicle_autonomy.vehicles.ardupilot.mavlink import constants as mavlink

from vehicle_autonomy.vehicles.ardupilot.command_port import ArduPilotCommandPort
from vehicle_autonomy.vehicles.ardupilot.telemetry_state import ArduPilotTelemetryState


class ArduPilotSession:
    """One receiver and one writer over an injected transport.

    Capture timing is mandatory for state publication. A caller may leave it
    absent for link diagnostics. ACK/operation confirmation additionally needs
    the codec's explicit receive authenticator. Source-clock qualification is
    only a telemetry ordering policy; it cannot authenticate a heartbeat.
    """

    def __init__(self, *, transport: ByteTransport, codec: MavlinkCodec,
                 authority: ControlAuthority, commands: ArduPilotCommandPort,
                 state_factory: Callable[[LinkSessionId], ArduPilotTelemetryState],
                 link_timeout_ns: int,
                 expected_vehicle_type: int,
                 captured_at: Callable[[object, TimePoint], TimePoint | None] | None = None,
                 confirmation_time_qualified: bool = False,
                 time_sync=None, clock=None) -> None:
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
        if not isinstance(confirmation_time_qualified, bool):
            raise TypeError("source-time qualification must be explicit bool")
        if time_sync is not None and (codec.receive_signing is None or not callable(clock)):raise ValueError("clock sync requires authenticated simulation timing")
        self._time_sync=time_sync;self._clock=clock;self._last_write_was_query=False
        self._captured_at = captured_at
        self._confirmation_time_qualified = confirmation_time_qualified
        self._session_id: LinkSessionId | None = None
        self._state: ArduPilotTelemetryState | None = None
        self._last_heartbeat: TimePoint | None = None
        self.last_rejected_vehicle_type: int | None = None
        self._rx_sequence: int | None = None
        self._rx_ticket = -1
        self._boot: dict[str, int] = {}
        self._source_capture: TimePoint | None = None
        self._source_boot: int | None = None
        self._reply_interval_ambiguous = False
        self._pending_packets: list[tuple] = []
        self._delivered_ticket = -1
        self.receive_rejections = {"duplicate": 0, "out_of_order": 0, "stale_sample": 0, "ambiguous_backlog": 0}

    def _accept_packet(self, message: object, received_at: TimePoint) -> bool:
        """Serial ordering plus source-clock progress; no request identity implied.

        Old samples cannot advance an anchor. A fresh timestamped source may
        re-anchor a large gap, discarding all unqualified reply evidence.
        """
        kind = message.get_type()
        boot = getattr(message, "time_boot_ms", None)
        if boot is not None and kind in self._boot and boot <= self._boot[kind]:
            if boot < self._boot[kind] and self._rx_sequence is not None and 0 < ((message.get_seq() - self._rx_sequence) & 255) < 128:
                self._disconnect(received_at)
                raise ValueError("source boot clock regressed; new transport/session required")
            reason = "duplicate" if boot == self._boot[kind] else "stale_sample"
            self.receive_rejections[reason] += 1
            if self._state is not None:
                self._state.note_rejected_telemetry(message, reason)
            return False
        seq = message.get_seq()
        delta = 1 if self._rx_sequence is None else (seq - self._rx_sequence) & 255
        if (delta == 0 or delta >= 128) and boot is not None and boot > max(self._boot.get(kind, -1), self._source_boot or -1):
            # Equal 8-bit headers can be a COMPLETE wrap, not a duplicate.
            # Only qualified source-clock progress permits re-anchoring.
            self._pending_packets.clear()
            if delta == 0:
                delta = 256
        elif delta == 0 or delta >= 128:
            reason = "duplicate" if delta == 0 else "out_of_order"
            self.receive_rejections[reason] += 1
            if self._state is not None:
                self._state.note_rejected_telemetry(message, reason)
            return False
        self._rx_sequence = seq
        self._rx_ticket += delta
        if boot is not None:
            self._boot[kind] = int(boot)
        return True

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

        def deliver(message, at, ticket, sample_time, *, before=None, before_boot=None, after=None, after_boot=None):
            nonlocal ingested
            self._commands.observe_receive_ticket(ticket)
            if message.get_type() == "COMMAND_ACK":
                self._commands.handle_ack(message, at, ticket=ticket)
            elif message.get_type() == "HEARTBEAT":
                self._commands.observe_heartbeat(message, at, ticket=ticket,
                    before_capture=before, after_capture=after,
                    before_boot=before_boot, after_boot=after_boot)
            if message.get_type() == "POSITION_TARGET_GLOBAL_INT":
                self._commands.observe_native_target(message, at)
            if self._state is not None and self._captured_at is not None:
                if sample_time is not None:
                    ingested |= self._state.ingest(message, captured_at=sample_time, received_at=at)
                else:
                    self._state.observe_telemetry(message, captured_at=None, received_at=at)
            self._delivered_ticket = ticket

        for message in messages:
            if (message.get_srcSystem(), message.get_srcComponent()) != (
                self._codec.target_system, self._codec.target_component,
            ):
                continue
            kind = message.get_type()
            if kind == "HEARTBEAT":
                if message.autopilot != mavlink.AUTOPILOT_ARDUPILOT or message.type != self._expected_vehicle_type:
                    self.last_rejected_vehicle_type = int(message.type)
                    self._disconnect(received_at)
                    continue
                if self._session_id is None:
                    self._session_id = LinkSessionId(uuid4().hex)
                    self._state = self._state_factory(self._session_id)
                    self._commands.reset_session(received_at)
                    self._authority.set_link_session(self._session_id)
                # Transport liveness only. This never qualifies a command or
                # renews normalized operation state until the source bracket.
                self._last_heartbeat = received_at
            if self._session_id is None:
                continue
            signature = getattr(message, '_vaf_signature_timestamp', None)
            if self._codec.receive_signing is not None and signature is None:
                reason = getattr(message, '_vaf_signature_rejection', 'unqualified')
                counter = 'duplicate' if reason == 'replay' else 'unqualified_packet'
                self.receive_rejections[counter] = self.receive_rejections.get(counter,0)+1
                self._state.note_rejected_telemetry(message, 'duplicate' if reason == 'replay' else 'unqualified')
                # Keep the last authenticated diagnostic value too. Raw
                # rejected payloads remain in the caller's receive log; they
                # must not overwrite WorldSnapshot's newer heartbeat field.
                continue
            if kind=='TIMESYNC' and self._time_sync is not None:
                self._time_sync.observe(message,self._clock(),self._commands.wire_attempted_bytes);continue
            if kind in ('HEARTBEAT', 'COMMAND_ACK'):
                if signature is None:
                    # Unauthenticated headers and other messages' timestamps
                    # cannot establish the generation of this state/ACK.
                    self.receive_rejections.setdefault('unqualified_confirmation', 0)
                    self.receive_rejections['unqualified_confirmation'] += 1
                    self._state.observe_telemetry(message, captured_at=None, received_at=received_at)
                else:
                    # The pinned stream's MAC and strictly increasing 48-bit
                    # timestamp were checked by Codec, independently of seq.
                    deliver(message, received_at, self._rx_ticket, received_at)
                continue
            if signature is not None and kind not in ('ATTITUDE','GLOBAL_POSITION_INT','LOCAL_POSITION_NED'):
                # Authenticated stream order is independently proven. Don't
                # delay these packets behind a source bracket: that would
                # ingest their OLD receive time after a newer signed heartbeat.
                sample = None if self._captured_at is None else self._captured_at(message,received_at)
                deliver(message,received_at,self._rx_ticket,sample)
                continue
            if self._confirmation_time_qualified and kind not in ("ATTITUDE", "GLOBAL_POSITION_INT", "LOCAL_POSITION_NED"):
                if self._rx_sequence is None:
                    self._rx_sequence, self._rx_ticket = message.get_seq(), 0
                    delta = 0
                else:
                    delta = (message.get_seq() - self._rx_sequence) & 255
                    if delta == 0 or delta >= 128:
                        self.receive_rejections["duplicate" if delta == 0 else "out_of_order"] += 1
                        if kind in ("HEARTBEAT", "COMMAND_ACK"):
                            self._reply_interval_ambiguous = True
                        continue
                # Untimestamped replies cannot move the anchor or poison it
                # across 8-bit wraps. Validate their positions at the NEXT
                # source-timed AP packet, never by receive time alone.
                if kind == "COMMAND_ACK":
                    # Observable candidate only; it cannot establish request
                    # identity or complete a goal. Do not advance the anchor.
                    self._commands.handle_ack(message, received_at, ticket=self._rx_ticket + delta)
                self._pending_packets.append((message, received_at, self._rx_ticket + delta,
                                              self._source_capture, self._source_boot))
                if len(self._pending_packets) > 256:
                    # Source progress is absent: drop unqualified evidence,
                    # keep its old state age, and continue read-only reception.
                    self.receive_rejections["ambiguous_backlog"] += len(self._pending_packets)
                    self._pending_packets.clear()
                    self._reply_interval_ambiguous = True
                continue
            if not self._accept_packet(message, received_at):
                continue
            sample = None if self._captured_at is None else self._captured_at(message, received_at)
            if self._confirmation_time_qualified:
                boot = int(message.time_boot_ms)
                pending, self._pending_packets = self._pending_packets, []
                tickets = [packet[2] for packet in pending]
                ambiguous = (self._reply_interval_ambiguous or any(t >= self._rx_ticket for t in tickets)
                             or any(b <= a for a, b in zip(tickets, tickets[1:])))
                self._reply_interval_ambiguous = False
                for old, at, ticket, before, before_boot in pending:
                    if not ambiguous and self._delivered_ticket < ticket < self._rx_ticket:
                        old_sample = self._captured_at(old, at)
                        deliver(old, at, ticket, old_sample, before=before, before_boot=before_boot,
                                after=sample, after_boot=boot)
                    else:
                        self.receive_rejections["out_of_order"] += 1
                        self._state.note_rejected_telemetry(old, "out_of_order")
                if sample is not None and (self._source_boot is None or boot > self._source_boot):
                    self._source_capture, self._source_boot = sample, boot
            deliver(message, received_at, self._rx_ticket, sample)
        if ingested and self._state is not None:
            self._commands.observe_state(self._state.publish(received_at))
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
        if self._time_sync is not None and self._session_id is not None and self._commands.protocol_query_slot_available:
            nonce=self._time_sync.request_due(self._clock())
            if nonce is not None:
                # A caller with a slow cadence must still make control progress.
                # One query cannot take two consecutive available control slots.
                if self._last_write_was_query:
                    written=self._commands.write_next(now)
                    if written is not None:
                        self._last_write_was_query=False;return written
                try:self._time_sync.sent(nonce,*self._commands.write_timesync(nonce))
                except (OSError,ConnectionError):self._disconnect(self._clock());raise
                self._last_write_was_query=True;return None
        written=self._commands.write_next(now)
        # An idle owner cycle is not a control write. Preserve priority earned
        # after an actual query until a queued control attempt consumes it.
        if written is not None:self._last_write_was_query=False
        return written

    def snapshot(self) -> VehicleStateSnapshot | None:
        return None if self._state is None else self._state.snapshot()

    def telemetry_snapshot(self, at_time: TimePoint):
        """Current diagnostic ages; never refreshes the control state timestamp."""
        return None if self._state is None else self._state.telemetry_snapshot(at_time)

    def link_snapshot(self, at_time: TimePoint):
        return None if self._state is None else self._state.link_snapshot(at_time)

    def local_reference(self):
        return None if self._state is None else self._state.local_reference()

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
        self._rx_sequence = None
        self._rx_ticket = -1
        self._boot.clear()
        self._source_capture = None
        self._source_boot = None
        self._reply_interval_ambiguous = False
        self._pending_packets.clear()
        self._delivered_ticket = -1

    def close(self, now: TimePoint) -> None:
        self._disconnect(now)
        self._transport.close()

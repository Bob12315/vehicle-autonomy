"""In-memory P4 authorization and write-time fence, independent of devices."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from contracts.core.primitives import ActionInstanceId, LeaseId, LinkSessionId, RunId
from contracts.core.time import TimePoint
from contracts.vehicle.command import VehicleCommandEnvelope


@dataclass(frozen=True, slots=True)
class ControlLease:
    lease_id: LeaseId
    run_id: RunId
    action_instance_id: ActionInstanceId
    expires_at: TimePoint

    def __post_init__(self) -> None:
        for name, kind in (("lease_id", LeaseId), ("run_id", RunId), ("action_instance_id", ActionInstanceId)):
            if not isinstance(getattr(self, name), kind):
                object.__setattr__(self, name, kind(getattr(self, name)))
        if not isinstance(self.expires_at, TimePoint):
            raise TypeError("lease expiry must be TimePoint")


class ControlAuthority:
    """One active lease. Mutations fence already queued commands by generation."""

    def __init__(self) -> None:
        self.lock = RLock()
        self._system_send = False
        self._action_send = False
        self._authorization_generation = 0
        self._send_generation = 0
        self._lease: ControlLease | None = None
        self._link_session_id: LinkSessionId | None = None

    @property
    def system_send(self) -> bool:
        return self._system_send

    @property
    def action_send(self) -> bool:
        return self._action_send

    @property
    def authorization_generation(self) -> int:
        return self._authorization_generation

    @property
    def send_generation(self) -> int:
        return self._send_generation

    @property
    def lease(self) -> ControlLease | None:
        return self._lease

    @property
    def link_session_id(self) -> LinkSessionId | None:
        return self._link_session_id

    def set_system_send(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("SEND must be bool")
        with self.lock:
            if enabled != self.system_send:
                self._system_send = enabled
                self._send_generation += 1

    def set_action_send(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("Action SEND must be bool")
        with self.lock:
            if enabled != self.action_send:
                self._action_send = enabled
                self._send_generation += 1

    def grant(self, lease: ControlLease, now: TimePoint) -> None:
        if not isinstance(lease, ControlLease) or not isinstance(now, TimePoint):
            raise TypeError("grant requires ControlLease and TimePoint")
        if lease.expires_at.elapsed_ns_since(now) <= 0:
            raise ValueError("lease must expire in the future")
        with self.lock:
            self._lease = lease
            self._authorization_generation += 1
            self._action_send = False
            self._send_generation += 1

    def revoke(self) -> None:
        with self.lock:
            self._lease = None
            self._action_send = False
            self._authorization_generation += 1
            self._send_generation += 1

    def set_link_session(self, session_id: LinkSessionId | None) -> None:
        if session_id is not None and not isinstance(session_id, LinkSessionId):
            session_id = LinkSessionId(session_id)
        with self.lock:
            if session_id != self._link_session_id:
                self._link_session_id = session_id
                self._send_generation += 1

    def admission_reason(self, run_id: RunId, action_id: ActionInstanceId, now: TimePoint) -> str | None:
        with self.lock:
            if not self.system_send:
                return "system_send_disabled"
            if not self.action_send:
                return "action_send_disabled"
            if self.lease is None:
                return "no_lease"
            if self.lease.run_id != run_id or self.lease.action_instance_id != action_id:
                return "lease_scope_mismatch"
            if self.lease.expires_at.clock_domain_id != now.clock_domain_id or self.lease.expires_at.elapsed_ns_since(now) <= 0:
                return "lease_expired"
            if self.link_session_id is None:
                return "link_disconnected"
            return None

    def write_reason(self, command: VehicleCommandEnvelope, now: TimePoint) -> str | None:
        """Called by the sole writer immediately before its physical write point."""
        with self.lock:
            if self.lease is None or self.lease.lease_id != command.lease_id or self.lease.run_id != command.run_id:
                return "lease_revoked"
            if not self.system_send or not self.action_send:
                return "send_disabled"
            if command.authorization_generation != self.authorization_generation or command.send_generation != self.send_generation:
                return "generation_changed"
            if self.link_session_id is None or self.link_session_id != command.expected_link_session_id:
                return "link_session_changed"
            try:
                if self.lease.expires_at.elapsed_ns_since(now) <= 0 or command.deadline.elapsed_ns_since(now) <= 0:
                    return "expired"
                if now.elapsed_ns_since(command.created_at) < 0:
                    return "future_command"
            except ValueError:
                return "clock_domain_mismatch"
            return None

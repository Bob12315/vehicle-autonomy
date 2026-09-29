"""Vehicle-side forwarding and local safety boundary for remote deployment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from contracts.platform.vehicle_commands import (
    CancelRequest, CancellationReceipt, CommandStatusSnapshot,
    CommandSubmissionReceipt, VehicleCommandEnvelope,
)
from contracts.platform.vehicle_state import VehicleStateSnapshot
from contracts.sensors.camera import CameraFrame


@dataclass(frozen=True, slots=True)
class GatewayHealth:
    connected: bool
    local_safety_ready: bool
    last_remote_contact_monotonic_ns: int | None
    reason_code: str


@dataclass(frozen=True, slots=True)
class GatewayWatchdogStatus:
    link_expired: bool
    command_admission_closed: bool
    stop_requested: bool
    stop_confirmed: bool

    def __post_init__(self) -> None:
        if self.link_expired and not (self.command_admission_closed and self.stop_requested):
            raise ValueError("expired link must close admission and request stop")
        if self.stop_confirmed and not self.stop_requested:
            raise ValueError("stop cannot be confirmed before it is requested")


class GatewayTelemetryForwardPort(Protocol):
    def publish(self, snapshot: VehicleStateSnapshot) -> None: ...


class GatewaySensorForwardPort(Protocol):
    def publish_camera(self, frame: CameraFrame) -> None: ...


class GatewayHealthPort(Protocol):
    def health(self) -> GatewayHealth: ...


class GatewayWatchdogPort(Protocol):
    def check(self, now_monotonic_ns: int) -> GatewayWatchdogStatus: ...
    def status(self) -> GatewayWatchdogStatus: ...


class GatewayCommandIngress(Protocol):
    """Only trusted local admission may implement this port.

    It must validate authorization, SEND, lease, session, generation and TTL
    again at the vehicle before passing anything to the existing command port.
    Remote transport is never itself a command writer.
    """

    def submit(self, command: VehicleCommandEnvelope) -> CommandSubmissionReceipt: ...
    def cancel(self, request: CancelRequest) -> CancellationReceipt: ...
    def status(self, command_id: str) -> CommandStatusSnapshot: ...

"""Server-side ports only; network protocol and authentication are unspecified."""

from __future__ import annotations

from typing import Protocol

from contracts.platform.ports import VehicleCommandPort, VehicleStatePort
from contracts.sensors.camera import CameraPort

from .contracts import GatewayHealthPort


class RemoteVehicleLink(VehicleStatePort, VehicleCommandPort, GatewayHealthPort, Protocol):
    """Bound to Execution/Safety composition, never to Mission or Web."""


class RemoteCameraSource(CameraPort, Protocol):
    """Reconstructs standard CameraFrame locally after a future transport."""

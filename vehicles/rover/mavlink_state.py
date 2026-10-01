"""Rover global-position telemetry projected into a local ENU odom frame."""

from __future__ import annotations

import math

from contracts.core.geometry import Vector3
from contracts.core.time import TimePoint
from vehicles.multirotor.mavlink_state import ArduPilotTelemetryState


class RoverTelemetryState(ArduPilotTelemetryState):
    """Use GPS_GLOBAL_ORIGIN because this Rover emits no LOCAL_POSITION_NED.

    The local tangent-plane approximation is bounded by the simulation's
    five-metre geofence. Velocity arrives as NED cm/s in GLOBAL_POSITION_INT.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._origin: tuple[float, float, float] | None = None

    def ingest(self, message: object, *, captured_at: TimePoint, received_at: TimePoint) -> bool:
        accepted = super().ingest(message, captured_at=captured_at, received_at=received_at)
        if not accepted and message.get_type() != "GPS_GLOBAL_ORIGIN":
            return False
        if (message.get_srcSystem(), message.get_srcComponent()) != (self._source_system, self._source_component):
            return False
        if message.get_type() == "GPS_GLOBAL_ORIGIN":
            origin = (int(message.latitude) / 1e7, int(message.longitude) / 1e7,
                      int(message.altitude) / 1000)
            with self._lock:
                if self._origin is None:
                    self._origin = origin
                elif self._origin != origin:
                    # Changing EKF origin requires a new link/session frame.
                    self._position = None
                    self._origin = None
                    raise ValueError("Rover EKF origin changed during session")
            return True
        if message.get_type() == "GLOBAL_POSITION_INT":
            with self._lock:
                if self._origin is None:
                    return True
                lat0, lon0, alt0 = self._origin
                lat = int(message.lat) / 1e7
                lon = int(message.lon) / 1e7
                radius = 6378137.0
                north = math.radians(lat - lat0) * radius
                east = math.radians(lon - lon0) * radius * math.cos(math.radians(lat0))
                up = int(message.alt) / 1000 - alt0
                if math.hypot(east, north) > 50:
                    self._position = None
                    raise ValueError("Rover position exceeds local projection domain")
                self._position = (Vector3(east, north, up),
                                  Vector3(int(message.vy) / 100, int(message.vx) / 100,
                                          -int(message.vz) / 100), captured_at)
        return accepted

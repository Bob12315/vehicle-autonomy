"""MAVLink receive-only decoding; no link or command writer."""

from vehicle_autonomy.vehicles.ardupilot.mavlink.telemetry import decode_telemetry

__all__ = ["decode_telemetry"]

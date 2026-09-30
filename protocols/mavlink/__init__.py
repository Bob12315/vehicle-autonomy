"""MAVLink receive-only decoding; no link or command writer."""

from .telemetry import decode_telemetry

__all__ = ["decode_telemetry"]

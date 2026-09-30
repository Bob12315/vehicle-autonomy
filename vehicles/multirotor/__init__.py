"""Multirotor adapters; telemetry is read-only and command-free."""

from .mavlink_state import ArduPilotTelemetryState

__all__ = ["ArduPilotTelemetryState"]

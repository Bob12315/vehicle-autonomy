"""Decode selected parsed MAVLink telemetry messages into protocol facts."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class LocalPositionNed:
    north_m: float
    east_m: float
    down_m: float
    velocity_north_mps: float
    velocity_east_mps: float
    velocity_down_mps: float


@dataclass(frozen=True, slots=True)
class AttitudeFrdNed:
    roll_rad: float
    pitch_rad: float
    yaw_rad: float
    roll_rate_rad_s: float
    pitch_rate_rad_s: float
    yaw_rate_rad_s: float


@dataclass(frozen=True, slots=True)
class GlobalPositionInt:
    latitude_e7: int
    longitude_e7: int
    altitude_mm: int


@dataclass(frozen=True, slots=True)
class GpsFix:
    fix_type: int


@dataclass(frozen=True, slots=True)
class SystemPower:
    voltage_mv: int
    current_centiamp: int
    remaining_percent: int


@dataclass(frozen=True, slots=True)
class Heartbeat:
    base_mode: int
    custom_mode: int


TelemetryFact: TypeAlias = LocalPositionNed | AttitudeFrdNed | GlobalPositionInt | GpsFix | SystemPower | Heartbeat


def _finite(message: object, name: str) -> float:
    value = float(getattr(message, name))
    if not math.isfinite(value):
        raise ValueError(f"MAVLink {name} must be finite")
    return value


def _integer(message: object, name: str) -> int:
    value = getattr(message, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"MAVLink {name} must be an integer")
    return value


def decode_telemetry(message: object) -> TelemetryFact | None:
    """Accept pymavlink-style parsed messages without opening a connection."""
    try:
        message_type = str(message.get_type())
        if message_type == "LOCAL_POSITION_NED":
            return LocalPositionNed(*(_finite(message, name) for name in ("x", "y", "z", "vx", "vy", "vz")))
        if message_type == "ATTITUDE":
            return AttitudeFrdNed(*(_finite(message, name) for name in (
                "roll", "pitch", "yaw", "rollspeed", "pitchspeed", "yawspeed",
            )))
        if message_type == "GLOBAL_POSITION_INT":
            return GlobalPositionInt(*(_integer(message, name) for name in ("lat", "lon", "alt")))
        if message_type == "GPS_RAW_INT":
            return GpsFix(_integer(message, "fix_type"))
        if message_type == "SYS_STATUS":
            return SystemPower(*(_integer(message, name) for name in (
                "voltage_battery", "current_battery", "battery_remaining",
            )))
        if message_type == "HEARTBEAT":
            return Heartbeat(_integer(message, "base_mode"), _integer(message, "custom_mode"))
        return None
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid MAVLink telemetry message") from exc

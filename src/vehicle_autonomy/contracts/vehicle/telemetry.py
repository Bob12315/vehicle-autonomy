"""Read-only, session-bound normalized vehicle telemetry diagnostics.

Capture age and receive age are deliberately independent. Untimestamped AP
messages are observable but never acquire a fictional sensor sample time.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from vehicle_autonomy.contracts.core.geometry import GeoPoint, Quaternion, Vector3
from vehicle_autonomy.contracts.core.primitives import LinkSessionId
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.time import TimePoint


class TelemetryAvailability(str, Enum):
    MISSING = "MISSING"
    VALID = "VALID"
    STALE = "STALE"
    INVALID = "INVALID"
    UNKNOWN_CAPTURE_TIME = "UNKNOWN_CAPTURE_TIME"


@dataclass(frozen=True, slots=True)
class VehicleIdentity:
    mav_type: int | None
    autopilot: int | None
    native_mode: int
    armed: bool
    system_status: int | None


@dataclass(frozen=True, slots=True)
class AttitudeTelemetry:
    orientation_flu_enu: Quaternion
    angular_velocity_flu_rad_s: Vector3


@dataclass(frozen=True, slots=True)
class PositionTelemetry:
    position_enu_m: Vector3 | None
    velocity_enu_mps: Vector3 | None
    geographic: GeoPoint | None = None


@dataclass(frozen=True, slots=True)
class GpsTelemetry:
    fix_type: int
    satellites: int | None
    hdop: float | None
    vdop: float | None


@dataclass(frozen=True, slots=True)
class EkfTelemetry:
    flags: int
    velocity_variance: float
    horizontal_position_variance: float
    vertical_position_variance: float
    compass_variance: float
    terrain_altitude_variance: float


@dataclass(frozen=True, slots=True)
class PowerTelemetry:
    voltage_v: float | None
    current_a: float | None
    remaining_percent: float | None


@dataclass(frozen=True, slots=True)
class AckTelemetry:
    command: int
    result: int
    progress_percent: int | None


@dataclass(frozen=True, slots=True)
class StatusTextTelemetry:
    severity: int
    text: str
    message_id: int
    chunk_sequence: int


TelemetryValue = (VehicleIdentity | AttitudeTelemetry | PositionTelemetry | GpsTelemetry
                  | EkfTelemetry | PowerTelemetry | AckTelemetry | StatusTextTelemetry)


@dataclass(frozen=True, slots=True)
class TelemetryField:
    message_type: str
    availability: TelemetryAvailability
    quality: QualityState
    value: TelemetryValue | None
    frame_id: str | None
    captured_at: TimePoint | None
    received_at: TimePoint | None
    receive_fresh: bool
    observations: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    invalid: int = 0


@dataclass(frozen=True, slots=True)
class VehicleTelemetrySnapshot:
    link_session_id: LinkSessionId
    source_system: int
    source_component: int
    published_at: TimePoint
    fields: tuple[TelemetryField, ...]

    def field(self, message_type: str) -> TelemetryField:
        return next(item for item in self.fields if item.message_type == message_type)

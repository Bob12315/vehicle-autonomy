"""Vehicle-reported state and independent link-health contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from contracts.core.geometry import GeoPoint, Pose3, Twist3
from contracts.core.primitives import LinkSessionId, ResourceVersion, SchemaVersion, VehicleId
from contracts.core.quality import QualityState
from contracts.core.stamped import Stamped
from contracts.core.time import TimePoint


@dataclass(frozen=True, slots=True)
class VehicleOperation:
    armed: bool | None = None
    motion_state: str | None = None
    failsafe: bool | None = None
    native_mode: str | None = None

    def __post_init__(self) -> None:
        for name in ("armed", "failsafe"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"{name} must be bool or None")
        for name in ("motion_state", "native_mode"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be non-empty when provided")


@dataclass(frozen=True, slots=True)
class BatteryState:
    voltage_v: float | None = None
    current_a: float | None = None
    remaining_percent: float | None = None

    def __post_init__(self) -> None:
        for name in ("voltage_v", "current_a", "remaining_percent"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise TypeError(f"{name} must be a number or None")
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.voltage_v is not None and self.voltage_v < 0:
            raise ValueError("voltage_v must be non-negative")
        if self.remaining_percent is not None and not 0 <= self.remaining_percent <= 100:
            raise ValueError("remaining_percent must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class VehicleHealth:
    quality: QualityState
    faults: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.quality, QualityState):
            raise TypeError("quality must be QualityState")
        if not isinstance(self.faults, tuple):
            raise TypeError("faults must be a tuple")
        if any(not isinstance(fault, str) or not fault.strip() for fault in self.faults):
            raise ValueError("fault descriptions must be non-empty")


@dataclass(frozen=True, slots=True)
class VehicleStateSnapshot:
    schema_version: SchemaVersion
    vehicle_id: VehicleId
    version: ResourceVersion
    published_at: TimePoint
    health: VehicleHealth
    reported_pose: Stamped[Pose3] | None = None
    reported_twist: Stamped[Twist3] | None = None
    global_position: Stamped[GeoPoint] | None = None
    operation: VehicleOperation = field(default_factory=VehicleOperation)
    battery: BatteryState | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, SchemaVersion) or not isinstance(self.version, ResourceVersion):
            raise TypeError("vehicle state versions must be validated values")
        if not isinstance(self.published_at, TimePoint):
            raise TypeError("published_at must be TimePoint")
        if not isinstance(self.health, VehicleHealth) or not isinstance(self.operation, VehicleOperation):
            raise TypeError("vehicle health and operation must be typed values")
        if not isinstance(self.vehicle_id, VehicleId):
            object.__setattr__(self, "vehicle_id", VehicleId(self.vehicle_id))
        for name in ("reported_pose", "reported_twist", "global_position"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Stamped):
                raise TypeError(f"{name} must be Stamped")
        if self.reported_pose is not None and not isinstance(self.reported_pose.value, Pose3):
            raise TypeError("reported_pose must contain Pose3")
        if self.reported_twist is not None and not isinstance(self.reported_twist.value, Twist3):
            raise TypeError("reported_twist must contain Twist3")
        if self.global_position is not None and not isinstance(self.global_position.value, GeoPoint):
            raise TypeError("global_position must contain GeoPoint")
        if self.battery is not None and not isinstance(self.battery, BatteryState):
            raise TypeError("battery must be BatteryState")


@dataclass(frozen=True, slots=True)
class LinkStateSnapshot:
    schema_version: SchemaVersion
    vehicle_id: VehicleId
    version: ResourceVersion
    published_at: TimePoint
    connected: bool
    health: QualityState
    link_session_id: LinkSessionId | None = None
    last_received_at: TimePoint | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.vehicle_id, VehicleId):
            object.__setattr__(self, "vehicle_id", VehicleId(self.vehicle_id))
        if not isinstance(self.connected, bool):
            raise TypeError("connected must be bool")
        if self.link_session_id is not None and not isinstance(self.link_session_id, LinkSessionId):
            object.__setattr__(self, "link_session_id", LinkSessionId(self.link_session_id))

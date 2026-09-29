"""Minimal normalized world view for Mission, Action and Planning consumers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from contracts.platform.common import ClockStamp, ResourceVersion, SchemaVersion
from contracts.platform.perception import PerceptionFrameSnapshot, PerceptionHealthSnapshot, PerceptionTarget
from contracts.platform.vehicle_state import VehicleStateSnapshot


@dataclass(frozen=True, slots=True)
class EnvironmentReference:
    version: ResourceVersion
    confirmed: bool
    origin_latitude_deg: float | None
    origin_longitude_deg: float | None
    heading_yaw_rad: float | None


@dataclass(frozen=True, slots=True)
class WorldPose:
    local_north_m: float | None
    local_east_m: float | None
    local_down_m: float | None
    latitude_deg: float | None
    longitude_deg: float | None
    altitude_msl_m: float | None
    yaw_rad: float | None


@dataclass(frozen=True, slots=True)
class WorldVelocity:
    north_mps: float
    east_mps: float
    down_mps: float


@dataclass(frozen=True, slots=True)
class WorldHealth:
    vehicle_usable: bool
    perception_usable: bool
    vehicle_reason: str
    perception_reason: str


@dataclass(frozen=True, slots=True)
class WorldSnapshot:
    schema: SchemaVersion
    sequence: int
    captured_at: ClockStamp
    vehicle: VehicleStateSnapshot | None
    perception: PerceptionFrameSnapshot | None
    perception_health: PerceptionHealthSnapshot | None
    environment_reference: EnvironmentReference | None
    pose: WorldPose | None
    velocity: WorldVelocity | None
    targets: tuple[PerceptionTarget, ...]
    health: WorldHealth

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ValueError("world sequence must be positive")


class WorldSnapshotPort(Protocol):
    def snapshot(self) -> WorldSnapshot | None: ...

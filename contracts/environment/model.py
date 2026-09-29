"""Minimal immutable Environment contract; geometry is supplied by profiles."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from contracts.platform.common import ResourceVersion


@dataclass(frozen=True, slots=True)
class CoordinateReference:
    frame: str
    origin_latitude_deg: float | None = None
    origin_longitude_deg: float | None = None
    heading_yaw_rad: float | None = None
    confirmed: bool = False

    def __post_init__(self) -> None:
        if self.frame not in {"none", "wgs84", "local", "field"}:
            raise ValueError("unsupported coordinate frame")


@dataclass(frozen=True, slots=True)
class NamedLocation:
    """A point in one frame; WGS84 uses x=longitude, y=latitude (degrees)."""

    name: str
    frame: str
    x: float
    y: float
    altitude_m: float | None = None

    def __post_init__(self) -> None:
        if not self.name or self.frame not in {"wgs84", "local", "field"}:
            raise ValueError("invalid named location")
        values = (self.x, self.y) if self.altitude_m is None else (self.x, self.y, self.altitude_m)
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in values):
            raise ValueError("named location coordinates must be finite")
        if self.frame == "wgs84" and not (-180 <= self.x <= 180 and -90 <= self.y <= 90):
            raise ValueError("named location WGS84 coordinate out of range")


@dataclass(frozen=True, slots=True)
class EnvironmentProfile:
    profile_id: str
    name: str
    frame: str

    def __post_init__(self) -> None:
        if not self.profile_id or not self.name or self.frame not in {"none", "wgs84", "local", "field"}:
            raise ValueError("invalid environment profile")


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    profile: EnvironmentProfile
    version: ResourceVersion
    reference: CoordinateReference
    locations: tuple[NamedLocation, ...] = ()

    def __post_init__(self) -> None:
        if self.reference.frame != self.profile.frame:
            raise ValueError("environment frame mismatch")
        names = [location.name for location in self.locations]
        if len(names) != len(set(names)) or any(location.frame != self.profile.frame for location in self.locations):
            raise ValueError("environment locations must be unique and use the profile frame")

    def location(self, name: str) -> NamedLocation:
        for location in self.locations:
            if location.name == name:
                return location
        raise KeyError(name)


class EnvironmentSnapshotPort(Protocol):
    def snapshot(self) -> EnvironmentSnapshot: ...

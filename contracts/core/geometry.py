"""Frame-neutral SI geometry values; frame semantics live in outer contracts."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .primitives import Identifier


class FrameId(Identifier):
    """Extensible frame identity (for example ``map`` or ``base_link``)."""

    __slots__ = ()


class SpatialValue:
    """Marker for values that require a frame when placed in a Stamped value."""

    __slots__ = ()


def _finite_number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")


@dataclass(frozen=True, slots=True)
class Vector3(SpatialValue):
    """Three-dimensional vector in SI units; no frame is implied."""

    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "z"):
            _finite_number(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class Quaternion(SpatialValue):
    """Unit quaternion in fixed x/y/z/w order (absolute norm tolerance 1e-6)."""

    x: float
    y: float
    z: float
    w: float

    def __post_init__(self) -> None:
        for name in ("x", "y", "z", "w"):
            _finite_number(name, getattr(self, name))
        norm = math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z + self.w * self.w)
        if abs(norm - 1.0) > 1e-6:
            raise ValueError("quaternion must be normalized within 1e-6")


@dataclass(frozen=True, slots=True)
class Pose3(SpatialValue):
    position: Vector3
    orientation: Quaternion

    def __post_init__(self) -> None:
        if not isinstance(self.position, Vector3) or not isinstance(self.orientation, Quaternion):
            raise TypeError("Pose3 requires Vector3 position and Quaternion orientation")


@dataclass(frozen=True, slots=True)
class Twist3(SpatialValue):
    linear: Vector3
    angular: Vector3

    def __post_init__(self) -> None:
        if not isinstance(self.linear, Vector3) or not isinstance(self.angular, Vector3):
            raise TypeError("Twist3 requires Vector3 linear and angular values")


@dataclass(frozen=True, slots=True)
class Transform3(SpatialValue):
    """Rigid transform value; direction is supplied by from/to frame identities."""

    translation: Vector3
    rotation: Quaternion

    def __post_init__(self) -> None:
        if not isinstance(self.translation, Vector3) or not isinstance(self.rotation, Quaternion):
            raise TypeError("Transform3 requires Vector3 translation and Quaternion rotation")


@dataclass(frozen=True, slots=True)
class GeoPoint(SpatialValue):
    latitude_deg: float
    longitude_deg: float
    altitude_m: float

    def __post_init__(self) -> None:
        for name in ("latitude_deg", "longitude_deg", "altitude_m"):
            _finite_number(name, getattr(self, name))
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError("latitude_deg must be between -90 and 90")
        if not -180.0 <= self.longitude_deg <= 180.0:
            raise ValueError("longitude_deg must be between -180 and 180")

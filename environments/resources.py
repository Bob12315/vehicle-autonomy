"""Immutable named resources; no navigation, planning or command dependencies."""
from __future__ import annotations
from dataclasses import dataclass, replace
import hashlib
import math
from pathlib import Path
import tomllib
from contracts.core.geometry import FrameId, GeoPoint, Vector3
from contracts.core.primitives import ResourceVersion
from contracts.world.models import ResourceReference


def exact(data, fields, label):
    if type(data) is not dict or set(data) != set(fields):
        raise ValueError(f"invalid {label} fields")
    return data


def text(value):
    if type(value) is not str or not value.strip():
        raise ValueError("nonempty source/name required")
    return value


@dataclass(frozen=True, slots=True)
class NamedPoint:
    name: str
    frame: FrameId
    position: Vector3


@dataclass(frozen=True, slots=True)
class Rectangle:
    name: str
    frame: FrameId
    min_x: float
    max_x: float
    min_y: float
    max_y: float

    def __post_init__(self):
        Vector3(self.min_x, self.max_x, self.min_y)
        Vector3(self.max_y, 0, 0)
        if self.min_x >= self.max_x or self.min_y >= self.max_y:
            raise ValueError("rectangle bounds must be ordered")


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    name: str
    frame: FrameId
    position: Vector3
    environment: ResourceReference


@dataclass(frozen=True, slots=True)
class Environment:
    resource_id: str
    version: ResourceVersion
    frame: FrameId
    origin: GeoPoint
    origin_source: str
    home_name: str
    home_source: str
    geofence: Rectangle
    points: tuple[NamedPoint, ...]
    regions: tuple[Rectangle, ...]
    content_hash: str
    frame_epoch: str = ""

    @property
    def reference(self):
        return ResourceReference(self.resource_id, self.version)

    def bind(self, frame_epoch):
        frame_epoch = text(str(frame_epoch))
        return replace(self, frame_epoch=frame_epoch,
                       version=ResourceVersion(f"{self.content_hash}:{frame_epoch}", 1))

    def resolve(self, name):
        if not self.frame_epoch:
            raise ValueError("environment has no verified session frame binding")
        for point in self.points:
            if point.name == name:
                return ResolvedTarget(point.name, point.frame, point.position, self.reference)
        raise ValueError(f"unknown named point: {name}")

    def home(self):
        if not self.home_source:
            raise ValueError("home source is unknown")
        return self.resolve(self.home_name)

    def validate_origin(self, state):
        if (state is None or state.reported_pose is None or state.global_position is None
                or state.reported_pose.frame_id != self.frame or state.global_position.frame_id != "earth"):
            raise ValueError("reported local/global origin evidence unavailable")
        point = state.global_position.value
        radius = 6378137.0
        north = math.radians(point.latitude_deg - self.origin.latitude_deg) * radius
        east = math.radians(point.longitude_deg - self.origin.longitude_deg) * radius * math.cos(math.radians(self.origin.latitude_deg))
        local = state.reported_pose.value.position
        if math.hypot(east - local.x, north - local.y) > .75:
            raise ValueError("configured and reported origin disagree")

    def check_safety(self, limits):
        fence = self.geofence
        if (fence.min_x, fence.max_x, fence.min_y, fence.max_y) != (
                limits.min_x_m, limits.max_x_m, limits.min_y_m, limits.max_y_m):
            raise ValueError("environment and SafetyPolicy geofences disagree")
        for point in self.points:
            p = point.position
            if not (fence.min_x <= p.x <= fence.max_x and fence.min_y <= p.y <= fence.max_y
                    and limits.min_altitude_m <= p.z <= limits.max_altitude_m):
                raise ValueError("named point outside SafetyPolicy")
        return self

    @classmethod
    def load(cls, path):
        raw = Path(path).read_bytes()
        data = tomllib.loads(raw.decode())
        exact(data, ("environment", "geofence", "points", "regions"), "environment document")
        meta = exact(data["environment"], ("schema", "id", "frame", "units", "origin", "origin_source",
                     "home", "home_source"), "environment metadata")
        if type(meta["schema"]) is not int or meta["schema"] != 1 or meta["units"] != "m":
            raise ValueError("unsupported environment schema/units")
        frame = FrameId(meta["frame"])
        if frame != "odom":
            raise ValueError("first environment requires explicit odom ENU")
        origin = GeoPoint(*meta["origin"])
        for key in ("id", "origin_source", "home", "home_source"):
            text(meta[key])
        points = []
        for point in data["points"]:
            exact(point, ("name", "frame", "position"), "point")
            if FrameId(point["frame"]) != frame:
                raise ValueError("named point frame mismatch")
            points.append(NamedPoint(text(point["name"]), frame, Vector3(*point["position"])))
        names = [p.name for p in points]
        if len(names) != len(set(names)) or meta["home"] not in names:
            raise ValueError("duplicate names or missing home")

        def rectangle(item):
            exact(item, ("name", "frame", "min_x", "max_x", "min_y", "max_y"), "rectangle")
            if FrameId(item["frame"]) != frame:
                raise ValueError("region frame mismatch")
            return Rectangle(text(item["name"]), frame, item["min_x"], item["max_x"], item["min_y"], item["max_y"])
        fence = rectangle(data["geofence"])
        regions = tuple(rectangle(item) for item in data["regions"])
        if len({r.name for r in regions}) != len(regions):
            raise ValueError("duplicate region names")
        for region in regions:
            if not (fence.min_x <= region.min_x < region.max_x <= fence.max_x
                    and fence.min_y <= region.min_y < region.max_y <= fence.max_y):
                raise ValueError("region outside geofence")
        for point in points:
            if not (fence.min_x <= point.position.x <= fence.max_x
                    and fence.min_y <= point.position.y <= fence.max_y):
                raise ValueError("named point outside environment geofence")
        digest = hashlib.sha256(raw).hexdigest()
        return cls(meta["id"], ResourceVersion(digest, 1), frame, origin, meta["origin_source"], meta["home"],
                   meta["home_source"], fence, tuple(points), regions, digest)

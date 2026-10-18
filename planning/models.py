"""Immutable geometric planning values, independent of ROS and vehicle commands."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

from contracts.core.geometry import FrameId
from contracts.core.time import TimePoint
from contracts.world.models import ResourceReference
from mapping.grid import OccupancyGrid


class PlanningError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class Pose2D:
    x: float
    y: float
    yaw: float = 0.0

    def __post_init__(self):
        for value in (self.x, self.y, self.yaw):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("planning pose requires finite SI values")
        if not -math.pi <= self.yaw <= math.pi:
            raise ValueError("planning yaw must be in [-pi, pi]")


@dataclass(frozen=True, slots=True)
class MapContext:
    reference: ResourceReference
    sha256: str
    frame_epoch: str
    grid: OccupancyGrid
    source_kind: str  # recorded_map or live_map
    captured_at: TimePoint | None = None
    max_age_ns: int = 10_000_000_000

    def __post_init__(self):
        if not isinstance(self.reference, ResourceReference) or not isinstance(self.grid, OccupancyGrid):
            raise TypeError("planning requires typed map content and reference")
        if not isinstance(self.frame_epoch, str) or not self.frame_epoch.strip():
            raise ValueError("explicit planning frame epoch required")
        if self.sha256 != hashlib.sha256(self.grid.encoded()).hexdigest():
            raise ValueError("planning map content hash mismatch")
        if self.source_kind not in ("recorded_map", "live_map"):
            raise ValueError("unknown planning map provenance")
        if (self.source_kind == "live_map" and not isinstance(self.captured_at, TimePoint)) or (self.source_kind == "recorded_map" and self.captured_at is not None):
            raise ValueError("only live maps require source capture time")
        if type(self.max_age_ns) is not int or not 0 < self.max_age_ns <= 10_000_000_000:
            raise ValueError("map freshness limit exceeds ten seconds")
        q = self.grid.origin.orientation
        if abs(q.x) > 1e-6 or abs(q.y) > 1e-6 or abs(self.grid.origin.position.z) > 1e-6:
            raise ValueError("planning supports only a planar z=0 occupancy grid")

    def check_fresh(self, now):
        if self.captured_at is not None:
            if self.captured_at.clock_domain_id != now.clock_domain_id:
                raise PlanningError("STALE_MAP", "planning map clock domain mismatch")
            age = now.elapsed_ns_since(self.captured_at)
            if not 0 <= age <= self.max_age_ns:
                raise PlanningError("STALE_MAP", "planning map is future-dated or expired")

    def to_local(self, pose):
        q = self.grid.origin.orientation
        yaw = math.atan2(2*q.w*q.z, 1-2*q.z*q.z)
        x, y = pose.x-self.grid.origin.position.x, pose.y-self.grid.origin.position.y
        angle = math.atan2(math.sin(pose.yaw-yaw), math.cos(pose.yaw-yaw))
        return Pose2D(math.cos(yaw)*x+math.sin(yaw)*y, -math.sin(yaw)*x+math.cos(yaw)*y, angle)

    def to_world(self, pose):
        q = self.grid.origin.orientation
        yaw = math.atan2(2*q.w*q.z, 1-2*q.z*q.z)
        angle = math.atan2(math.sin(pose.yaw+yaw), math.cos(pose.yaw+yaw))
        return Pose2D(self.grid.origin.position.x+math.cos(yaw)*pose.x-math.sin(yaw)*pose.y,
                      self.grid.origin.position.y+math.sin(yaw)*pose.x+math.cos(yaw)*pose.y, angle)


@dataclass(frozen=True, slots=True)
class PlanRequest:
    request_id: str
    context: MapContext
    start: Pose2D
    goal: Pose2D
    created_at: TimePoint
    deadline_ns: int
    clearance_m: float = .55

    def __post_init__(self):
        if not isinstance(self.context, MapContext) or not all(isinstance(p, Pose2D) for p in (self.start, self.goal)):
            raise TypeError("typed map context/start/goal required")
        if not isinstance(self.request_id, str) or not self.request_id or len(self.request_id) > 128:
            raise ValueError("bounded planning request identity required")
        if not isinstance(self.created_at, TimePoint) or type(self.deadline_ns) is not int or not 0 < self.deadline_ns-self.created_at.monotonic_ns <= 20_000_000_000:
            raise ValueError("planning deadline must be within twenty seconds")
        if type(self.clearance_m) not in (int, float) or not math.isfinite(self.clearance_m) or not .1 <= self.clearance_m <= 2:
            raise ValueError("planning clearance must be within 0.1..2 metres")


@dataclass(frozen=True, slots=True)
class PathCandidate:
    request_id: str
    map_sha256: str
    frame_epoch: str
    frame_id: FrameId
    poses: tuple[Pose2D, ...]

    def __post_init__(self):
        object.__setattr__(self, "frame_id", FrameId(self.frame_id))
        if not isinstance(self.poses, tuple) or not 1 <= len(self.poses) <= 8192 or not all(isinstance(p, Pose2D) for p in self.poses):
            raise ValueError("path requires 1..8192 immutable planar poses")


@dataclass(frozen=True, slots=True)
class VerifiedPath:
    request: PlanRequest
    candidate: PathCandidate
    validated_at: TimePoint
    valid_until_ns: int
    length_m: float
    backend: str

    def document(self):
        r, c = self.request, self.request.context
        return {"schema": 1, "request_id": r.request_id, "executable": False,
            "kind": "geometric_path", "backend": self.backend, "frame_id": str(c.grid.frame_id),
            "frame_epoch": c.frame_epoch, "map": {"resource_id": str(c.reference.resource_id),
                "generation": str(c.reference.version.generation_id), "revision": c.reference.version.revision,
                "sha256": c.sha256, "source_kind": c.source_kind,
                "captured_ns": None if c.captured_at is None else c.captured_at.monotonic_ns},
            "clock_domain_id": str(r.created_at.clock_domain_id), "requested_ns": r.created_at.monotonic_ns,
            "validated_ns": self.validated_at.monotonic_ns, "valid_until_ns": self.valid_until_ns,
            "clearance_m": r.clearance_m, "length_m": self.length_m,
            "start": [r.start.x, r.start.y, r.start.yaw], "goal": [r.goal.x, r.goal.y, r.goal.yaw],
            "poses": [[p.x, p.y, p.yaw] for p in self.candidate.poses]}

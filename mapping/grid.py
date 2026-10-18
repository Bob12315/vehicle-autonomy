"""ROS-independent, immutable occupancy grids and content-addressed storage."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from uuid import uuid4

from contracts.core.geometry import FrameId, Pose3, Quaternion, Vector3

MAX_CELLS = 250_000
MAX_GRID_BYTES = 2_000_000


def pose_from_json(value: dict) -> Pose3:
    if type(value) is not dict or set(value) != {"position", "orientation"}:
        raise ValueError("pose requires position and orientation")
    if not isinstance(value["position"], list) or len(value["position"]) != 3:
        raise ValueError("pose requires three position values")
    if not isinstance(value["orientation"], list) or len(value["orientation"]) != 4:
        raise ValueError("pose requires an xyzw quaternion")
    return Pose3(Vector3(*value["position"]), Quaternion(*value["orientation"]))


def pose_to_json(pose: Pose3) -> dict:
    p, q = pose.position, pose.orientation
    return {"position": [p.x, p.y, p.z], "orientation": [q.x, q.y, q.z, q.w]}


@dataclass(frozen=True, slots=True)
class OccupancyGrid:
    frame_id: FrameId
    resolution_m: float
    width: int
    height: int
    origin: Pose3
    cells: tuple[int, ...]

    def __post_init__(self):
        object.__setattr__(self, "frame_id", FrameId(self.frame_id))
        if type(self.resolution_m) not in (int, float) or not math.isfinite(self.resolution_m) or not 0 < self.resolution_m <= 10:
            raise ValueError("map resolution must be finite and positive")
        if any(type(v) is not int or not 0 < v <= 2048 for v in (self.width, self.height)) or self.width * self.height > MAX_CELLS:
            raise ValueError("map dimensions exceed the bounded input")
        if not isinstance(self.origin, Pose3) or not isinstance(self.cells, tuple):
            raise TypeError("map requires typed origin and immutable cells")
        if len(self.cells) != self.width * self.height or any(type(v) is not int or not -1 <= v <= 100 for v in self.cells):
            raise ValueError("map requires row-major occupancy values -1..100")

    def document(self):
        return {"schema": 1, "frame_id": str(self.frame_id), "resolution_m": self.resolution_m,
                "width": self.width, "height": self.height, "origin": pose_to_json(self.origin),
                "cells": self.cells}

    @classmethod
    def from_document(cls, value):
        if type(value) is not dict or set(value) != {"schema", "frame_id", "resolution_m", "width", "height", "origin", "cells"} or type(value["schema"]) is not int or value["schema"] != 1:
            raise ValueError("unsupported map document")
        if type(value["cells"]) is not list:
            raise ValueError("map cells must be an array")
        return cls(value["frame_id"], value["resolution_m"], value["width"], value["height"],
                   pose_from_json(value["origin"]), tuple(value["cells"]))

    def encoded(self):
        return json.dumps(self.document(), separators=(",", ":"), allow_nan=False).encode()


def atomic_json(path: Path, value):
    """Write only into an explicitly selected directory; readers see one cut."""
    payload = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class MapStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def save(self, grid: OccupancyGrid) -> str:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = grid.encoded()
        digest = hashlib.sha256(payload).hexdigest()
        path = self.directory / f"{digest}.json"
        if path.exists():
            self.load(digest)
        else:
            atomic_json(path, grid.document())
        return digest

    def load(self, digest: str) -> OccupancyGrid:
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid map content hash")
        path = self.directory / f"{digest}.json"
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_GRID_BYTES:
                raise ValueError("map input must be a bounded regular file")
            payload = stream.read(MAX_GRID_BYTES + 1)
        if len(payload) > MAX_GRID_BYTES or hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("map content hash mismatch")
        return OccupancyGrid.from_document(json.loads(payload))

    def export_pgm(self, digest: str, directory: Path):
        """Export a standalone ROS-compatible map image and metadata."""
        grid = self.load(digest)
        directory.mkdir(parents=True, exist_ok=True)
        if abs(grid.origin.orientation.x) > 1e-6 or abs(grid.origin.orientation.y) > 1e-6:
            raise ValueError("PGM export requires a planar map origin")
        q = grid.origin.orientation
        yaw = math.atan2(2 * q.w * q.z, 1 - 2 * q.z * q.z)
        # OccupancyGrid starts bottom-left; PGM image rows start at the top.
        pixels = bytes(205 if v == -1 else (0 if v >= 65 else 254 if v <= 19 else 205)
                       for row in reversed(range(grid.height))
                       for v in grid.cells[row * grid.width:(row + 1) * grid.width])
        (directory / "map.pgm").write_bytes(f"P5\n{grid.width} {grid.height}\n255\n".encode() + pixels)
        (directory / "map.yaml").write_text(
            f"image: map.pgm\nmode: trinary\nresolution: {grid.resolution_m}\n"
            f"origin: [{grid.origin.position.x}, {grid.origin.position.y}, {yaw}]\n"
            "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n")

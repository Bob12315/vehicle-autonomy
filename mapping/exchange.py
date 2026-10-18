"""Read-only map input boundary; never imports ROS or a vehicle command port."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import json
import os
from pathlib import Path
import stat
import tomllib

from contracts.core.primitives import ResourceVersion
from contracts.core.time import TimePoint
from contracts.world.models import ResourceReference
from .grid import MapStore, OccupancyGrid, pose_from_json


@dataclass(frozen=True, slots=True)
class MapInput:
    reference: ResourceReference
    captured_at: TimePoint
    grid: OccupancyGrid
    sha256: str


@dataclass(frozen=True, slots=True)
class MappingConfig:
    directory: Path
    clock_domain_id: str
    max_age_ns: int

    @classmethod
    def load(cls, path, clock_domain_id):
        data = tomllib.loads(Path(path).read_text())
        if set(data) != {"schema", "directory", "clock_domain_id", "max_age_ns"} or type(data["schema"]) is not int or data["schema"] != 1:
            raise ValueError("invalid ROS mapping configuration")
        if data["clock_domain_id"] != clock_domain_id:
            raise ValueError("mapping and application clock domains must match")
        if type(data["max_age_ns"]) is not int or not 0 < data["max_age_ns"] <= 10_000_000_000:
            raise ValueError("mapping maximum age must be within ten seconds")
        if type(data["directory"]) is not str or not Path(data["directory"]).is_absolute():
            raise ValueError("mapping directory must be explicit and absolute")
        return cls(Path(data["directory"]), data["clock_domain_id"], data["max_age_ns"])


class MappingInput:
    def __init__(self, config: MappingConfig):
        self.config = config
        self.store = MapStore(config.directory / "maps")
        self.health = {"kind": "ros2_mapping", "valid": False, "error": "no map received"}
        self._key = None
        self._document = None
        self._input = None
        self._frame_epoch = None
        self._source_epoch = None
        self._revision = -1
        self._signature = None
        self._retired_epochs = set()

    def poll(self, now: TimePoint, frame_epoch: str):
        if frame_epoch != self._frame_epoch:
            self._key = self._input = self._document = self._source_epoch = None
            self._revision = -1
            self._signature = None
            self._retired_epochs.clear()
            self._frame_epoch = frame_epoch
        try:
            descriptor = os.open(self.config.directory / "bridge.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
                    raise ValueError("mapping envelope must be a bounded regular file")
                payload = stream.read(16385)
            if len(payload) > 16384:
                raise ValueError("mapping envelope is too large")
            data = json.loads(payload)
            if type(data) is not dict or type(data.get("schema")) is not int or data.get("schema") != 1 or data.get("source") != "ros2.slam_toolbox":
                raise ValueError("unsupported mapping source")
            if data.get("frame_epoch") != frame_epoch or data.get("clock_domain_id") != str(now.clock_domain_id):
                raise ValueError("mapping frame epoch or clock domain mismatch")
            if data.get("status") != "VALID":
                raise ValueError(data.get("error", "mapping source unavailable"))
            item = data["map"]
            capture = item["captured_ns"]
            publication = data["published_ns"]
            if any(type(v) is not int for v in (capture, publication)) or not capture <= publication <= now.monotonic_ns:
                raise ValueError("invalid map capture/publication time")
            if now.monotonic_ns - capture > self.config.max_age_ns:
                raise ValueError("map expired")
            version = ResourceVersion(data["source_epoch"], item["revision"])
            if version.generation_id in self._retired_epochs:
                raise ValueError("retired map source epoch")
            if self._source_epoch == version.generation_id and version.revision < self._revision:
                raise ValueError("map revision regressed")
            key = (frame_epoch, version, item["sha256"])
            if self._key is not None and key[:2] == self._key[:2] and key != self._key:
                raise ValueError("map version reused for changed content")
            for field in ("base_link_in_map", "odom_in_map"):
                pose_from_json(data[field])
            signature = json.dumps({key: data[key] for key in ("map", "base_link_in_map", "odom_in_map")}, sort_keys=True)
            if self._key is not None and key[:2] == self._key[:2] and signature != self._signature:
                raise ValueError("map version reused for changed source facts")
            if self._key != key:
                grid = self.store.load(item["sha256"])
                if grid.frame_id != "map":
                    raise ValueError("only explicitly named map frame accepted")
                if self._source_epoch is not None and self._source_epoch != version.generation_id:
                    if len(self._retired_epochs) >= 128:
                        raise ValueError("too many mapping source restarts in one application epoch")
                    self._retired_epochs.add(self._source_epoch)
                self._input = MapInput(ResourceReference("ros2.slam_toolbox.map", version),
                    TimePoint(capture, now.utc - timedelta(microseconds=(now.monotonic_ns-capture)//1000), now.clock_domain_id), grid, item["sha256"])
                self._key = key
                self._signature = signature
                self._source_epoch, self._revision = version.generation_id, version.revision
                self._document = data
            elif capture != self._input.captured_at.monotonic_ns:
                raise ValueError("map version reused for another capture time")
            # The bridge's localized pose is diagnostic. It does not replace
            # telemetry odometry used by existing Actions and Safety.
            grid = self._input.grid
            self.health = {"kind": "ros2_mapping", "valid": True, "error": None,
                "source_epoch": version.generation_id, "revision": version.revision,
                "frame_epoch": frame_epoch, "age_ns": now.monotonic_ns - capture,
                "captured_ns": capture,
                "sha256": item["sha256"], "frame": str(grid.frame_id),
                "width": grid.width, "height": grid.height, "resolution_m": grid.resolution_m,
                "base_link_in_map": data["base_link_in_map"], "odom_in_map": data["odom_in_map"]}
            return self._input
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            self.health = {"kind": "ros2_mapping", "valid": False, "error": str(exc)}
            return None

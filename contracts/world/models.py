"""Immutable, versioned, traceable world-state publication contracts."""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from typing import Generic, TypeVar

from contracts.core.primitives import (
    ResourceId, ResourceVersion, SchemaVersion, SnapshotId,
    is_deeply_immutable,
)
from contracts.core.quality import ComponentFreshness
from contracts.core.time import TimePoint
from contracts.localization.models import LocalizationEstimate
from contracts.vehicle.models import VehicleStateSnapshot

ObjectT = TypeVar("ObjectT")


@dataclass(frozen=True, slots=True)
class ResourceReference:
    resource_id: ResourceId
    version: ResourceVersion

    def __post_init__(self) -> None:
        if not isinstance(self.resource_id, ResourceId):
            object.__setattr__(self, "resource_id", ResourceId(self.resource_id))
        if not isinstance(self.version, ResourceVersion):
            raise TypeError("resource reference version must be ResourceVersion")


@dataclass(frozen=True, slots=True)
class ResourceDependency:
    resource_type: str
    resource_id: ResourceId
    version: ResourceVersion

    def __post_init__(self) -> None:
        if not isinstance(self.resource_type, str) or not self.resource_type.strip():
            raise ValueError("resource_type must be non-empty")
        if not isinstance(self.resource_id, ResourceId):
            object.__setattr__(self, "resource_id", ResourceId(self.resource_id))
        if not isinstance(self.version, ResourceVersion):
            raise TypeError("resource dependency version must be ResourceVersion")

@dataclass(frozen=True)
class WorldSnapshot(Generic[ObjectT]):
    schema_version: SchemaVersion
    snapshot_id: SnapshotId
    version: ResourceVersion
    published_at: TimePoint
    vehicle: VehicleStateSnapshot | None = None
    localization: LocalizationEstimate | None = None
    objects: tuple[ObjectT, ...] = ()
    map: ResourceReference | None = None
    environment: ResourceReference | None = None
    freshness: tuple[ComponentFreshness, ...] = ()
    dependencies: tuple[ResourceDependency, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, SchemaVersion) or not isinstance(self.version, ResourceVersion):
            raise TypeError("snapshot versions must be validated version values")
        if not isinstance(self.published_at, TimePoint):
            raise TypeError("published_at must be TimePoint")
        if not isinstance(self.snapshot_id, SnapshotId):
            object.__setattr__(self, "snapshot_id", SnapshotId(self.snapshot_id))
        if self.vehicle is not None and not isinstance(self.vehicle, VehicleStateSnapshot):
            raise TypeError("vehicle must be VehicleStateSnapshot")
        if self.localization is not None and not isinstance(self.localization, LocalizationEstimate):
            raise TypeError("localization must be LocalizationEstimate")
        for name in ("map", "environment"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, ResourceReference):
                raise TypeError(f"{name} must be ResourceReference")
        for name in ("objects", "freshness", "dependencies"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} must be a tuple")
        if not all(is_dataclass(value) and is_deeply_immutable(value) for value in self.objects):
            raise TypeError("world objects must be deeply immutable typed values")
        if not all(isinstance(item, ComponentFreshness) for item in self.freshness):
            raise TypeError("freshness entries must be ComponentFreshness")
        if not all(isinstance(item, ResourceDependency) for item in self.dependencies):
            raise TypeError("dependencies must be ResourceDependency")
        freshness_ids = tuple(item.component_id for item in self.freshness)
        if len(freshness_ids) != len(set(freshness_ids)):
            raise ValueError("freshness component IDs must be unique")
        dependency_keys = tuple(
            (item.resource_type, item.resource_id, item.version) for item in self.dependencies
        )
        if len(dependency_keys) != len(set(dependency_keys)):
            raise ValueError("world dependencies must be unique")

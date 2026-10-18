"""Offline World Model: one immutable publication cut from typed state inputs."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from contracts.core.primitives import ResourceVersion, SchemaVersion
from contracts.core.quality import ComponentFreshness, FreshnessState, QualityState
from contracts.core.stamped import Stamped
from contracts.core.time import TimePoint
from contracts.localization.models import LocalizationEstimate
from contracts.sensor import DetectedObject, Observation
from contracts.vehicle.models import VehicleStateSnapshot
from contracts.world.models import ResourceDependency, ResourceReference, WorldSnapshot
from .models import WorldObject


@dataclass(frozen=True, slots=True)
class FreshnessLimits:
    vehicle_ns: int
    localization_ns: int
    objects_ns: int
    map_ns: int = 10_000_000_000

    def __post_init__(self) -> None:
        for name in ("vehicle_ns", "localization_ns", "objects_ns", "map_ns"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive nanosecond duration")


class WorldReader:
    """Read-only view for Mission, Action, Planning, and Guidance consumers."""

    __slots__ = ("_model",)

    def __init__(self, model: WorldModel) -> None:
        self._model = model

    def snapshot(self) -> WorldSnapshot[WorldObject] | None:
        return self._model.snapshot()


class WorldModel:
    def __init__(self, generation_id: str, limits: FreshnessLimits) -> None:
        if not isinstance(limits, FreshnessLimits):
            raise TypeError("limits must be FreshnessLimits")
        self._generation = ResourceVersion(generation_id, 0).generation_id
        self._limits = limits
        self._lock = Lock()
        self._vehicle: VehicleStateSnapshot | None = None
        self._localization: LocalizationEstimate | None = None
        self._observations: dict[tuple[str, str], Observation[DetectedObject]] = {}
        self._producer_sequences: dict[str, int] = {}
        self._last_observations = {}
        self._latest: WorldSnapshot[WorldObject] | None = None
        self._revision = 0
        self._transform_dependency = None
        self._environment = None
        self._map = None
        self._map_captured_at = None

    @property
    def generation_id(self):
        return self._generation

    def update_environment(self, reference: ResourceReference | None):
        if reference is not None and not isinstance(reference, ResourceReference):
            raise TypeError("typed Environment reference required")
        with self._lock:
            self._environment = reference

    def update_map(self, reference: ResourceReference | None, captured_at: TimePoint | None = None):
        """Adopt only a reference; grid content belongs to the mapping resource store."""
        if reference is not None and (not isinstance(reference, ResourceReference) or not isinstance(captured_at, TimePoint)):
            raise TypeError("map reference requires a typed source timestamp")
        with self._lock:
            if reference is not None and self._map is not None:
                old, new = self._map.version, reference.version
                if old.generation_id == new.generation_id and new.revision < old.revision:
                    raise ValueError("map version regressed")
                if reference == self._map and captured_at != self._map_captured_at:
                    raise ValueError("map version reused for another source timestamp")
            self._map = reference
            self._map_captured_at = captured_at if reference is not None else None

    def reader(self) -> WorldReader:
        return WorldReader(self)

    @staticmethod
    def _reject_older(previous: object | None, candidate: object) -> None:
        if previous is None:
            return
        older_version = previous.version
        version = candidate.version
        if version.generation_id == older_version.generation_id and version.revision < older_version.revision:
            raise ValueError("state version regressed")
        if version == older_version and candidate != previous:
            raise ValueError("state version was reused for different data")
        old_time = previous.published_at
        new_time = candidate.published_at
        if old_time.clock_domain_id == new_time.clock_domain_id and new_time < old_time:
            raise ValueError("state publication time regressed")

    def update_vehicle(self, state: VehicleStateSnapshot | None) -> None:
        if state is None:
            with self._lock:
                self._vehicle = None
            return
        if not isinstance(state, VehicleStateSnapshot):
            raise TypeError("vehicle input must be VehicleStateSnapshot or None")
        for stamp in (state.reported_pose, state.reported_twist, state.global_position):
            if (stamp is not None and stamp.captured_at.clock_domain_id == state.published_at.clock_domain_id
                    and stamp.captured_at > state.published_at):
                raise ValueError("vehicle capture cannot follow publication")
        with self._lock:
            self._reject_older(self._vehicle, state)
            self._vehicle = state

    def update_localization(self, estimate: LocalizationEstimate | None) -> None:
        if estimate is None:
            with self._lock:
                self._localization = None
            return
        if not isinstance(estimate, LocalizationEstimate):
            raise TypeError("localization input must be LocalizationEstimate or None")
        for stamp in (estimate.pose, estimate.twist):
            if (stamp is not None and stamp.captured_at.clock_domain_id == estimate.published_at.clock_domain_id
                    and stamp.captured_at > estimate.published_at):
                raise ValueError("localization capture cannot follow publication")
        with self._lock:
            self._reject_older(self._localization, estimate)
            self._localization = estimate

    def update_transform_dependency(self, dependency: ResourceDependency | None) -> None:
        if dependency is not None and (not isinstance(dependency, ResourceDependency)
                                       or dependency.resource_type != "Transform"):
            raise TypeError("Transform dependency required")
        with self._lock:
            self._transform_dependency = dependency

    def ingest_observation(self, observation: Observation[DetectedObject]) -> None:
        if not isinstance(observation, Observation) or not isinstance(observation.data, DetectedObject):
            raise TypeError("World Model currently accepts typed DetectedObject observations")
        if observation.frame_id is None:
            raise ValueError("spatial detection requires frame_id")
        if (observation.captured_at.clock_domain_id == observation.received_at.clock_domain_id
                and observation.received_at < observation.captured_at):
            raise ValueError("received_at cannot precede captured_at")
        producer = str(observation.producer_id)
        with self._lock:
            previous = self._producer_sequences.get(producer, -1)
            if observation.sequence < previous:
                raise ValueError("observation sequence regressed")
            if observation.sequence == previous:
                if observation != self._last_observations[producer]:
                    raise ValueError('observation sequence reused for different data')
                return
            self._last_observations[producer] = observation
            self._producer_sequences[producer] = observation.sequence
            self._observations[(producer, str(observation.data.object_id))] = observation

    @staticmethod
    def _freshness(
        component_id: str, now: TimePoint, limit_ns: int,
        *facts: TimePoint,
    ) -> ComponentFreshness:
        if not facts:
            return ComponentFreshness(component_id, FreshnessState.UNKNOWN, reason="unavailable")
        if any(fact.clock_domain_id != now.clock_domain_id for fact in facts):
            return ComponentFreshness(component_id, FreshnessState.UNKNOWN, reason="clock_domain_mismatch")
        ages = tuple(now.monotonic_ns - fact.monotonic_ns for fact in facts)
        if any(age < 0 for age in ages):
            return ComponentFreshness(component_id, FreshnessState.UNKNOWN, reason="future_timestamp")
        age = max(ages)
        if age > limit_ns:
            return ComponentFreshness(component_id, FreshnessState.STALE, age, "expired")
        return ComponentFreshness(component_id, FreshnessState.FRESH, age)

    @staticmethod
    def _stamps(*values: Stamped[object] | None) -> tuple[TimePoint, ...]:
        return tuple(value.captured_at for value in values if value is not None)

    @staticmethod
    def _usable(quality: QualityState) -> bool:
        return quality in (QualityState.VALID, QualityState.DEGRADED)

    def publish(self, published_at: TimePoint) -> WorldSnapshot[WorldObject]:
        if not isinstance(published_at, TimePoint):
            raise TypeError("published_at must be TimePoint")
        with self._lock:
            if self._latest is not None:
                if published_at.clock_domain_id != self._latest.published_at.clock_domain_id:
                    raise ValueError("world publication clock domain changed")
                if published_at < self._latest.published_at:
                    raise ValueError("world publication time regressed")
            dependencies: list[ResourceDependency] = []
            freshness: list[ComponentFreshness] = []

            vehicle = self._vehicle
            if vehicle is None:
                vehicle_freshness = self._freshness("vehicle", published_at, self._limits.vehicle_ns)
            else:
                vehicle_freshness = self._freshness(
                    "vehicle", published_at, self._limits.vehicle_ns,
                    vehicle.published_at,
                    *self._stamps(vehicle.reported_pose, vehicle.reported_twist, vehicle.global_position),
                )
                dependencies.append(ResourceDependency("VehicleState", vehicle.vehicle_id, vehicle.version))
            freshness.append(vehicle_freshness)
            selected_vehicle = vehicle if (vehicle is not None and vehicle_freshness.state is FreshnessState.FRESH
                                           and self._usable(vehicle.health.quality)) else None

            localization = self._localization
            if localization is None:
                localization_freshness = self._freshness("localization", published_at, self._limits.localization_ns)
            else:
                localization_freshness = self._freshness(
                    "localization", published_at, self._limits.localization_ns,
                    localization.published_at,
                    *self._stamps(localization.pose, localization.twist),
                )
                dependencies.append(ResourceDependency("Localization", localization.producer_id, localization.version))
            freshness.append(localization_freshness)
            selected_localization = localization if (
                localization is not None and localization_freshness.state is FreshnessState.FRESH
                and self._usable(localization.quality)
            ) else None

            if (selected_vehicle is not None and selected_localization is not None
                    and self._transform_dependency is not None
                    and self._transform_dependency.version == selected_vehicle.version):
                dependencies.append(self._transform_dependency)

            objects: list[WorldObject] = []
            object_freshness: list[ComponentFreshness] = []
            for (producer, object_id), observation in sorted(self._observations.items()):
                component_id = f"object:{producer}:{object_id}"
                item_freshness = self._freshness(
                    component_id, published_at, self._limits.objects_ns,
                    observation.captured_at, observation.received_at,
                )
                object_freshness.append(item_freshness)
                dependencies.append(ResourceDependency(
                    "Observation", observation.observation_id,
                    ResourceVersion(observation.observation_id, observation.sequence),
                ))
                if item_freshness.state is FreshnessState.FRESH and self._usable(observation.quality):
                    objects.append(WorldObject(
                        f"{producer}:{object_id}", observation.data.label,
                        Stamped(observation.frame_id, observation.captured_at, observation.data.position),
                        observation.data.confidence, observation.quality,
                        observation.observation_id, observation.producer_id,
                    ))
            if not object_freshness:
                group = ComponentFreshness("objects", FreshnessState.UNKNOWN, reason="unavailable")
            elif any(item.state is FreshnessState.UNKNOWN for item in object_freshness):
                group = ComponentFreshness("objects", FreshnessState.UNKNOWN, reason="some_unknown")
            elif any(item.state is FreshnessState.STALE for item in object_freshness):
                group = ComponentFreshness("objects", FreshnessState.STALE,
                                           max(item.age_ns for item in object_freshness if item.age_ns is not None),
                                           "some_expired")
            else:
                group = ComponentFreshness("objects", FreshnessState.FRESH,
                                           max(item.age_ns for item in object_freshness if item.age_ns is not None))
            freshness.extend((group, *object_freshness))

            if self._environment is not None:
                dependencies.append(ResourceDependency("Environment", self._environment.resource_id,
                                                       self._environment.version))
            map_freshness = self._freshness("map", published_at, self._limits.map_ns,
                *((self._map_captured_at,) if self._map_captured_at is not None else ()))
            freshness.append(map_freshness)
            adopted_map = self._map if map_freshness.state is FreshnessState.FRESH else None
            if self._map is not None:
                dependencies.append(ResourceDependency("Map", self._map.resource_id, self._map.version))
            revision = self._revision + 1
            result = WorldSnapshot(
                SchemaVersion(1, 0), f"{self._generation}:{revision}",
                ResourceVersion(self._generation, revision), published_at,
                selected_vehicle, selected_localization, tuple(objects),
                map=adopted_map, environment=self._environment, freshness=tuple(freshness), dependencies=tuple(dependencies),
            )
            self._revision = revision
            self._latest = result
            return result

    def snapshot(self) -> WorldSnapshot[WorldObject] | None:
        with self._lock:
            return self._latest

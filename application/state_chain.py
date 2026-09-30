"""Offline composition of read-only vehicle state, observations, and World Model."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from contracts.core.time import TimePoint
from contracts.localization.models import LocalizationEstimate
from contracts.sensor import DetectedObject, Observation
from contracts.vehicle.models import VehicleStateSnapshot
from contracts.vehicle.ports import VehicleStatePort
from contracts.world.models import WorldSnapshot
from world_model import WorldModel, WorldObject, WorldReader


class LocalizationEstimator(Protocol):
    def estimate(self, vehicle: VehicleStateSnapshot | None) -> LocalizationEstimate | None:
        """Produce an independent estimate from a state input, if available."""


class OfflineStateChain:
    """Explicit offline wiring; it holds no vehicle command or hardware port."""

    def __init__(
        self, vehicle_state: VehicleStatePort, localization: LocalizationEstimator,
        world_model: WorldModel,
    ) -> None:
        self._vehicle_state = vehicle_state
        self._localization = localization
        self._world_model = world_model

    def world_query(self) -> WorldReader:
        return self._world_model.reader()

    def collect_and_publish(
        self, published_at: TimePoint,
        observations: Iterable[Observation[DetectedObject]] = (),
    ) -> WorldSnapshot[WorldObject]:
        vehicle = self._vehicle_state.snapshot()
        self._world_model.update_vehicle(vehicle)
        estimate = self._localization.estimate(vehicle)
        self._world_model.update_localization(estimate)
        for observation in observations:
            self._world_model.ingest_observation(observation)
        return self._world_model.publish(published_at)

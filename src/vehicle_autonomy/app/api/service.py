"""Application use cases have no direct vehicle command access."""

from __future__ import annotations

from vehicle_autonomy.contracts.core.models import MissionDefinition
from vehicle_autonomy.contracts.vehicle.ports import VehicleCapabilities
from vehicle_autonomy.engine.mission.compiler import MissionValidator


class FrameworkService:
    def __init__(self, missions: MissionValidator) -> None:
        self._missions = missions

    def validate_mission(self, mission: MissionDefinition, vehicle: VehicleCapabilities) -> None:
        self._missions.validate(mission, vehicle)

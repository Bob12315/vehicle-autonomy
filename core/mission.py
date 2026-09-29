"""Validate Mission references before any Action or command is used."""

from __future__ import annotations

from contracts.core.models import MissionDefinition
from contracts.vehicle.ports import VehicleCapabilities

from .action_registry import ActionRegistry


class MissionValidator:
    def __init__(self, actions: ActionRegistry) -> None:
        self._actions = actions

    def validate(self, mission: MissionDefinition, vehicle: VehicleCapabilities) -> None:
        if not mission.name or not mission.steps:
            raise ValueError("Mission requires a name and at least one step")
        seen: set[str] = set()
        for step in mission.steps:
            if not step.step_id or step.step_id in seen:
                raise ValueError(f"Mission step ID is empty or repeated: {step.step_id!r}")
            seen.add(step.step_id)
            registration = self._actions.resolve(step.action)
            missing = registration.definition.required_capabilities - vehicle.names
            if missing:
                raise ValueError(f"Action {step.action} requires capabilities: {sorted(missing)}")

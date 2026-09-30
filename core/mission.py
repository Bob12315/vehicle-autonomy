"""Validate Mission references before any Action or command is used."""

from __future__ import annotations

from contracts.core.models import MissionDefinition
from contracts.decision import MissionPlan, MissionStep
from contracts.vehicle.ports import VehicleCapabilities

from .action_registry import ActionRegistry, RegisteredTypedAction
from dataclasses import dataclass


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

    def compile(self, plan: MissionPlan, vehicle: VehicleCapabilities) -> "CompiledMission":
        if not isinstance(plan, MissionPlan):
            raise TypeError("plan must be MissionPlan")
        if not isinstance(vehicle, VehicleCapabilities):
            raise TypeError("vehicle must be VehicleCapabilities")
        bound = []
        for step in plan.steps:
            registration = self._actions.resolve_typed(step.action)
            registration.spec.validate_parameters(step.parameters)
            missing = registration.spec.required_capabilities - vehicle.names
            if missing:
                raise ValueError(f"Action {step.action} requires capabilities: {sorted(missing)}")
            bound.append(CompiledStep(step, registration))
        return CompiledMission(plan.name, tuple(bound))


@dataclass(frozen=True, slots=True)
class CompiledStep:
    step: MissionStep
    registration: RegisteredTypedAction


@dataclass(frozen=True, slots=True)
class CompiledMission:
    name: str
    steps: tuple[CompiledStep, ...]

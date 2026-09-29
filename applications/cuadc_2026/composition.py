"""CUADC Action composition and capability checks."""

from __future__ import annotations

from contracts.vehicle import VehicleCapabilities, VehiclePlugin
from .actions.definitions import action_definitions
from missions.common.actions.registry import ActionRegistry
from missions.definitions import ActionDefinition
from .profile import CUADC_2026_PROFILE


_ACTION_CAPABILITIES: dict[str, frozenset[str]] = {
    "takeoff": frozenset({"takeoff", "yaw"}),
    "land": frozenset({"land"}),
    "change_speed": frozenset({"speed"}),
    "goto_waypoint": frozenset({"position", "yaw"}),
    "align_descend": frozenset({"body_velocity", "yaw"}),
    "payload_release": frozenset({"payload"}),
}


def compose_actions(
    vehicle: VehiclePlugin[ActionDefinition],
    *,
    core_actions: tuple[ActionDefinition, ...] = (),
    application_actions: tuple[ActionDefinition, ...] | None = None,
) -> tuple[ActionDefinition, ...]:
    if application_actions is None:
        application_actions = tuple(
            item for item in action_definitions() if item.name in CUADC_2026_PROFILE.action_names
        )
    result = (*core_actions, *vehicle.actions, *application_actions)
    names = [item.name for item in result]
    if len(names) != len(set(names)):
        raise ValueError("duplicate Action registration")
    return result


def create_registry(definitions: tuple[ActionDefinition, ...]) -> ActionRegistry:
    registry = ActionRegistry()
    for definition in definitions:
        registry.register(definition.name, definition.factory, definition=definition)
    return registry


def unsupported_action_reason(
    name: str, definitions: tuple[ActionDefinition, ...],
    capabilities: VehicleCapabilities,
) -> str | None:
    if name not in {item.name for item in definitions}:
        return f"unsupported_action:{name}"
    missing = capabilities.missing(_ACTION_CAPABILITIES.get(name, frozenset()))
    if missing:
        return f"unsupported_vehicle_capability:{name}:{','.join(sorted(missing))}"
    return None


def capability_validator(
    definitions: tuple[ActionDefinition, ...], capabilities: VehicleCapabilities,
):
    """Bind one composition's support check for MissionCompiler and run starts."""
    return lambda name: unsupported_action_reason(name, definitions, capabilities)

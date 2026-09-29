"""Multirotor Action contribution; state and command ownership stay in app services."""

from __future__ import annotations

from typing import Callable

from contracts.vehicle import VehicleCapabilities, VehicleHealth
from missions.definitions import ActionDefinition
from .actions.definitions import MULTIROTOR_ACTION_DEFINITIONS
from contracts.platform.vehicle_state import VehicleStateSnapshot

from .capabilities import MULTIROTOR_CAPABILITIES
from .commands.translator import translate_vehicle_effect
from .state.health import health_from_state
from .safety.policy import SafetyPolicy, SafetyPolicyConfig


class MultirotorPlugin:
    def __init__(self, state_snapshot: Callable[[], VehicleStateSnapshot] | None = None) -> None:
        self._state_snapshot = state_snapshot

    @property
    def capabilities(self) -> VehicleCapabilities:
        return MULTIROTOR_CAPABILITIES

    @property
    def actions(self) -> tuple[ActionDefinition, ...]:
        return MULTIROTOR_ACTION_DEFINITIONS

    def health(self) -> VehicleHealth:
        if self._state_snapshot is None:
            return VehicleHealth(False, True, False, "state_port_unbound")
        return health_from_state(self._state_snapshot())

    def translate_effect(self, effect):
        return translate_vehicle_effect(effect)

    def safety_policy(self, config: SafetyPolicyConfig = SafetyPolicyConfig()) -> SafetyPolicy:
        return SafetyPolicy(config)

"""Second Vehicle Plugin proof with explicit no-hardware behavior."""

from __future__ import annotations

from typing import Callable

from contracts.vehicle import VehicleCapabilities, VehicleHealth
from contracts.platform.vehicle_state import VehicleStateSnapshot

from .actions import ROVER_ACTION_DEFINITIONS
from .capabilities import FAKE_ROVER_CAPABILITIES
from .safety import RoverSafetyPolicy


class RoverPlugin:
    def __init__(self, state_snapshot: Callable[[], VehicleStateSnapshot] | None = None) -> None:
        self._state_snapshot = state_snapshot

    @property
    def capabilities(self) -> VehicleCapabilities:
        return FAKE_ROVER_CAPABILITIES

    @property
    def actions(self):
        return ROVER_ACTION_DEFINITIONS

    def health(self) -> VehicleHealth:
        if self._state_snapshot is None:
            return VehicleHealth(False, True, False, "state_port_unbound")
        state = self._state_snapshot()
        return VehicleHealth(state.connected, state.stale,
                             state.control_allowed and state.connected and not state.stale,
                             None if state.connected and not state.stale else "fake_rover_unavailable")

    def translate_effect(self, effect):
        raise TypeError("fake Rover has no vehicle command translator")

    def safety_policy(self) -> RoverSafetyPolicy:
        return RoverSafetyPolicy()

    def unsupported_action_reason(self, name: str) -> str | None:
        if name not in {action.name for action in self.actions}:
            return f"unsupported_action:{name}"
        if name not in self.capabilities.supported:
            return f"unsupported_vehicle_capability:{name}"
        return None

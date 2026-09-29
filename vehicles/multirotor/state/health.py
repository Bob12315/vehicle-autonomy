"""Translate the existing immutable vehicle snapshot into plugin health."""

from contracts.platform.vehicle_state import VehicleStateSnapshot
from contracts.vehicle import VehicleHealth


def health_from_state(state: VehicleStateSnapshot) -> VehicleHealth:
    return VehicleHealth(
        state.connected, state.stale, state.control_allowed,
        None if state.connected and not state.stale else "vehicle_state_unavailable",
    )

"""Vehicle-neutral public contracts and compatibility aliases."""

from contracts.platform.ports import VehicleCommandPort, VehicleStatePort
from contracts.platform.vehicle_state import VehicleStateSnapshot

from .plugin import VehicleCapabilities, VehicleHealth, VehiclePlugin

__all__ = [
    "VehicleCapabilities", "VehicleCommandPort", "VehicleHealth",
    "VehiclePlugin", "VehicleStatePort", "VehicleStateSnapshot",
]

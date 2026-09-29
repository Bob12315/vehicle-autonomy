from dataclasses import FrozenInstanceError

import pytest

from contracts.platform.ports import VehicleCommandPort as ExistingCommandPort
from contracts.platform.ports import VehicleStatePort as ExistingStatePort
from contracts.vehicle import (
    VehicleCapabilities, VehicleCommandPort, VehicleHealth,
    VehiclePlugin, VehicleStatePort,
)
from vehicles.multirotor.plugin import MultirotorPlugin


def test_vehicle_ports_reuse_existing_typed_protocols() -> None:
    assert VehicleStatePort is ExistingStatePort
    assert VehicleCommandPort is ExistingCommandPort
    assert isinstance(MultirotorPlugin(), VehiclePlugin)


def test_vehicle_capabilities_and_health_are_immutable() -> None:
    capabilities = VehicleCapabilities("rover", frozenset({"drive", "reverse"}))
    assert capabilities.missing(frozenset({"drive", "takeoff"})) == frozenset({"takeoff"})
    with pytest.raises(FrozenInstanceError):
        capabilities.vehicle_type = "multirotor"
    with pytest.raises(TypeError):
        VehicleCapabilities("rover", {"drive"})
    health = VehicleHealth(False, True, False, "disconnected")
    with pytest.raises(FrozenInstanceError):
        health.connected = True

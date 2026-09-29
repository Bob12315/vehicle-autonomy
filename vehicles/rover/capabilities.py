from contracts.vehicle import VehicleCapabilities


FAKE_ROVER_CAPABILITIES = VehicleCapabilities(
    "rover", frozenset({"stop", "drive_velocity", "goto_ground"}),
)

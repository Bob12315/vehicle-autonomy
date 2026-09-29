"""Capabilities implemented by the current Action and command adapters."""

from contracts.vehicle import VehicleCapabilities


MULTIROTOR_CAPABILITIES = VehicleCapabilities(
    "multirotor",
    frozenset({
        "takeoff", "land", "hover", "position", "body_velocity", "yaw",
        "speed", "payload", "gimbal",
    }),
)

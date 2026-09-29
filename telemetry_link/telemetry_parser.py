"""Compatibility imports for multirotor MAVLink field mapping."""

from vehicles.multirotor.state.mavlink_fields import (
    control_allowed_for_mode,
    decode_copter_mode,
    global_position_is_valid,
    heartbeat_is_armed,
    parse_gimbal_device_attitude_status,
    parse_mount_status,
    parse_sys_status_values,
    quaternion_to_euler,
)

__all__ = [
    "control_allowed_for_mode", "decode_copter_mode", "global_position_is_valid",
    "heartbeat_is_armed", "parse_gimbal_device_attitude_status",
    "parse_mount_status", "parse_sys_status_values", "quaternion_to_euler",
]

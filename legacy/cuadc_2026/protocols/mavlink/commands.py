"""MAVLink command identity used by ACK correlation."""

from __future__ import annotations

from pymavlink import mavutil


_ACK_COMMANDS = {
    "arm": mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
    "takeoff": mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
    "land": mavutil.mavlink.MAV_CMD_NAV_LAND,
    "condition_yaw": mavutil.mavlink.MAV_CMD_CONDITION_YAW,
    "change_speed": mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED,
    "set_servo": mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
    "gimbal_angle": mavutil.mavlink.MAV_CMD_DO_MOUNT_CONTROL,
    "gimbal_rate": mavutil.mavlink.MAV_CMD_DO_GIMBAL_MANAGER_PITCHYAW,
}


def ack_command_id(vehicle_command_kind: str) -> int | None:
    return _ACK_COMMANDS.get(vehicle_command_kind)

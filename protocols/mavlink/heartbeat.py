"""MAVLink heartbeat identity check, independent of vehicle mode mapping."""

from __future__ import annotations

from pymavlink import mavutil


def is_autopilot_heartbeat(message: object) -> bool:
    autopilot = int(getattr(message, "autopilot", mavutil.mavlink.MAV_AUTOPILOT_INVALID))
    mav_type = int(getattr(message, "type", mavutil.mavlink.MAV_TYPE_GCS))
    return autopilot != mavutil.mavlink.MAV_AUTOPILOT_INVALID and mav_type != mavutil.mavlink.MAV_TYPE_GCS

"""Pymavlink message encoders used by the compatibility sender."""

from __future__ import annotations

from pymavlink import mavutil
from pymavlink.dialects.v20 import ardupilotmega


def send_command_long(master: object, command: int, params: list[float]) -> None:
    if len(params) != 7:
        raise ValueError("COMMAND_LONG requires seven parameters")
    master.mav.command_long_send(
        master.target_system, master.target_component, int(command), 0,
        *(float(value) for value in params),
    )


def send_message_interval_request(master: object, message_name: str, rate_hz: float) -> None:
    message_id = getattr(mavutil.mavlink, f"MAVLINK_MSG_ID_{message_name}", None)
    if message_id is None:
        message_id = getattr(ardupilotmega, f"MAVLINK_MSG_ID_{message_name}", None)
    if message_id is None:
        raise ValueError(f"unknown MAVLink message name: {message_name}")
    interval_us = int(1e6 / rate_hz) if rate_hz > 0 else -1
    send_command_long(master, mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                      [float(message_id), float(interval_us), 0, 0, 0, 0, 0])


def send_set_servo(master: object, channel: int, pwm: int) -> None:
    send_command_long(master, mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
                      [float(channel), float(pwm), 0, 0, 0, 0, 0])

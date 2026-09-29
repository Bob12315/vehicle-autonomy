"""Vehicle command semantics mapped to the characterized MAVLink sender API."""

from __future__ import annotations

import math
import time

from contracts.platform.vehicle_commands import (
    Arm, BodyVelocity, ChangeSpeed, ConditionYaw, GimbalAngle, GimbalRate,
    GlobalPositionTarget, Land, LocalPositionTarget, SetMode, SetServo, StopMotion,
    Takeoff, VehicleCommand,
)
from telemetry_link.frames import BODY_NED, LOCAL_NED
from telemetry_link.models import ActionCommand, ActionType, ControlCommand, ControlType, GimbalRateCommand


def translate_multirotor_mavlink_command(
    payload: VehicleCommand,
) -> ActionCommand | ControlCommand | GimbalRateCommand:
    """Translate typed semantics without owning transport, ACK or send authority."""
    def action(kind: ActionType, params: dict[str, object]) -> ActionCommand:
        return ActionCommand(kind, params, retries_left=0, created_at=time.time())

    if isinstance(payload, SetMode):
        return action(ActionType.SET_MODE, {"mode": payload.mode})
    if isinstance(payload, Arm):
        return action(ActionType.ARM if payload.arm else ActionType.DISARM, {})
    if isinstance(payload, Takeoff):
        return action(ActionType.TAKEOFF, {"altitude_m": payload.altitude_m})
    if isinstance(payload, Land):
        return action(ActionType.LAND, {})
    if isinstance(payload, LocalPositionTarget):
        params = {"x": payload.north_m, "y": payload.east_m, "z": payload.down_m,
                  "frame": LOCAL_NED, "_speed_overrides": []}
        if payload.yaw_rad is not None:
            params["yaw"] = payload.yaw_rad
        return action(ActionType.LOCAL_POSITION, params)
    if isinstance(payload, GlobalPositionTarget):
        params = {"lat": payload.latitude_deg, "lon": payload.longitude_deg,
                  "alt": payload.altitude_m, "frame": 6, "_speed_overrides": []}
        if payload.yaw_rad is not None:
            params["yaw"] = payload.yaw_rad
        return action(ActionType.GLOBAL_GOTO, params)
    if isinstance(payload, BodyVelocity):
        return ControlCommand(ControlType.VELOCITY,
            vx=payload.forward_mps, vy=payload.right_mps, vz=payload.down_mps,
            yaw=payload.yaw_rad, yaw_rate=payload.yaw_rate_rad_s,
            timestamp=time.time(), frame=BODY_NED)
    if isinstance(payload, ConditionYaw):
        return action(ActionType.CONDITION_YAW, {"yaw_deg": payload.yaw_deg,
            "yaw_speed_deg_s": 20.0, "direction": 0, "relative": payload.relative})
    if isinstance(payload, ChangeSpeed):
        return action(ActionType.CHANGE_SPEED, {"speed_mps": payload.speed_mps, "speed_type": 1})
    if isinstance(payload, SetServo):
        return action(ActionType.SET_SERVO, {"channel": payload.channel, "pwm": payload.pwm})
    if isinstance(payload, GimbalAngle):
        return action(ActionType.GIMBAL_ANGLE, {"yaw": math.degrees(payload.yaw_rad),
            "pitch": math.degrees(payload.pitch_rad), "roll": 0.0})
    if isinstance(payload, GimbalRate):
        return GimbalRateCommand(payload.yaw_rate_rad_s, payload.pitch_rate_rad_s,
                                 created_at=time.time())
    if isinstance(payload, StopMotion):
        return ControlCommand(ControlType.STOP, vx=0.0, vy=0.0, vz=0.0,
                              yaw_rate=0.0, timestamp=time.time(), frame=BODY_NED)
    raise ValueError(f"unsupported typed MAVLink payload: {type(payload).__name__}")

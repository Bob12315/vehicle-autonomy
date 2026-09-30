"""ArduCopter Guided command mapping at the Vehicle/Protocol boundary."""

from __future__ import annotations

import math

from contracts.vehicle.command import (
    ArmCommand, DisarmCommand, LandCommand, ModeCommand, PoseTargetCommand,
    StopMotionCommand, TakeoffCommand, TwistTargetCommand, VehicleCommand,
)
from protocols.mavlink.codec import CommandLong, Instruction, LocalSetpoint
from protocols.mavlink import constants as mavlink


class ArduPilotCommandTranslator:
    """Only the documented Copter command subset; unknown frames/modes fail closed."""

    def __init__(self, *, mode_ids: dict[str, int]) -> None:
        if not mode_ids or any(
            not isinstance(name, str) or not name.strip() or isinstance(value, bool)
            or not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF for name, value in mode_ids.items()
        ):
            raise ValueError("explicit ArduCopter mode map required")
        self._mode_ids = dict(mode_ids)

    def mode_id(self, name: str) -> int:
        try:
            return self._mode_ids[name]
        except KeyError as exc:
            raise ValueError("ArduCopter mode is not configured") from exc

    def translate(self, command: VehicleCommand, *, stop_frame: int | None = None) -> Instruction:
        zeros = (0.0,) * 7
        if isinstance(command, ArmCommand):
            return CommandLong(mavlink.CMD_ARM_DISARM, (1.0, *zeros[1:]))
        if isinstance(command, DisarmCommand):
            return CommandLong(mavlink.CMD_ARM_DISARM, zeros)
        if isinstance(command, TakeoffCommand):
            return CommandLong(mavlink.CMD_TAKEOFF, (*zeros[:6], float(command.height_m)))
        if isinstance(command, LandCommand):
            return CommandLong(mavlink.CMD_LAND, zeros)
        if isinstance(command, ModeCommand):
            return CommandLong(mavlink.CMD_SET_MODE, (
                float(mavlink.MODE_CUSTOM_ENABLED),
                float(self.mode_id(command.native_mode)), *zeros[2:],
            ))
        if isinstance(command, PoseTargetCommand):
            if command.frame_id != "odom":
                raise ValueError("Copter pose target requires odom ENU frame")
            q = command.target_pose.orientation
            if abs(q.x) > 1e-6 or abs(q.y) > 1e-6:
                raise ValueError("Copter position target cannot express roll/pitch")
            yaw_enu = 2 * math.atan2(q.z, q.w)
            yaw_ned = math.pi / 2 - yaw_enu
            p = command.target_pose.position
            return LocalSetpoint(
                mavlink.FRAME_LOCAL_NED, 2552, x=p.y, y=p.x, z=-p.z,
                yaw=yaw_ned,
            )
        if isinstance(command, TwistTargetCommand):
            frame = self._frame(command.frame_id)
            angular = command.target_twist.angular
            if abs(angular.x) > 1e-9 or abs(angular.y) > 1e-9:
                raise ValueError("Copter velocity target only supports yaw rate")
            v = command.target_twist.linear
            if frame == mavlink.FRAME_LOCAL_NED:
                vx, vy, vz = v.y, v.x, -v.z
            else:
                vx, vy, vz = v.x, -v.y, -v.z
            return LocalSetpoint(frame, 1479, vx=vx, vy=vy, vz=vz, yaw_rate=-angular.z)
        if isinstance(command, StopMotionCommand):
            if stop_frame not in (mavlink.FRAME_LOCAL_NED, mavlink.FRAME_BODY_NED):
                raise ValueError("stop requires the active stream frame")
            return LocalSetpoint(stop_frame, 1479)
        raise TypeError("unsupported ArduCopter command")

    @staticmethod
    def _frame(frame_id: str) -> int:
        if frame_id == "odom":
            return mavlink.FRAME_LOCAL_NED
        if frame_id == "base_link":
            return mavlink.FRAME_BODY_NED
        raise ValueError("unsupported Copter velocity frame")

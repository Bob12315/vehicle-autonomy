"""ArduRover Guided mapping; all writes still use the common fenced port."""

from __future__ import annotations

import math

from contracts.vehicle.command import (
    ArmCommand, DisarmCommand, LandCommand, ModeCommand, PoseTargetCommand,
    StopMotionCommand, TakeoffCommand, TwistTargetCommand, VehicleCommand,
)
from protocols.mavlink.codec import Instruction, LocalSetpoint
from protocols.mavlink import constants as mavlink
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator


class ArduRoverCommandTranslator(ArduPilotCommandTranslator):
    """Skid-steer body speed/turn rate and local Guided position targets."""

    vehicle_kind = "rover"

    def __init__(self, *, mode_ids: dict[str, int]) -> None:
        if mode_ids != {"HOLD": 4, "GUIDED": 15}:
            raise ValueError("audited ArduRover HOLD/GUIDED mode map required")
        super().__init__(mode_ids=mode_ids)

    def translate(self, command: VehicleCommand, *, stop_frame: int | None = None) -> Instruction:
        if isinstance(command, (TakeoffCommand, LandCommand)):
            raise ValueError("ArduRover has no Takeoff or Land command")
        if isinstance(command, (ArmCommand, DisarmCommand, ModeCommand)):
            return super().translate(command, stop_frame=stop_frame)
        if isinstance(command, PoseTargetCommand):
            if command.frame_id != "odom":
                raise ValueError("Rover Goto requires odom ENU frame")
            p = command.target_pose.position
            if abs(p.z) > .25:
                raise ValueError("Rover Goto must be planar")
            # Rover's position branch ignores yaw; use velocity/yaw-rate ignore bits.
            return LocalSetpoint(mavlink.FRAME_LOCAL_NED, 3576,
                                 x=p.y, y=p.x, z=0.0)
        if isinstance(command, TwistTargetCommand):
            if command.frame_id != "base_link":
                raise ValueError("Rover drive requires base_link FLU frame")
            v = command.target_twist.linear
            w = command.target_twist.angular
            if any(abs(value) > 1e-9 for value in (v.y, v.z, w.x, w.y)):
                raise ValueError("Rover drive supports forward speed and yaw rate only")
            # BODY_NED forward remains +X. FLU positive yaw is NED negative yaw.
            return LocalSetpoint(mavlink.FRAME_BODY_NED, 1479,
                                 vx=v.x, yaw_rate=-w.z)
        if isinstance(command, StopMotionCommand):
            if stop_frame not in (mavlink.FRAME_BODY_NED, mavlink.FRAME_LOCAL_NED):
                raise ValueError("Rover Stop requires an active drive or Goto stream")
            return LocalSetpoint(mavlink.FRAME_BODY_NED, 1479)
        raise TypeError("unsupported ArduRover command")

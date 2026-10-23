"""Native ArduPlane mode control, never Copter zero-velocity/VTOL mapping."""
from vehicle_autonomy.contracts.vehicle.command import ArmCommand, DisarmCommand, ModeCommand, FixedWingTargetCommand
from vehicle_autonomy.vehicles.ardupilot.commands import ArduPilotCommandTranslator

from vehicle_autonomy.vehicles.ardupilot.mavlink.codec import CommandInt

PLANE_MODES = {'MANUAL': 0, 'GUIDED': 15, 'LOITER': 12, 'RTL': 11, 'TAKEOFF': 13, 'AUTOLAND': 26}


class ArduPlaneCommandTranslator(ArduPilotCommandTranslator):
    vehicle_kind = 'plane'

    def __init__(self, *, mode_ids):
        if mode_ids != PLANE_MODES:
            raise ValueError('audited conventional ArduPlane mode map required')
        super().__init__(mode_ids=mode_ids)

    def translate(self, command, *, stop_frame=None):
        if isinstance(command, FixedWingTargetCommand):
            p = command.center
            return CommandInt(192, 0, (-1., 1., 0., 0.),
                round(p.latitude_deg*1e7), round(p.longitude_deg*1e7), p.altitude_m)
        if isinstance(command, (ArmCommand, DisarmCommand, ModeCommand)):
            return super().translate(command, stop_frame=stop_frame)
        raise ValueError('plane_requires_native_modes_not_hover_or_zero_velocity')

"""Rover-native state and its projection to the current generic World input."""

from __future__ import annotations

import math
from dataclasses import dataclass

from contracts.platform.common import ClockStamp, SchemaVersion
from contracts.platform.vehicle_state import VehicleStateSnapshot


@dataclass(frozen=True, slots=True)
class RoverState:
    sequence: int
    captured_at: ClockStamp
    connected: bool
    stale: bool
    control_allowed: bool
    north_m: float
    east_m: float
    heading_rad: float
    forward_mps: float

    def __post_init__(self) -> None:
        if self.sequence < 0 or any(not math.isfinite(value) for value in (
            self.north_m, self.east_m, self.heading_rad, self.forward_mps,
        )):
            raise ValueError("invalid Rover state")


def project_rover_state(state: RoverState) -> VehicleStateSnapshot:
    """Fill unavailable flight/GPS fields explicitly; no hardware inference."""
    return VehicleStateSnapshot(
        schema=SchemaVersion(1, 0), source="sitl", link_session_id="fake-rover",
        sequence=state.sequence, captured_at=state.captured_at,
        connected=state.connected, stale=state.stale,
        control_allowed=state.control_allowed, target_system_id=None,
        target_component_id=None, last_rx_age_s=None,
        armed=False, mode="FAKE_ROVER", landed=None, in_air=None, failsafe=None,
        roll_rad=None, pitch_rad=None, yaw_rad=state.heading_rad,
        yaw_rate_rad_s=None, attitude_age_s=None,
        local_north_m=state.north_m, local_east_m=state.east_m,
        local_down_m=0.0,
        velocity_north_mps=state.forward_mps * math.cos(state.heading_rad),
        velocity_east_mps=state.forward_mps * math.sin(state.heading_rad),
        velocity_down_mps=0.0, local_valid=True, local_age_s=0.0,
        latitude_deg=None, longitude_deg=None, altitude_msl_m=None,
        relative_altitude_m=None, global_valid=False, global_age_s=None,
        global_position_received_at_utc_s=None, gps_fix_type=None,
        satellites_visible=None, gps_eph_m=None, gps_epv_m=None,
        gps_valid=False, battery_voltage_v=None, battery_current_a=None,
        battery_remaining_pct=None, battery_valid=False,
        gimbal_yaw_rad=None, gimbal_pitch_rad=None, gimbal_roll_rad=None,
        gimbal_valid=False, gimbal_age_s=None,
    )

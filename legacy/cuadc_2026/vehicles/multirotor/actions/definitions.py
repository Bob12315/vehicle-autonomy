"""Definitions owned by the multirotor plugin."""
from __future__ import annotations

from missions.action_definition_builder import _definition

from .takeoff import TakeoffAction
from .land import LandAction
from .change_speed import ChangeSpeedAction

_NUMBER = {"type": "number"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_STRING = {"type": "string"}

MULTIROTOR_ACTION_DEFINITIONS = (
    _definition("takeoff", TakeoffAction, "Arm, issue TAKEOFF, then lock the FIELD-centre heading during the climb.",
                {"mode": "GUIDED", "altitude_m": 4.5, "altitude_tolerance_m": 0.35, "require_armed": True, "max_updates": 150, "max_duration_s": 45, "yaw_mode": "field_heading", "takeoff_yaw_deg": None, "yaw_tolerance_deg": 5.0, "yaw_min_hold_updates": 2, "yaw_timeout_s": 12.0, "yaw_speed_deg_s": 20.0, "settle_time_s": 1.0, "priority": 2, "arm_priority": 1, "mode_priority": 2},
                properties={"mode": {"type": "string", "enum": ["GUIDED"]}, "altitude_m": {"type": "number", "exclusiveMinimum": 0}, "target_alt_m": {"type": "number", "exclusiveMinimum": 0}, "altitude_tolerance_m": {"type": "number", "exclusiveMinimum": 0}, "max_updates": {"type": "integer", "minimum": 1}, "max_duration_s": {"type": ["number", "null"], "exclusiveMinimum": 0}, "yaw_mode": {"type": "string", "enum": ["field_heading", "hold"]}, "takeoff_yaw_deg": {"type": ["number", "null"]}, "field_yaw_deg": _NUMBER, "yaw_deg": _NUMBER, "yaw_tolerance_deg": {"type": "number", "exclusiveMinimum": 0, "maximum": 180}, "yaw_min_hold_updates": {"type": "integer", "minimum": 1}, "yaw_timeout_s": {"type": "number", "exclusiveMinimum": 0}, "yaw_speed_deg_s": {"type": "number", "exclusiveMinimum": 0}, "settle_time_s": {"type": "number", "minimum": 0}, "require_armed": _BOOLEAN, "priority": _INTEGER, "arm_priority": _INTEGER, "mode_priority": _INTEGER, "key": _STRING},
                parameter_aliases={"altitude_m": ("target_alt_m",), "field_yaw_deg": ("yaw_deg",)},
                required_inputs=("drone.mode", "drone.armed", "drone.relative_altitude", "field_heading_yaw_rad"), effects=("set_mode", "arm", "takeoff", "condition_yaw")),
    _definition("land", LandAction, "Land through the execution safety gates.",
                {"max_updates": 300, "priority": 2},
                properties={"land_altitude_threshold_m": {"type": "number", "minimum": 0}, "max_updates": {"type": "integer", "minimum": 1}, "priority": _INTEGER, "key": _STRING}, required_inputs=("drone",), effects=("land",)),
    _definition("change_speed", ChangeSpeedAction, "Set the flight-controller speed target.", {"speed_mps": 1.0, "speed_type": "ground", "priority": 4, "key": "drop_speed_1mps"},
                properties={"speed_mps": {"type": "number", "exclusiveMinimum": 0}, "speed_type": {"type": "string", "enum": ["ground", "air", "climb", "descent"]}, "priority": _INTEGER, "key": _STRING}, effects=("change_speed",)),
)

"""Decode protocol fields without owning vehicle state or link lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from pymavlink import mavutil


@dataclass(frozen=True, slots=True)
class LandedStateObservation:
    on_ground: bool
    in_air: bool


def message_type(message: object) -> str:
    return str(message.get_type())


def decode_landed_state(message: object) -> LandedStateObservation:
    value = int(getattr(message, "landed_state", 0))
    return LandedStateObservation(
        value == mavutil.mavlink.MAV_LANDED_STATE_ON_GROUND,
        value == mavutil.mavlink.MAV_LANDED_STATE_IN_AIR,
    )

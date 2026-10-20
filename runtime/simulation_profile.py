"""Strict, vehicle-specific profiles for owned localhost simulation runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:  # Ubuntu 22.04 / Python 3.10, isolated dependency
    import tomli as tomllib

from contracts.core.geometry import FrameId
from core.vehicle_safety import SafetyLimits
from protocols.mavlink.constants import TYPE_GROUND_ROVER, TYPE_QUADROTOR


_MODE_IDS = {
    "copter": {"GUIDED": 4, "LOITER": 5, "RTL": 6, "LAND": 9},
    "rover": {"HOLD": 4, "GUIDED": 15},
}
_MAV_TYPES = {"copter": TYPE_QUADROTOR, "rover": TYPE_GROUND_ROVER}
_SAFETY_KEYS = set(SafetyLimits.__dataclass_fields__)


def _exact(value: object, keys: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"{label} requires exactly {sorted(keys)}")
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class SimulationProfile:
    kind: str
    host: str
    port: int
    vehicle_id: str
    clock_domain_id: str
    mav_type: int
    mode_ids: dict[str, int]
    period_ns: int
    link_timeout_ns: int
    warmup_ns: int
    effect_ttl_ns: int
    lease_ns: int
    safety: SafetyLimits

    @classmethod
    def load(cls, path: str | Path) -> "SimulationProfile":
        document = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        _exact(document, {"vehicle", "modes", "timing", "safety"}, "simulation profile")
        vehicle = _exact(document["vehicle"], {"kind", "host", "port", "vehicle_id", "clock_domain_id"}, "vehicle")
        kind = vehicle["kind"]
        if type(kind) is not str or kind not in _MODE_IDS:
            raise ValueError("unsupported simulation vehicle kind")
        if vehicle["host"] not in ("127.0.0.1", "::1"):
            raise ValueError("simulation host must be numeric loopback")
        for name in ("vehicle_id", "clock_domain_id"):
            if type(vehicle[name]) is not str or not vehicle[name].strip():
                raise ValueError(f"{name} must be nonempty text")
        port = _positive_int(vehicle["port"], "port")
        if port > 65535:
            raise ValueError("port out of range")
        modes = document["modes"]
        if type(modes) is not dict or modes != _MODE_IDS[kind] or any(type(v) is not int for v in modes.values()):
            raise ValueError(f"{kind} mode IDs must match the audited ArduPilot map")
        timing = _exact(document["timing"], {"period_ns", "link_timeout_ns", "warmup_ns", "effect_ttl_ns", "lease_ns"}, "timing")
        for name, value in timing.items():
            _positive_int(value, name)
        safety_data = _exact(document["safety"], _SAFETY_KEYS, "safety")
        for name in ("allowed_frames", "allowed_modes"):
            if type(safety_data[name]) is not list or any(type(v) is not str for v in safety_data[name]):
                raise ValueError(f"{name} must be a text array")
        limits = SafetyLimits(**{
            **safety_data,
            "allowed_frames": frozenset(FrameId(v) for v in safety_data["allowed_frames"]),
            "allowed_modes": frozenset(safety_data["allowed_modes"]),
        })
        if limits.allowed_frames != {FrameId("odom"), FrameId("base_link")}:
            raise ValueError("simulation accepts only odom and base_link frames")
        if limits.allowed_modes != set(modes):
            raise ValueError("safety modes must equal audited vehicle modes")
        if not (timing["period_ns"] < limits.deadman_ns < limits.max_snapshot_age_ns
                and timing["period_ns"] * 2 < limits.max_snapshot_age_ns
                and timing["link_timeout_ns"] <= limits.max_snapshot_age_ns
                and timing["effect_ttl_ns"] <= limits.max_request_ttl_ns
                and timing["lease_ns"] > timing["warmup_ns"]):
            raise ValueError("simulation timing and safety bounds are inconsistent")
        return cls(kind, vehicle["host"], port, vehicle["vehicle_id"], vehicle["clock_domain_id"],
                   _MAV_TYPES[kind], dict(modes), timing["period_ns"], timing["link_timeout_ns"],
                   timing["warmup_ns"], timing["effect_ttl_ns"], timing["lease_ns"], limits)

"""Strict, loopback-only ArduCopter SITL profile."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:  # Ubuntu 22.04 / Python 3.10, isolated dependency
    import tomli as tomllib

from contracts.core.geometry import FrameId
from core.vehicle_safety import SafetyLimits


def _keys(value: dict, expected: set[str], name: str) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{name} requires exactly {sorted(expected)}")


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class SitlProfile:
    host: str
    port: int
    clock_domain_id: str
    vehicle_id: str
    vehicle_type: str
    target_system: int
    target_component: int
    mode: str
    mode_id: int
    period_ns: int
    read_timeout_ns: int
    link_timeout_ns: int
    lease_ns: int
    mission_timeout_ns: int
    arm_ready_wait_ns: int
    safety: SafetyLimits

    @classmethod
    def load(cls, path: str | Path) -> "SitlProfile":
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        _keys(data, {"sitl", "timing", "safety"}, "profile")
        sitl, timing, safety = data["sitl"], data["timing"], data["safety"]
        _keys(sitl, {"host", "port", "clock_domain_id", "vehicle_id", "vehicle_type", "target_system",
                     "target_component", "mode", "mode_id"}, "sitl")
        _keys(timing, {"period_ns", "read_timeout_ns", "link_timeout_ns", "lease_ns",
                       "mission_timeout_ns", "arm_ready_wait_ns"}, "timing")
        _keys(safety, {"max_request_ttl_ns", "max_snapshot_age_ns", "deadman_ns",
                       "min_altitude_m", "max_altitude_m", "max_takeoff_m", "max_linear_mps",
                       "max_angular_rad_s", "allowed_frames", "allowed_modes", "min_x_m",
                       "max_x_m", "min_y_m", "max_y_m"}, "safety")
        if sitl["host"] not in ("127.0.0.1", "::1"):
            raise ValueError("SITL host must be a numeric loopback address")
        if sitl["vehicle_type"] != "ARDUCOPTER_QUADROTOR":
            raise ValueError("P6 requires ArduCopter quadrotor SITL")
        if any(type(sitl[name]) is not str or not sitl[name].strip()
               for name in ("clock_domain_id", "vehicle_id", "mode")):
            raise ValueError("SITL identifiers and mode must be non-empty")
        if type(sitl["mode_id"]) is not int or not 0 <= sitl["mode_id"] <= 0xFFFFFFFF:
            raise ValueError("invalid mode_id")
        if type(safety["allowed_frames"]) is not list or type(safety["allowed_modes"]) is not list:
            raise ValueError("safety allowlists must be arrays")
        if safety["allowed_modes"] != [sitl["mode"]]:
            raise ValueError("only the configured SITL mode may be allowed")
        limits = SafetyLimits(**{**safety,
            "allowed_frames": frozenset(FrameId(value) for value in safety["allowed_frames"]),
            "allowed_modes": frozenset(safety["allowed_modes"]),
        })
        period = _positive(timing["period_ns"], "period_ns")
        read = _positive(timing["read_timeout_ns"], "read_timeout_ns")
        link = _positive(timing["link_timeout_ns"], "link_timeout_ns")
        lease = _positive(timing["lease_ns"], "lease_ns")
        mission = _positive(timing["mission_timeout_ns"], "mission_timeout_ns")
        ready_wait = timing["arm_ready_wait_ns"]
        if type(ready_wait) is not int or ready_wait < 0 or ready_wait >= mission:
            raise ValueError("arm_ready_wait_ns must be nonnegative and below mission timeout")
        if not (read < period < limits.deadman_ns and period * 2 < limits.max_snapshot_age_ns
                and link < lease and 5_000_000_000 <= limits.max_request_ttl_ns < mission < lease):
            raise ValueError("timing, freshness, lease and deadman bounds are inconsistent")
        port = _positive(sitl["port"], "port")
        if port > 65535:
            raise ValueError("invalid TCP port")
        for name in ("target_system", "target_component"):
            if not 1 <= _positive(sitl[name], name) <= 255:
                raise ValueError(f"invalid {name}")
        return cls(sitl["host"], port, sitl["clock_domain_id"], sitl["vehicle_id"], sitl["vehicle_type"],
                   sitl["target_system"], sitl["target_component"], sitl["mode"],
                   sitl["mode_id"], period, read, link, lease, mission, ready_wait, limits)

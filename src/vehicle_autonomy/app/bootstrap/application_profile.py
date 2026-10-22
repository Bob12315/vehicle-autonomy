"""Audited application profile catalog; explicit configs remain loopback-only."""

from vehicle_autonomy._resources import resource_root
from pathlib import Path
from vehicle_autonomy.app.bootstrap.simulation_profile import SimulationProfile

ROOT = resource_root()
PROFILES = {"copter_sim": "copter", "rover_sim": "rover"}


def load_profile(name: str, config: str | None = None) -> SimulationProfile:
    if name not in PROFILES:
        raise ValueError("unknown application profile")
    profile = SimulationProfile.load(config or ROOT / f"simulation/profiles/{PROFILES[name]}.toml")
    if profile.kind != PROFILES[name]:
        raise ValueError("profile vehicle mismatch")
    return profile

"""Audited application profile catalog; explicit configs remain loopback-only."""
from pathlib import Path
from .simulation_profile import SimulationProfile

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {"copter_sim": "copter", "rover_sim": "rover"}


def load_profile(name: str, config: str | None = None) -> SimulationProfile:
    if name not in PROFILES:
        raise ValueError("unknown application profile")
    profile = SimulationProfile.load(config or ROOT / f"simulation/profiles/{PROFILES[name]}.toml")
    if profile.kind != PROFILES[name]:
        raise ValueError("profile vehicle mismatch")
    return profile

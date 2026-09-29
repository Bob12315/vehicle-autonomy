"""Declarative component placement with explicit availability status."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DeploymentMode(str, Enum):
    ONBOARD = "onboard"
    SERVER = "server"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class DeploymentProfile:
    profile_id: str
    mode: DeploymentMode
    placements: tuple[tuple[str, str], ...]
    available: bool = False

    def __post_init__(self) -> None:
        if not self.profile_id or not isinstance(self.mode, DeploymentMode):
            raise ValueError("invalid deployment profile")
        placements = dict(self.placements)
        if len(placements) != len(self.placements):
            raise ValueError("duplicate component placement")
        if set(placements.values()) - {"onboard", "server"}:
            raise ValueError("unsupported deployment node")
        if placements.get("safety") != "onboard" or placements.get("vehicle_link") != "onboard":
            raise ValueError("safety and vehicle link must stay at the vehicle")
        if self.mode is DeploymentMode.ONBOARD and "server" in placements.values():
            raise ValueError("onboard profile cannot place components on a server")
        if self.mode is not DeploymentMode.ONBOARD and placements.get("gateway") != "onboard":
            raise ValueError("remote deployment requires an onboard gateway")
        if self.available and self.mode is not DeploymentMode.ONBOARD:
            raise ValueError("server and hybrid deployment are not available")
        required = {"sensor", "perception", "world_model", "mission",
                    "execution", "safety", "vehicle_link"}
        if required - placements.keys():
            raise ValueError("deployment profile has unplaced components")

    def node_for(self, component: str) -> str:
        try:
            return dict(self.placements)[component]
        except KeyError as exc:
            raise ValueError(f"component has no placement: {component}") from exc


def builtin_profiles() -> tuple[DeploymentProfile, ...]:
    return (
        DeploymentProfile("onboard_rk3588", DeploymentMode.ONBOARD, (
            ("sensor", "onboard"), ("perception", "onboard"),
            ("world_model", "onboard"), ("mission", "onboard"),
            ("execution", "onboard"), ("safety", "onboard"),
            ("vehicle_link", "onboard"),
        ), available=True),
        DeploymentProfile("server", DeploymentMode.SERVER, (
            ("sensor", "onboard"), ("perception", "server"),
            ("gateway", "onboard"),
            ("vehicle_link", "onboard"), ("safety", "onboard"),
            ("world_model", "server"), ("mission", "server"),
            ("execution", "server"),
        )),
        DeploymentProfile("hybrid", DeploymentMode.HYBRID, (
            ("sensor", "onboard"), ("perception", "onboard"),
            ("gateway", "onboard"), ("vehicle_link", "onboard"),
            ("safety", "onboard"), ("execution", "onboard"),
            ("world_model", "onboard"), ("mission", "server"),
        )),
    )


class DeploymentCatalog:
    def __init__(self, profiles: tuple[DeploymentProfile, ...] | None = None) -> None:
        selected = builtin_profiles() if profiles is None else profiles
        self._profiles = {profile.profile_id: profile for profile in selected}
        if not self._profiles or len(self._profiles) != len(selected):
            raise ValueError("deployment profiles must be unique and nonempty")

    def profiles(self) -> tuple[DeploymentProfile, ...]:
        return tuple(self._profiles.values())

    def get(self, profile_id: str) -> DeploymentProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise ValueError(f"unknown deployment profile: {profile_id}") from exc

    def require_available(self, profile_id: str) -> DeploymentProfile:
        profile = self.get(profile_id)
        if not profile.available:
            raise ValueError(f"deployment profile is not available: {profile_id}")
        return profile

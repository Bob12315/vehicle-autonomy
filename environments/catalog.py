from __future__ import annotations

from contracts.environment import (
    CoordinateReference, EnvironmentProfile, EnvironmentSnapshot,
    EnvironmentSnapshotPort,
)
from contracts.platform.common import ResourceVersion


class StaticEnvironment:
    def __init__(self, profile: EnvironmentProfile) -> None:
        self.profile = profile
        self._snapshot = EnvironmentSnapshot(
            profile, ResourceVersion(profile.profile_id, 0), CoordinateReference(profile.frame),
        )

    def snapshot(self) -> EnvironmentSnapshot:
        return self._snapshot


def static_profiles() -> tuple[StaticEnvironment, ...]:
    """Generic profiles contain no invented map, coordinates or locations."""
    return tuple(StaticEnvironment(EnvironmentProfile(profile_id, name, frame)) for profile_id, name, frame in (
        ("none", "No environment", "none"),
        ("generic_gps", "Generic GPS", "wgs84"),
        ("generic_local", "Generic local", "local"),
    ))


class EnvironmentCatalog:
    def __init__(self, providers: tuple[EnvironmentSnapshotPort, ...]) -> None:
        self._providers: dict[str, EnvironmentSnapshotPort] = {}
        for provider in providers:
            profile_id = provider.snapshot().profile.profile_id
            if profile_id in self._providers:
                raise ValueError(f"duplicate environment profile: {profile_id}")
            self._providers[profile_id] = provider

    def profiles(self) -> tuple[EnvironmentProfile, ...]:
        return tuple(provider.snapshot().profile for provider in self._providers.values())

    def snapshot(self, profile_id: str) -> EnvironmentSnapshot:
        try:
            provider = self._providers[profile_id]
        except KeyError as exc:
            raise ValueError(f"unknown environment profile: {profile_id}") from exc
        return provider.snapshot()

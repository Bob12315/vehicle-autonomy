"""Generic application composition metadata; no application-specific rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MissionTemplateRef:
    name: str
    label: str
    relative_path: str

    def __post_init__(self) -> None:
        path = Path(self.relative_path)
        if not self.name or not self.label or not self.relative_path or path.is_absolute() or ".." in path.parts or path.suffix != ".json":
            raise ValueError("invalid Mission template reference")


@dataclass(frozen=True, slots=True)
class ApplicationProfile:
    profile_id: str
    deployment_profile_id: str
    vehicle_type: str
    protocol_id: str
    transport_options: tuple[str, ...]
    sensor_profile_id: str
    perception_profile_id: str
    environment_profile_id: str
    mission_templates: tuple[MissionTemplateRef, ...]
    action_names: frozenset[str]
    legacy_config_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identities = (self.profile_id, self.deployment_profile_id, self.vehicle_type,
                      self.protocol_id, self.sensor_profile_id,
                      self.perception_profile_id, self.environment_profile_id)
        if not all(identities) or not self.transport_options or not self.mission_templates:
            raise ValueError("incomplete application profile")
        names = [template.name for template in self.mission_templates]
        if len(names) != len(set(names)):
            raise ValueError("duplicate Mission template")

    def template(self, name: str) -> MissionTemplateRef:
        for template in self.mission_templates:
            if template.name == name:
                return template
        raise KeyError(name)

    def template_path(self, name: str, root: Path) -> Path:
        return root / self.template(name).relative_path


class ApplicationCatalog:
    def __init__(self, profiles: tuple[ApplicationProfile, ...]) -> None:
        self._profiles = {profile.profile_id: profile for profile in profiles}
        if not self._profiles or len(self._profiles) != len(profiles):
            raise ValueError("application profiles must be unique and nonempty")

    def get(self, profile_id: str) -> ApplicationProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise ValueError(f"unknown application profile: {profile_id}") from exc

    def profiles(self) -> tuple[ApplicationProfile, ...]:
        return tuple(self._profiles.values())

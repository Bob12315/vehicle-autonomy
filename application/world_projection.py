"""Compatibility projection from current Field reference to generic World data."""

from __future__ import annotations

from contracts.core.world import EnvironmentReference
from contracts.environment import EnvironmentSnapshot
from environments.cuadc_2026 import environment_reference_from_field


def environment_reference_from_snapshot(
    environment: EnvironmentSnapshot | None,
) -> EnvironmentReference | None:
    if environment is None:
        return None
    reference = environment.reference
    return EnvironmentReference(
        environment.version, reference.confirmed,
        reference.origin_latitude_deg, reference.origin_longitude_deg,
        reference.heading_yaw_rad,
    )


__all__ = ["environment_reference_from_field", "environment_reference_from_snapshot"]

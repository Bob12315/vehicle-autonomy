"""Compatibility projection from current Field reference to generic World data."""

from __future__ import annotations

from contracts.core.world import EnvironmentReference
from contracts.platform.common import ResourceVersion
from contracts.platform.field import FieldReferenceSnapshot


def environment_reference_from_field(
    field: FieldReferenceSnapshot | None,
) -> EnvironmentReference | None:
    if field is None:
        return None
    return EnvironmentReference(
        ResourceVersion(field.version.generation_id, field.version.revision),
        field.is_confirmed,
        field.origin_lat,
        field.origin_lon,
        field.field_heading_yaw_rad,
    )

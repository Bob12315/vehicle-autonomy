from __future__ import annotations

from typing import Callable

from contracts.core.world import EnvironmentReference
from contracts.environment import CoordinateReference, EnvironmentProfile, EnvironmentSnapshot
from contracts.platform.common import ResourceVersion
from contracts.platform.field import FieldReferenceSnapshot


CUADC_PROFILE = EnvironmentProfile("cuadc_2026", "CUADC 2026", "field")


def environment_reference_from_field(field: FieldReferenceSnapshot | None) -> EnvironmentReference | None:
    """Preserve the P5 World reference projection for legacy consumers."""
    if field is None:
        return None
    return EnvironmentReference(
        ResourceVersion(field.version.generation_id, field.version.revision),
        field.is_confirmed, field.origin_lat, field.origin_lon, field.field_heading_yaw_rad,
    )


class CuadcEnvironment:
    """Read-only boundary; field calibration and competition geometry remain legacy."""

    profile = CUADC_PROFILE

    def __init__(self, field_snapshot: Callable[[], FieldReferenceSnapshot]) -> None:
        self._field_snapshot = field_snapshot

    def snapshot(self) -> EnvironmentSnapshot:
        return environment_snapshot_from_field(self._field_snapshot())


def environment_snapshot_from_field(field: FieldReferenceSnapshot) -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        CUADC_PROFILE,
        ResourceVersion(field.version.generation_id, field.version.revision),
        CoordinateReference(
            "field", field.origin_lat, field.origin_lon,
            field.field_heading_yaw_rad, field.is_confirmed and field.is_frozen,
        ),
    )

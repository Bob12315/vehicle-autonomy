from dataclasses import replace
from datetime import datetime, timezone

import pytest

from contracts.environment import CoordinateReference, EnvironmentProfile, EnvironmentSnapshot, NamedLocation
from contracts.platform.common import ClockStamp, ResourceVersion
from contracts.platform.field import CalibrationSummary, FieldReferenceSnapshot, ReferenceVersion
from environments import EnvironmentCatalog, static_profiles
from environments.cuadc_2026 import CuadcEnvironment
from world_model import WorldModel


def _field_snapshot() -> FieldReferenceSnapshot:
    return FieldReferenceSnapshot(
        ReferenceVersion("field-session", 2), True, True,
        "runtime_current_gps", "runtime_forward_marker",
        40.0, 110.0, 40.001, 110.0, 0.1, 1.0,
        "competition_runtime", "CUADC", CalibrationSummary(),
    )


def test_generic_profiles_and_cuadc_adapter_are_separate() -> None:
    field = _field_snapshot()
    catalog = EnvironmentCatalog((*static_profiles(), CuadcEnvironment(lambda: field)))
    assert {profile.profile_id for profile in catalog.profiles()} == {
        "none", "generic_gps", "generic_local", "cuadc_2026",
    }
    for profile_id in ("none", "generic_gps", "generic_local"):
        assert catalog.snapshot(profile_id).locations == ()
        assert catalog.snapshot(profile_id).reference.confirmed is False
    cuadc = catalog.snapshot("cuadc_2026")
    assert cuadc.reference.origin_latitude_deg == 40.0
    assert cuadc.reference.heading_yaw_rad == 0.1
    assert cuadc.version.revision == 2
    assert cuadc.locations == ()
    with pytest.raises(ValueError, match="unknown environment"):
        catalog.snapshot("unknown")


def test_environment_contract_rejects_mixed_frames_and_duplicate_locations() -> None:
    profile = EnvironmentProfile("test", "Test", "local")
    location = NamedLocation("start", "local", 1.0, 2.0)
    snapshot = EnvironmentSnapshot(profile, ResourceVersion("test", 0),
                                   CoordinateReference("local"), (location,))
    assert snapshot.location("start") == location
    with pytest.raises(ValueError, match="unique"):
        replace(snapshot, locations=(location, location))
    with pytest.raises(ValueError, match="frame mismatch"):
        replace(snapshot, reference=CoordinateReference("wgs84"))
    with pytest.raises(ValueError, match="finite"):
        NamedLocation("bad", "local", float("nan"), 0.0)
    with pytest.raises(ValueError, match="out of range"):
        NamedLocation("bad", "wgs84", 181.0, 0.0)


def test_world_model_keeps_environment_snapshot_for_mission_consumers() -> None:
    environment = EnvironmentCatalog((*static_profiles(),)).snapshot("generic_local")
    world = WorldModel().publish(
        captured_at=ClockStamp(datetime.now(timezone.utc), 100, "test"),
        vehicle=None, perception=None, environment=environment,
    )
    assert world.environment is environment
    assert world.targets == ()

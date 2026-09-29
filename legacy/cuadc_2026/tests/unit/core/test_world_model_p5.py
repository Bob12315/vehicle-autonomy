from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from types import SimpleNamespace
import time

import pytest

from application.core.snapshot_collector import SnapshotCollector, SnapshotCollectorPorts
from application.core.state_store import RuntimeInputStore
from application.runner import SystemRunner
from application.world_projection import environment_reference_from_field
from environments.cuadc_2026 import environment_snapshot_from_field
from contracts.core.common import freeze_json
from contracts.core.input_state import FusionSnapshot, FusionState, FreshnessState
from contracts.core.time import CoreTime
from contracts.platform.common import ClockStamp, SchemaVersion
from contracts.platform.field import CalibrationSummary, FieldReferenceSnapshot, ReferenceVersion
from contracts.platform.perception import PerceptionFrameSnapshot, PerceptionHealthSnapshot, PerceptionTarget
from missions.core.legacy_action_adapter import LegacyActionModuleAdapter
from telemetry_link.ports import VehicleStateAdapter
from world_model import WorldModel


class Port:
    def __init__(self, value):
        self.value = value

    def snapshot(self):
        return self.value


class Fusion:
    def compute(self, _vehicle, _perception, _field):
        return FusionSnapshot(FusionState.UNAVAILABLE, None, None, None, freeze_json({}))


def sample_inputs():
    now = ClockStamp(datetime.now(timezone.utc), 5_000_000_000, "app")
    vehicle = replace(VehicleStateAdapter(lambda: None).snapshot(),
                      captured_at=now, connected=True, stale=False,
                      local_valid=True, local_north_m=1.0, local_east_m=2.0,
                      local_down_m=-3.0, velocity_north_mps=.5,
                      velocity_east_mps=.25, velocity_down_mps=0.0)
    perception = PerceptionFrameSnapshot(
        SchemaVersion(2, 0), "camera", "session", 1, 7, now, "app",
        now.monotonic_ns, 640, 480,
        PerceptionTarget(9, "target", .8, 100.0, 120.0), (), False, 0,
        "ok",
    )
    health = PerceptionHealthSnapshot(True, "session", 0.0, "ok", 1)
    field = FieldReferenceSnapshot(
        ReferenceVersion("field", 2), True, True, "gps", "heading",
        47.0, 106.0, None, None, 0.3, 1.0, "profile", "Profile",
        CalibrationSummary(),
    )
    return now, vehicle, perception, health, field


def test_world_snapshot_combines_normalized_inputs_and_fences_stale_target() -> None:
    now, vehicle, perception, health, field = sample_inputs()
    world_model = WorldModel()
    first = world_model.publish(
        captured_at=now, vehicle=vehicle, perception=perception,
        perception_health=health,
        environment_reference=environment_reference_from_field(field),
    )
    assert first.sequence == 1 and world_model.snapshot() is first
    assert first.pose.local_north_m == 1.0 and first.velocity.north_mps == .5
    assert first.targets[0].track_id == 9
    assert first.environment_reference.version.revision == 2
    with pytest.raises(FrozenInstanceError):
        first.sequence = 3

    stale = world_model.publish(
        captured_at=now, vehicle=vehicle, perception=perception,
        perception_health=replace(health, healthy=False, reason_code="stale"),
    )
    assert stale.sequence == 2
    assert stale.perception is perception
    assert stale.targets == () and not stale.health.perception_usable
    assert stale.health.perception_reason == "stale"

    old_frame = replace(perception, received_at_monotonic_ns=now.monotonic_ns - 3_000_000_000)
    aged = world_model.publish(captured_at=now, vehicle=vehicle,
                               perception=old_frame, perception_health=health)
    assert aged.targets == ()
    assert aged.health.perception_reason == "stale_or_future_perception"


def test_core_input_publishes_world_from_same_cut_and_action_reads_it() -> None:
    now, vehicle, perception, health, field = sample_inputs()
    collector = SnapshotCollector(SnapshotCollectorPorts(
        Port(vehicle), Port(perception), Port(field), Port(None), Fusion(), Port(health),
        Port(environment_snapshot_from_field(field))),
        RuntimeInputStore(),
    )
    cycle = CoreTime(now.monotonic_ns + 100, now.utc, now.clock_domain_id)
    snapshot = collector.capture_and_publish(cycle)
    assert snapshot.world.vehicle is snapshot.vehicle
    assert snapshot.world.perception is snapshot.perception
    assert snapshot.world.environment.profile.profile_id == "cuadc_2026"
    assert snapshot.world.environment_reference.version.revision == field.version.revision
    assert snapshot.world.targets[0].track_id == 9
    context = LegacyActionModuleAdapter._context(SimpleNamespace(snapshot=snapshot))
    assert context["target"]["track_id"] == 9
    assert context["drone"]["local_north_m"] == 1.0


def test_old_perception_is_marked_stale_and_not_exposed_as_target() -> None:
    now, vehicle, perception, health, field = sample_inputs()
    collector = SnapshotCollector(SnapshotCollectorPorts(
        Port(vehicle), Port(perception), Port(field), Port(None), Fusion()),
        RuntimeInputStore(),
    )
    cycle = CoreTime(now.monotonic_ns + 3_000_000_000, now.utc, now.clock_domain_id)
    snapshot = collector.capture_and_publish(cycle)
    assert snapshot.perception_freshness.state is FreshnessState.STALE
    assert snapshot.world.targets == ()
    context = LegacyActionModuleAdapter._context(SimpleNamespace(snapshot=snapshot))
    assert context["target"] == {}


def test_production_action_context_prefers_world_vehicle_and_fences_stale_vision() -> None:
    now, vehicle, perception, health, _field = sample_inputs()
    now = replace(now, monotonic_ns=time.monotonic_ns())
    world = WorldModel().publish(
        captured_at=now, vehicle=replace(vehicle, armed=True), perception=perception,
        perception_health=replace(health, healthy=False, reason_code="stale"),
    )
    runner = object.__new__(SystemRunner)
    runner.state_store = SimpleNamespace(read=lambda: {
        "drone": {"armed": False},
        "perception": {"target_valid": True, "tracking_state": "locked", "ex": 1.0},
        "scene": {"valid": True},
    })
    runner.world_model = SimpleNamespace(snapshot=lambda: world)
    runner.runtime_context_builder = SimpleNamespace(build_action_context=lambda value: value)
    context = runner.action_lab_context()
    assert context["drone"]["armed"] is True
    assert context["perception"]["target_valid"] is False
    assert context["scene"]["valid"] is False
    assert context["world_snapshot"] is world

    runner.world_model = SimpleNamespace(snapshot=lambda: replace(
        world, captured_at=replace(now, monotonic_ns=now.monotonic_ns - 3_000_000_000)))
    expired = runner.action_lab_context()
    assert expired["drone"]["control_allowed"] is False
    assert expired["perception"]["target_valid"] is False

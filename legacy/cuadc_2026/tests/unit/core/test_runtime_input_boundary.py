from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from application.core.snapshot_collector import SnapshotCollector, SnapshotCollectorPorts
from application.core.state_store import RuntimeInputStore
from contracts.core.common import freeze_json
from contracts.core.input_state import FreshnessState, FusionSnapshot, FusionState
from contracts.core.time import CoreTime
from contracts.platform.common import ClockStamp
from telemetry_link.ports import VehicleStateAdapter


class _Port:
    def __init__(self, value):
        self.value = value
        self.reads = 0

    def snapshot(self):
        self.reads += 1
        return self.value


class _Fusion:
    def compute(self, vehicle, perception, field):
        return FusionSnapshot(FusionState.UNAVAILABLE, None, None, None, freeze_json({}))


def test_runtime_input_is_one_immutable_versioned_cut() -> None:
    vehicle = VehicleStateAdapter(lambda: None).snapshot()
    now = CoreTime(vehicle.captured_at.monotonic_ns + 100, datetime.now(timezone.utc), "app")
    ports = [_Port(vehicle), _Port(None), _Port(None), _Port(None)]
    store = RuntimeInputStore()
    collector = SnapshotCollector(SnapshotCollectorPorts(*ports, _Fusion()), store)

    first = collector.capture_and_publish(now)
    assert store.current() is first
    assert first.vehicle is vehicle
    assert first.vehicle_freshness.age_ns == 100
    assert [port.reads for port in ports] == [1, 1, 1, 1]
    assert first.send_gate.enabled is False
    with pytest.raises(FrozenInstanceError):
        first.vehicle = None
    with pytest.raises(TypeError):
        replace(first, world={"live": [1]})

    second = collector.capture_and_publish(now)
    assert second.ref.publication_version.revision == first.ref.publication_version.revision + 1
    assert first.ref != second.ref


def test_vehicle_clock_domain_mismatch_is_invalid() -> None:
    vehicle = VehicleStateAdapter(lambda: None).snapshot()
    mismatched = replace(vehicle, captured_at=ClockStamp(
        vehicle.captured_at.utc, vehicle.captured_at.monotonic_ns, "other"
    ))
    now = CoreTime(vehicle.captured_at.monotonic_ns + 100, datetime.now(timezone.utc), "app")
    collector = SnapshotCollector(SnapshotCollectorPorts(
        _Port(mismatched), _Port(None), _Port(None), _Port(None), _Fusion()
    ), RuntimeInputStore())
    snapshot = collector.capture_and_publish(now)
    assert snapshot.vehicle_freshness.state is FreshnessState.INVALID
    assert snapshot.vehicle_freshness.reason_code == "clock_domain_mismatch"

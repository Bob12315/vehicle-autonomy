"""A second Vehicle composes through the existing Core without a real writer."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from application.core.runtime import build_core_runtime
from contracts.core.common import IdempotencyKey, RequestId, freeze_json
from contracts.core.action import ActionState
from contracts.core.effects import BodyVelocityTarget, Takeoff
from contracts.core.input_state import FusionSnapshot, FusionState
from contracts.core.run import (
    ActionRunTarget, RunAuthorizationRequest, StartRunCommand,
)
from contracts.core.run_io import ResultProjectionPolicy, RunRecordingPolicy
from contracts.core.time import CoreTime, ManualCoreClock
from contracts.platform.common import ClockStamp, LinkSessionId, SchemaVersion
from contracts.platform.vehicle_commands import (
    AckPolicy, BarrierDisposition, CancelRequest, CancelScope,
    CompletionPolicy, StopMotion, SubmissionState, VehicleCommandEnvelope,
)
from contracts.vehicle import VehiclePlugin
from missions.core.mission_compiler import MissionCompiler
from missions.core.production_catalog import create_production_catalog
from vehicles.rover import RoverPlugin
from vehicles.rover.fake_adapter import FakeRoverAdapter
from vehicles.rover.safety import RoverSafetyConfig
from vehicles.rover.state import RoverState
from world_model import WorldModel


class NullSnapshot:
    def snapshot(self):
        return None


class Fusion:
    def compute(self, vehicle, perception, field):
        return FusionSnapshot(FusionState.UNAVAILABLE, None, None, None, freeze_json({}))


class NoVisionCommands:
    def submit(self, command):
        raise AssertionError("fake Rover has no vision command")

    def status(self, command_id):
        raise KeyError(command_id)


def _rover():
    now = CoreTime(1_000_000_000, datetime(2026, 1, 1, tzinfo=timezone.utc), "fake-rover")
    state = RoverState(1, ClockStamp(now.utc, now.monotonic_ns, now.clock_domain_id),
                       True, False, True, 3.0, 4.0, 0.0, 0.5)
    adapter = FakeRoverAdapter(state)
    plugin = RoverPlugin(adapter.snapshot)
    return now, adapter, plugin


def test_fake_rover_projects_state_into_existing_world_model() -> None:
    now, adapter, plugin = _rover()
    assert isinstance(plugin, VehiclePlugin)
    assert plugin.health().control_allowed is True
    vehicle = adapter.snapshot()
    world = WorldModel().publish(
        captured_at=vehicle.captured_at, vehicle=vehicle, perception=None,
    )
    assert world.health.vehicle_usable is True
    assert world.pose.local_north_m == 3.0
    assert world.pose.local_east_m == 4.0
    assert world.velocity.north_mps == 0.5
    assert world.pose.latitude_deg is None
    with pytest.raises(ValueError, match="invalid Rover state"):
        RoverState(0, vehicle.captured_at, True, False, True,
                   float("nan"), 0.0, 0.0, 0.0)


def test_fake_rover_actions_compile_and_fail_closed_in_unmodified_core() -> None:
    now, adapter, plugin = _rover()
    catalog = create_production_catalog(plugin.actions)
    assert {item.definition.name for item in catalog.all()} == {
        "stop", "drive_velocity", "goto_ground",
    }
    compiler = MissionCompiler(catalog.definitions,
                               unsupported_action_reason=plugin.unsupported_action_reason)
    mission = compiler.compile({"version": 2, "name": "fake_rover", "steps": [
        {"name": "drive_velocity", "params": {"forward_mps": 0.5,
                                                "yaw_rate_rad_s": 0.0}},
        {"name": "stop", "params": {}},
    ]})
    assert len(mission.steps) == 2
    with pytest.raises(ValueError, match="unknown Action: takeoff"):
        compiler.compile({"version": 2, "name": "invalid", "steps": [
            {"name": "takeoff", "params": {"altitude_m": 2.0}},
        ]})

    clock = ManualCoreClock(now)
    runtime = build_core_runtime(
        source="sitl", link_session_id=LinkSessionId("fake-rover"),
        vehicle_state=adapter, perception=NullSnapshot(),
        field_reference=NullSnapshot(), fusion=Fusion(),
        vehicle_commands=adapter, vision_commands=NoVisionCommands(),
        clock=clock, action_catalog=catalog,
        vehicle_translate=plugin.translate_effect, safety=plugin.safety_policy(),
    )
    first = runtime.scheduler.run_one_cycle_for_test()
    assert runtime.send_state.snapshot().enabled is False
    assert first.input_snapshot.world.pose.local_north_m == 3.0
    registration = next(item for item in catalog.all()
                        if item.definition.name == "drive_velocity")
    receipt = runtime.coordinator.request_start(StartRunCommand(
        RequestId("request"), IdempotencyKey("key"),
        ActionRunTarget(registration.definition.contract_ref,
                        freeze_json({"forward_mps": 0.5, "yaw_rate_rad_s": 0.0})),
        "sitl", RunAuthorizationRequest("operator", "request", True),
        RunRecordingPolicy(), ResultProjectionPolicy(), now,
    ))
    assert receipt.disposition.value == "accepted"
    clock.advance_ns(50_000_000)
    started = runtime.scheduler.run_one_cycle_for_test()
    assert started.run is not None
    clock.advance_ns(50_000_000)
    stopped = runtime.scheduler.run_one_cycle_for_test()
    assert stopped.run is not None
    assert stopped.run.action.state is ActionState.FAILED
    assert stopped.run.action.reason_code == "fake_rover_no_control_backend"
    assert adapter._rejected == {}


def test_fake_rover_safety_and_command_port_never_claim_physical_send() -> None:
    _now, adapter, plugin = _rover()
    policy = plugin.safety_policy()
    assert policy.evaluate(BodyVelocityTarget(0.5, 0.0, 0.0),
                           SimpleNamespace(send_enabled=False)).reason_code == "send_disabled"
    assert policy.evaluate(Takeoff(2.0),
                           SimpleNamespace(send_enabled=True)).reason_code == "fake_rover_no_control_backend"
    with pytest.raises(ValueError, match="invalid Rover safety"):
        RoverSafetyConfig(max_forward_mps=0.0)
    with pytest.raises(TypeError, match="no vehicle command translator"):
        plugin.translate_effect(BodyVelocityTarget(0.5, 0.0, 0.0))

    command = VehicleCommandEnvelope(
        SchemaVersion(2, 0), "command", "run", "lease", 0, 0,
        "sitl", "fake-rover", 0, 100, 5, "key", AckPolicy.DISABLED,
        CompletionPolicy.TRANSPORT_ONLY, 0, StopMotion(),
    )
    submission = adapter.submit(command)
    assert submission.submission_state is SubmissionState.REJECTED
    assert adapter.status("command").transport_state.value == "NOT_ATTEMPTED"
    cancel = adapter.cancel(CancelRequest.create(
        CancelScope.COMMAND, command_id="command", reason="test",
        emit_stop_barrier=True, now_ns=1,
    ))
    assert cancel.barrier_disposition is BarrierDisposition.STOP_UNDELIVERABLE

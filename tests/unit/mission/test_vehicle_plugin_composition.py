from types import SimpleNamespace
from pathlib import Path

import pytest

from app.config import build_arg_parser, load_app_config
from application.runner import SystemRunner
from application.vehicle_composition import (
    capability_validator, compose_actions, create_registry, unsupported_action_reason,
)
from contracts.vehicle import VehicleCapabilities
from contracts.core.effects import Takeoff as TakeoffEffect
from contracts.platform.vehicle_commands import Takeoff as TakeoffCommand
from applications.cuadc_2026.actions.definitions import action_definitions
from missions.engine import MissionActionStep
from missions.core.mission_compiler import MissionCompiler
from missions.core.production_catalog import create_production_catalog
from vehicles.multirotor.plugin import MultirotorPlugin


def _runner():
    config = load_app_config(build_arg_parser().parse_args(["--no-yolo-udp", "--no-ui"]))
    return SystemRunner(config)


def test_multirotor_plugin_owns_only_vehicle_actions_and_preserves_registry() -> None:
    plugin = MultirotorPlugin()
    assert {item.name for item in plugin.actions} == {"takeoff", "land", "change_speed"}
    assert "applications.cuadc_2026.actions.definitions" not in (
        Path(__file__).resolve().parents[3] / "vehicles/multirotor/plugin.py"
    ).read_text()
    definitions = compose_actions(plugin)
    assert {item.name for item in definitions} == {item.name for item in action_definitions()}
    registry = create_registry(definitions)
    assert registry.get("takeoff").__module__ == "vehicles.multirotor.actions.takeoff"
    assert registry.get("goto_waypoint").__module__ == "applications.cuadc_2026.actions.goto_waypoint"
    assert set(registry.list()) == {item.name for item in definitions}
    assert isinstance(plugin.translate_effect(TakeoffEffect(3.0)), TakeoffCommand)
    with pytest.raises(ValueError, match="duplicate"):
        compose_actions(plugin, core_actions=plugin.actions)


def test_unsupported_vehicle_action_fails_before_mission_authorization_or_execution() -> None:
    runner = _runner()
    runner.vehicle_plugin = SimpleNamespace(capabilities=VehicleCapabilities("rover", frozenset({"position"})))
    runner.configure_action_mission([MissionActionStep("takeoff", {"altitude_m": 3.0})])
    status = runner.action_mission_start(authorize=True, target_source="sitl")
    assert status["failed"] is True
    assert status["reason"] == "unsupported_vehicle_capability:takeoff:takeoff,yaw"
    assert runner.action_runtime.dispatcher.authorization is None
    assert runner.action_runtime.action_name is None

    direct = runner.action_lab_start_action("takeoff", {"altitude_m": 3.0}, authorize=True)
    assert direct.failed is True
    assert direct.reason == status["reason"]
    assert runner.action_runtime.action_name is None


def test_candidate_mission_compiler_rejects_unsupported_vehicle_action() -> None:
    definitions = compose_actions(MultirotorPlugin())
    catalog = create_production_catalog(definitions)
    validator = capability_validator(
        definitions, VehicleCapabilities("rover", frozenset({"position"}))
    )
    compiler = MissionCompiler(catalog.definitions, unsupported_action_reason=validator)
    with pytest.raises(ValueError, match="unsupported_vehicle_capability:takeoff"):
        compiler.compile({"version": 2, "name": "invalid_rover_mission", "steps": [
            {"label": "rise", "name": "takeoff", "params": {"altitude_m": 3.0}},
        ]})


def test_plugin_without_takeoff_rejects_unknown_action_before_execution() -> None:
    rover = SimpleNamespace(actions=(), capabilities=VehicleCapabilities("rover", frozenset({"drive"})))
    definitions = compose_actions(rover)
    assert unsupported_action_reason("takeoff", definitions, rover.capabilities) == "unsupported_action:takeoff"

"""Behavioral checks for the clean, hardware disconnected framework."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
import unittest

from vehicle_autonomy.app.api.service import FrameworkService
from vehicle_autonomy.contracts.core.models import ActionDefinition, ActionStep, Effect, MissionDefinition
from vehicle_autonomy.contracts.core.primitives import ResourceVersion, SchemaVersion
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.vehicle.ports import VehicleCapabilities
from vehicle_autonomy.contracts.world.models import WorldSnapshot
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.control.execution import ExecutionGateway, SendGate
from vehicle_autonomy.engine.mission.compiler import MissionValidator


class _Action:
    def plan(self, snapshot, parameters):
        return (Effect("sample"),)


class _Commands:
    def __init__(self):
        self.submitted = []

    def submit(self, effect):
        self.submitted.append(effect)


class _Safety:
    def __init__(self, allow):
        self.allow = allow
        self.calls = 0

    def evaluate(self, effect, snapshot):
        self.calls += 1
        return self.allow


class FrameworkTests(unittest.TestCase):
    def test_mission_requires_registered_action_and_capability(self):
        registry = ActionRegistry()
        registry.register(ActionDefinition("observe", frozenset({"camera"})), _Action())
        service = FrameworkService(MissionValidator(registry))
        mission = MissionDefinition("survey", (ActionStep("one", "observe"),))
        with self.assertRaisesRegex(ValueError, "camera"):
            service.validate_mission(mission, VehicleCapabilities())
        service.validate_mission(mission, VehicleCapabilities(frozenset({"camera"})))
        with self.assertRaisesRegex(ValueError, "not registered"):
            service.validate_mission(
                MissionDefinition("other", (ActionStep("one", "unknown"),)),
                VehicleCapabilities(),
            )

    def test_duplicate_actions_and_step_ids_are_rejected(self):
        registry = ActionRegistry()
        registry.register(ActionDefinition("observe"), _Action())
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(ActionDefinition("observe"), _Action())
        with self.assertRaisesRegex(ValueError, "repeated"):
            MissionValidator(registry).validate(
                MissionDefinition("survey", (ActionStep("one", "observe"), ActionStep("one", "observe"))),
                VehicleCapabilities(),
            )

    def test_execution_requires_both_gates_and_explicit_safety_allow(self):
        commands = _Commands()
        safety = _Safety(True)
        execution = ExecutionGateway(commands, safety)
        effect = Effect("sample")
        snapshot = WorldSnapshot(SchemaVersion(1, 0), "snapshot-1", ResourceVersion("world", 1), TimePoint(1, datetime(2026, 1, 1, tzinfo=timezone.utc), "test"))
        self.assertFalse(execution.submit(effect, snapshot))
        self.assertFalse(execution.submit(effect, snapshot, SendGate(system_enabled=True)))
        self.assertFalse(execution.submit(effect, snapshot, SendGate(action_enabled=True)))
        self.assertEqual(commands.submitted, [])
        self.assertEqual(safety.calls, 0)
        safety.allow = False
        self.assertFalse(execution.submit(effect, snapshot, SendGate(True, True)))
        self.assertEqual(commands.submitted, [])
        safety.allow = True
        self.assertTrue(execution.submit(effect, snapshot, SendGate(True, True)))
        self.assertEqual(commands.submitted, [effect])

    def test_new_root_does_not_import_archived_implementation(self):
        root = Path(__file__).resolve().parents[1]
        root = root / "src" / "vehicle_autonomy"
        for directory in ("contracts", "engine", "actions", "vehicles", "world", "autonomy", "app"):
            self.assertTrue((root / directory).is_dir())
            for path in (root / directory).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.append(node.module)
                self.assertFalse(any(name.split(".")[0] in {"legacy", "telemetry_link"} for name in imports), str(path))
                if not path.is_relative_to(root / "vehicles" / "ardupilot" / "mavlink"):
                    self.assertFalse(any(name.split(".")[0] == "pymavlink" for name in imports), str(path))
                if directory in {"contracts", "engine"}:
                    self.assertFalse(any(name.startswith("vehicle_autonomy.vehicles.ardupilot.mavlink") for name in imports), str(path))


if __name__ == "__main__":
    unittest.main()

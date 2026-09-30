"""Typed Mission compilation and offline Action lifecycle behavior."""

from __future__ import annotations

import ast
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
import unittest

from contracts.core.geometry import Twist3, Vector3
from contracts.core.primitives import ResourceVersion, SchemaVersion, thaw_json
from contracts.core.time import TimePoint
from contracts.decision import (
    ActionDecision, ActionOutcome, ActionSpec, ExitDecision, ExitReason,
    FailurePolicy, MissionPlan, MissionStep,
)
from contracts.effects import StopMotionEffect, TwistTargetEffect
from contracts.vehicle.ports import VehicleCapabilities
from contracts.world.models import WorldSnapshot
from core.action_registry import ActionRegistry
from core.actions import WORLD_SUMMARY_SPEC, WorldSummaryAction, WorldSummaryParameters
from core.mission import MissionValidator
from core.mission_runtime import MissionRuntime, RunStatus


def at(ns: int, domain: str = "clock") -> TimePoint:
    return TimePoint(ns, datetime(2026, 1, 1, tzinfo=timezone.utc), domain)


def world(ns: int = 10) -> WorldSnapshot:
    return WorldSnapshot(SchemaVersion(1, 0), "world-1", ResourceVersion("world", 1), at(ns))


class Reader:
    def __init__(self, value):
        self.value = value

    def snapshot(self):
        return self.value


@dataclass(frozen=True, slots=True)
class PulseParameters:
    stream_id: str


class ScriptedInstance:
    def __init__(self, decisions, exits):
        self.decisions = list(decisions)
        self.exits = list(exits)
        self.exit_reasons = []
        self.tick_calls = 0

    def tick(self, snapshot):
        self.tick_calls += 1
        return self.decisions.pop(0)

    def exit(self, snapshot, reason):
        self.exit_reasons.append(reason)
        return self.exits.pop(0)


class ScriptedFactory:
    def __init__(self, instances):
        self.instances = list(instances)
        self.starts = 0

    def start(self, parameters, snapshot):
        self.starts += 1
        return self.instances.pop(0)


class FlakyExitInstance(ScriptedInstance):
    def __init__(self):
        super().__init__([ActionDecision(ActionOutcome.SUCCEEDED)], [ExitDecision(True)])
        self.fail_once = True

    def exit(self, snapshot, reason):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("exit unavailable")
        return super().exit(snapshot, reason)


class P3DecisionTests(unittest.TestCase):
    def test_summary_action_compiles_and_completes_after_exit(self):
        registry = ActionRegistry()
        registry.register_typed(WORLD_SUMMARY_SPEC, WorldSummaryAction())
        plan = MissionPlan("inspect", (MissionStep("summary", "world.summary", WorldSummaryParameters()),))
        compiled = MissionValidator(registry).compile(plan, VehicleCapabilities())
        runtime = MissionRuntime(compiled, Reader(world()), "run-1", max_snapshot_age_ns=100)
        first = runtime.tick(at(11))
        self.assertEqual(first.status, RunStatus.EXITING)
        self.assertEqual(first.effects, ())
        second = runtime.tick(at(12))
        self.assertEqual(second.status, RunStatus.SUCCEEDED)
        self.assertEqual(thaw_json(second.results[0].result)["snapshot_id"], "world-1")
        self.assertEqual(runtime.tick(at(13)).status, RunStatus.SUCCEEDED)

    def test_compile_rejects_unregistered_capability_schema_and_duplicate(self):
        registry = ActionRegistry()
        spec = ActionSpec("pulse", PulseParameters, frozenset({"motion"}), (TwistTargetEffect, StopMotionEffect))
        registry.register_typed(spec, ScriptedFactory([]))
        compiler = MissionValidator(registry)
        with self.assertRaisesRegex(ValueError, "capabilities"):
            compiler.compile(MissionPlan("m", (MissionStep("s", "pulse", PulseParameters("x")),)), VehicleCapabilities())
        with self.assertRaisesRegex(TypeError, "parameters"):
            compiler.compile(MissionPlan("m", (MissionStep("s", "pulse", WorldSummaryParameters()),)),
                             VehicleCapabilities(frozenset({"motion"})))
        with self.assertRaisesRegex(TypeError, "stream_id"):
            compiler.compile(MissionPlan("m", (MissionStep("s", "pulse", PulseParameters(42)),)),
                             VehicleCapabilities(frozenset({"motion"})))
        with self.assertRaisesRegex(ValueError, "not registered"):
            compiler.compile(MissionPlan("m", (MissionStep("s", "missing", PulseParameters("x")),)),
                             VehicleCapabilities(frozenset({"motion"})))
        with self.assertRaisesRegex(ValueError, "unique"):
            MissionPlan("m", (MissionStep("s", "pulse", PulseParameters("x")),
                              MissionStep("s", "pulse", PulseParameters("x"))))
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register_typed(spec, ScriptedFactory([]))

    def test_failure_retries_only_after_exit_barrier(self):
        first = ScriptedInstance([ActionDecision(ActionOutcome.FAILED, error="temporary")],
                                 [ExitDecision(False), ExitDecision(True)])
        second = ScriptedInstance([ActionDecision(ActionOutcome.SUCCEEDED, result={"ok": True})], [ExitDecision(True)])
        factory = ScriptedFactory([first, second])
        registry = ActionRegistry()
        registry.register_typed(ActionSpec("pulse", PulseParameters), factory)
        compiled = MissionValidator(registry).compile(
            MissionPlan("retry", (MissionStep("one", "pulse", PulseParameters("stream"), max_attempts=2),)),
            VehicleCapabilities(),
        )
        runtime = MissionRuntime(compiled, Reader(world()), "run-retry", max_snapshot_age_ns=100)
        self.assertEqual(runtime.tick(at(11)).status, RunStatus.EXITING)
        self.assertEqual(runtime.tick(at(12)).status, RunStatus.EXITING)
        self.assertEqual(factory.starts, 1)
        self.assertEqual(runtime.tick(at(13)).status, RunStatus.RUNNING)
        self.assertEqual(factory.starts, 1)
        self.assertEqual(runtime.tick(at(14)).status, RunStatus.EXITING)
        self.assertEqual(factory.starts, 2)
        done = runtime.tick(at(15))
        self.assertEqual(done.status, RunStatus.SUCCEEDED)
        self.assertEqual([item.reason for item in done.results], [ExitReason.FAILED, ExitReason.SUCCEEDED])
        self.assertEqual([item.attempt for item in done.results], [1, 2])

    def test_cancel_waits_for_stop_exit_and_effects_are_requests_only(self):
        target = TwistTargetEffect("base_link", Twist3(Vector3(1, 0, 0), Vector3(0, 0, 0)), "stream")
        instance = ScriptedInstance([ActionDecision(ActionOutcome.RUNNING, (target,))],
                                    [ExitDecision(False, (StopMotionEffect("stream"),)), ExitDecision(True)])
        factory = ScriptedFactory([instance])
        registry = ActionRegistry()
        registry.register_typed(ActionSpec("pulse", PulseParameters, effect_types=(TwistTargetEffect, StopMotionEffect),
                                           effect_ttl_ns=25), factory)
        compiled = MissionValidator(registry).compile(
            MissionPlan("cancel", (MissionStep("one", "pulse", PulseParameters("stream")),)), VehicleCapabilities(),
        )
        runtime = MissionRuntime(compiled, Reader(world()), "run-cancel", max_snapshot_age_ns=100)
        initial = runtime.tick(at(11))
        self.assertEqual(initial.status, RunStatus.RUNNING)
        self.assertEqual(type(initial.effects[0].effect), TwistTargetEffect)
        self.assertEqual(initial.effects[0].deadline.monotonic_ns, 36)
        self.assertFalse({"authorization_generation", "lease_id", "send_generation"} &
                         {field.name for field in fields(type(initial.effects[0]))})
        self.assertEqual(runtime.cancel().status, RunStatus.EXITING)
        exiting = runtime.tick(at(12))
        self.assertEqual(exiting.status, RunStatus.EXITING)
        self.assertEqual(type(exiting.effects[0].effect), StopMotionEffect)
        self.assertNotEqual(exiting.effects[0].effect_id, initial.effects[0].effect_id)
        done = runtime.tick(at(13))
        self.assertEqual(done.status, RunStatus.CANCELLED)
        self.assertEqual(instance.exit_reasons, [ExitReason.CANCELLED, ExitReason.CANCELLED])
        self.assertEqual(instance.tick_calls, 1)

    def test_undeclared_effect_fails_closed_and_does_not_emit(self):
        target = TwistTargetEffect("base_link", Twist3(Vector3(1, 0, 0), Vector3(0, 0, 0)), "stream")
        instance = ScriptedInstance([ActionDecision(ActionOutcome.RUNNING, (target,))], [ExitDecision(True)])
        registry = ActionRegistry()
        registry.register_typed(ActionSpec("pulse", PulseParameters, effect_types=(StopMotionEffect,)), ScriptedFactory([instance]))
        compiled = MissionValidator(registry).compile(
            MissionPlan("reject", (MissionStep("one", "pulse", PulseParameters("stream")),)), VehicleCapabilities(),
        )
        runtime = MissionRuntime(compiled, Reader(world()), "run-reject", max_snapshot_age_ns=100)
        rejected = runtime.tick(at(11))
        self.assertEqual(rejected.status, RunStatus.EXITING)
        self.assertEqual(rejected.effects, ())
        self.assertIn("undeclared", rejected.error)
        self.assertEqual(runtime.tick(at(12)).status, RunStatus.FAILED)

    def test_no_or_stale_world_does_not_run_action(self):
        registry = ActionRegistry()
        registry.register_typed(WORLD_SUMMARY_SPEC, WorldSummaryAction())
        compiled = MissionValidator(registry).compile(
            MissionPlan("wait", (MissionStep("one", "world.summary", WorldSummaryParameters()),)), VehicleCapabilities(),
        )
        reader = Reader(None)
        runtime = MissionRuntime(compiled, reader, "run-wait", max_snapshot_age_ns=5)
        self.assertEqual(runtime.tick(at(11)).status, RunStatus.RUNNING)
        reader.value = world()
        self.assertEqual(runtime.tick(at(16)).status, RunStatus.RUNNING)
        self.assertIn("stale", runtime.tick(at(16)).error)
        self.assertEqual(runtime.tick(at(15)).status, RunStatus.EXITING)

    def test_failure_continue_and_exit_exception_block_progress(self):
        failed = ScriptedInstance([ActionDecision(ActionOutcome.FAILED, error="not found")], [ExitDecision(True)])
        flaky = FlakyExitInstance()
        factory = ScriptedFactory([failed, flaky])
        registry = ActionRegistry()
        registry.register_typed(ActionSpec("probe", PulseParameters), factory)
        plan = MissionPlan("continue", (
            MissionStep("first", "probe", PulseParameters("x"), on_failure=FailurePolicy.CONTINUE),
            MissionStep("second", "probe", PulseParameters("x")),
        ))
        compiled = MissionValidator(registry).compile(plan, VehicleCapabilities())
        runtime = MissionRuntime(compiled, Reader(world()), "run-continue", max_snapshot_age_ns=100)
        self.assertEqual(runtime.tick(at(11)).status, RunStatus.EXITING)
        self.assertEqual(runtime.tick(at(12)).status, RunStatus.RUNNING)
        self.assertEqual(runtime.tick(at(13)).status, RunStatus.EXITING)
        blocked = runtime.tick(at(14))
        self.assertEqual(blocked.status, RunStatus.EXITING)
        self.assertIn("exit barrier pending", blocked.error)
        self.assertEqual(factory.starts, 2)
        completed = runtime.tick(at(15))
        self.assertEqual(completed.status, RunStatus.SUCCEEDED)
        self.assertEqual([item.step_id for item in completed.results], ["first", "second"])

    def test_decision_chain_cannot_import_command_port_or_protocol(self):
        root = Path(__file__).resolve().parents[1]
        for relative in ("contracts/decision.py", "core/actions.py", "core/action_registry.py",
                         "core/mission.py", "core/mission_runtime.py", "core/transform.py"):
            tree = ast.parse((root / relative).read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imports.append((node.module or "", {alias.name for alias in node.names}))
                elif isinstance(node, ast.Import):
                    imports.extend((alias.name, set()) for alias in node.names)
            self.assertFalse(any(
                module.startswith(("contracts.vehicle.command", "core.execution", "protocols", "pymavlink", "legacy"))
                or (module == "contracts.vehicle.ports" and "VehicleCommandPort" in names)
                for module, names in imports
            ), relative)


if __name__ == "__main__":
    unittest.main()

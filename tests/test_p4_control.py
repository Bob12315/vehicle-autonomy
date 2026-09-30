"""P4 offline control boundary, queue fences, and stop semantics."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path
import unittest

from contracts.core.geometry import FrameId, Pose3, Quaternion, Twist3, Vector3
from contracts.core.primitives import ResourceVersion, SchemaVersion
from contracts.core.quality import ComponentFreshness, FreshnessState, QualityState
from contracts.core.time import TimePoint
from contracts.effects.vehicle import (
    ArmEffect, EffectEnvelope, ModeEffect, PoseTargetEffect, StopMotionEffect,
    TakeoffEffect, TwistTargetEffect,
)
from contracts.vehicle.command import CommandPhase, StopMotionCommand
from contracts.vehicle.models import VehicleHealth, VehicleStateSnapshot
from contracts.world.models import WorldSnapshot
from core.control_authority import ControlAuthority, ControlLease
from core.fake_command_port import FakeVehicleCommandPort
from core.vehicle_execution import StopState, VehicleExecution
from core.vehicle_safety import SafetyLimits, VehicleSafetyPolicy


def time_at(ns: int, domain: str = "host") -> TimePoint:
    return TimePoint(ns, datetime(2026, 1, 1, tzinfo=timezone.utc), domain)


def world(ns: int = 100, *, healthy: bool = True) -> WorldSnapshot:
    vehicle = VehicleStateSnapshot(
        SchemaVersion(1, 0), "vehicle", ResourceVersion("v", 1), time_at(ns),
        VehicleHealth(QualityState.VALID if healthy else QualityState.INVALID),
    )
    return WorldSnapshot(
        SchemaVersion(1, 0), "world", ResourceVersion("w", 1), time_at(ns),
        vehicle=vehicle, freshness=(ComponentFreshness("vehicle", FreshnessState.FRESH),),
    )


def effect(number: int, payload, *, created: int = 100, deadline: int = 150,
           domain: str = "host") -> EffectEnvelope:
    return EffectEnvelope(
        SchemaVersion(1, 0), f"effect-{number}", "run", "action",
        time_at(created, domain), time_at(deadline, domain), payload,
    )


def limits() -> SafetyLimits:
    return SafetyLimits(
        max_request_ttl_ns=100, max_snapshot_age_ns=50, deadman_ns=10,
        min_altitude_m=0, max_altitude_m=20, max_takeoff_m=5,
        max_linear_mps=2, max_angular_rad_s=1,
        allowed_frames=frozenset({FrameId("map")}), allowed_modes=frozenset({"GUIDED"}),
        min_x_m=-10, max_x_m=10, min_y_m=-10, max_y_m=10,
    )


class ControlBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = ControlAuthority()
        self.port = FakeVehicleCommandPort(self.authority)
        self.ids = iter(f"command-{i}" for i in range(100))
        self.execution = VehicleExecution(self.port, self.authority, VehicleSafetyPolicy(limits()), lambda: next(self.ids))
        self.snapshot = world()

    def enable(self) -> None:
        self.authority.grant(ControlLease("lease", "run", "action", time_at(200)), time_at(100))
        self.authority.set_system_send(True)
        self.authority.set_action_send(True)
        self.authority.set_link_session("session-1")

    def test_default_closed_both_gates_and_explicit_policy(self):
        self.assertEqual(self.execution.dispatch(effect(1, ArmEffect()), self.snapshot, time_at(101)).reason, "system_send_disabled")
        self.authority.set_system_send(True)
        self.assertEqual(self.execution.dispatch(effect(2, ArmEffect()), self.snapshot, time_at(101)).reason, "action_send_disabled")
        self.assertEqual(len(self.port.transmitted), 0)
        with self.assertRaises(TypeError):
            VehicleExecution(self.port, self.authority, None, lambda: "id")
        with self.assertRaises(AttributeError):
            self.authority.system_send = True

    def test_scope_ttl_clock_and_policy_rejections(self):
        self.enable()
        cases = [
            (effect(1, ArmEffect(), deadline=101), 101, "invalid_effect_time"),
            (effect(2, ArmEffect(), deadline=300), 101, "invalid_effect_time"),
            (effect(3, ArmEffect(), domain="else"), 101, "clock_domain_mismatch"),
            (effect(4, TakeoffEffect(6)), 101, "takeoff_height_out_of_bounds"),
            (effect(5, ModeEffect("AUTO")), 101, "mode_not_allowed"),
            (effect(6, TwistTargetEffect("body", Twist3(Vector3(0, 0, 0), Vector3(0, 0, 0)), "s")), 101, "frame_not_allowed"),
            (effect(7, TwistTargetEffect("map", Twist3(Vector3(3, 0, 0), Vector3(0, 0, 0)), "s")), 101, "speed_limit_exceeded"),
            (effect(8, PoseTargetEffect("map", Pose3(Vector3(20, 0, 1), Quaternion(0, 0, 0, 1)), "s")), 101, "target_outside_geofence"),
        ]
        for request, now, expected in cases:
            with self.subTest(expected=expected, number=request.effect_id):
                self.assertEqual(self.execution.dispatch(request, self.snapshot, time_at(now)).reason, expected)
        wrong_scope = EffectEnvelope(SchemaVersion(1, 0), "wrong", "other-run", "action", time_at(100), time_at(150), ArmEffect())
        self.assertEqual(self.execution.dispatch(wrong_scope, self.snapshot, time_at(101)).reason, "lease_scope_mismatch")
        self.assertEqual(self.execution.dispatch(effect(9, ArmEffect()), world(0), time_at(101)).reason, "world_stale")
        self.assertEqual(self.execution.dispatch(effect(10, ArmEffect()), world(100, healthy=False), time_at(101)).reason, "vehicle_state_unavailable")

    def test_lease_and_link_lifecycle(self):
        self.enable()
        result = self.execution.dispatch(effect(1, ArmEffect()), self.snapshot, time_at(101))
        self.assertEqual(result.receipt.phase, CommandPhase.ACCEPTED)
        self.authority.revoke()
        status = self.port.transmit_next(time_at(102))
        self.assertEqual(status.phase, CommandPhase.REJECTED)
        self.assertEqual(self.port.rejection_reasons[status.command_id], "lease_revoked")
        self.assertEqual(self.port.transmitted, [])
        self.authority.grant(ControlLease("lease-2", "run", "action", time_at(200)), time_at(103))
        self.authority.set_action_send(True)
        self.assertEqual(self.execution.dispatch(effect(2, ArmEffect()), self.snapshot, time_at(104)).receipt.phase, CommandPhase.ACCEPTED)
        self.authority.set_link_session("session-2")
        self.assertEqual(self.port.transmit_next(time_at(105)).phase, CommandPhase.REJECTED)
        self.assertEqual(self.execution.dispatch(effect(3, ArmEffect()), self.snapshot, time_at(106)).receipt.phase, CommandPhase.ACCEPTED)
        self.authority.set_link_session(None)
        self.assertEqual(self.port.transmit_next(time_at(107)).phase, CommandPhase.REJECTED)
        self.assertEqual(self.execution.dispatch(effect(4, ArmEffect()), self.snapshot, time_at(108)).reason, "link_disconnected")

    def test_disconnect_reconnect_same_session_fences_old_queue(self):
        self.enable()
        queued = self.execution.dispatch(effect(1, ArmEffect()), self.snapshot, time_at(101)).receipt
        self.authority.set_link_session(None)
        self.authority.set_link_session("session-1")
        self.assertEqual(self.port.transmit_next(time_at(102)).phase, CommandPhase.REJECTED)
        self.assertEqual(self.port.rejection_reasons[queued.command_id], "generation_changed")
        self.assertEqual(self.port.transmitted, [])

    def test_send_generation_deadline_and_lease_expiry_at_write(self):
        self.enable()
        receipt = self.execution.dispatch(effect(1, ArmEffect()), self.snapshot, time_at(101)).receipt
        self.authority.set_action_send(False)
        self.authority.set_action_send(True)
        self.assertEqual(self.port.transmit_next(time_at(102)).phase, CommandPhase.REJECTED)
        self.assertEqual(self.port.rejection_reasons[receipt.command_id], "generation_changed")
        self.execution.dispatch(effect(2, ArmEffect()), self.snapshot, time_at(103))
        self.assertEqual(self.port.transmit_next(time_at(150)).phase, CommandPhase.REJECTED)
        self.execution.dispatch(effect(3, ArmEffect(), deadline=180), self.snapshot, time_at(104))
        self.assertEqual(self.port.transmit_next(time_at(201)).phase, CommandPhase.REJECTED)
        self.assertEqual(self.port.transmitted, [])

    def test_receipt_cancel_ack_and_observed_completion_are_distinct(self):
        self.enable()
        result = self.execution.dispatch(effect(1, ArmEffect()), self.snapshot, time_at(101))
        command_id = result.receipt.command_id
        self.assertEqual(self.port.status(command_id).phase, CommandPhase.ACCEPTED)
        with self.assertRaises(ValueError):
            self.port.acknowledge(command_id, time_at(102))
        self.assertEqual(self.port.transmit_next(time_at(102)).phase, CommandPhase.TRANSMITTED)
        with self.assertRaises(ValueError):
            self.port.acknowledge(command_id, time_at(101))
        self.assertEqual(self.port.acknowledge(command_id, time_at(103)).phase, CommandPhase.ACKNOWLEDGED)
        self.assertEqual(self.port.observe_completed(command_id, time_at(104)).phase, CommandPhase.COMPLETED)
        with self.assertRaises(FrozenInstanceError):
            result.receipt.phase = CommandPhase.REJECTED
        another = self.execution.dispatch(effect(2, ArmEffect()), self.snapshot, time_at(105)).receipt
        from contracts.vehicle.command import CancelCommandRequest
        self.assertEqual(self.port.cancel(CancelCommandRequest(another.command_id, time_at(106))).phase, CommandPhase.CANCELLED)
        self.assertIsNone(self.port.transmit_next(time_at(107)))

    def test_continuous_deadman_stop_and_confirmation(self):
        self.enable()
        request = effect(1, TwistTargetEffect("map", Twist3(Vector3(1, 0, 0), Vector3(0, 0, 0)), "stream"))
        motion = self.execution.dispatch(request, self.snapshot, time_at(101)).receipt
        self.assertEqual(self.port.transmit_next(time_at(102)).phase, CommandPhase.TRANSMITTED)
        self.assertEqual(self.execution.tick(time_at(111)), ())
        stop = self.execution.tick(time_at(112))[0]
        self.assertEqual(stop.state, StopState.ACCEPTED)
        self.assertEqual(self.port.status(motion.command_id).phase, CommandPhase.CANCELLED)
        self.assertEqual(self.execution.stop_status("stream").state, StopState.ACCEPTED)
        sent = self.port.transmit_next(time_at(113))
        self.assertIsInstance(self.port.transmitted[-1].command, StopMotionCommand)
        self.assertEqual(self.port.simulated_zero_writes, ["stream"])
        self.assertEqual(sent.phase, CommandPhase.TRANSMITTED)
        self.assertEqual(self.execution.stop_status("stream").state, StopState.TRANSMITTED)
        self.port.acknowledge(stop.command_id, time_at(114))
        self.assertEqual(self.execution.stop_status("stream").state, StopState.ACKNOWLEDGED)
        self.port.observe_completed(stop.command_id, time_at(115))
        self.assertEqual(self.execution.stop_status("stream").state, StopState.CONFIRMED)
        renewed = self.execution.dispatch(
            effect(2, TwistTargetEffect("map", Twist3(Vector3(1, 0, 0), Vector3(0, 0, 0)), "stream")),
            self.snapshot, time_at(116),
        )
        self.assertEqual(renewed.receipt.phase, CommandPhase.ACCEPTED)

    def test_disconnect_stop_is_unconfirmed_and_never_transmitted(self):
        self.enable()
        motion = self.execution.dispatch(effect(1, TwistTargetEffect("map", Twist3(Vector3(1, 0, 0), Vector3(0, 0, 0)), "stream")), self.snapshot, time_at(101)).receipt
        self.authority.set_link_session(None)
        result = self.execution.tick(time_at(112))[0]
        self.assertEqual(result.state, StopState.UNCONFIRMED)
        self.assertEqual(result.reason, "link_disconnected")
        self.assertEqual(self.port.status(motion.command_id).phase, CommandPhase.CANCELLED)
        self.assertEqual(self.port.transmitted, [])
        self.assertIsNone(self.port.transmit_next(time_at(113)))

    def test_refresh_cancels_old_queued_target_and_effect_id_is_idempotent(self):
        self.enable()
        payload = TwistTargetEffect("map", Twist3(Vector3(1, 0, 0), Vector3(0, 0, 0)), "stream")
        first = self.execution.dispatch(effect(1, payload), self.snapshot, time_at(101))
        self.assertEqual(self.execution.dispatch(effect(1, payload), self.snapshot, time_at(101)), first)
        second = self.execution.dispatch(effect(2, payload), self.snapshot, time_at(105))
        self.assertEqual(self.port.status(first.receipt.command_id).phase, CommandPhase.CANCELLED)
        self.assertEqual(self.port.transmit_next(time_at(106)).command_id, second.receipt.command_id)
        self.assertEqual(len(self.port.transmitted), 1)
        stop = self.execution.dispatch(effect(3, StopMotionEffect("stream")), self.snapshot, time_at(107))
        self.assertEqual(stop.receipt.phase, CommandPhase.ACCEPTED)
        self.assertEqual(self.execution.stop_status("stream").state, StopState.ACCEPTED)
        self.assertEqual(
            self.execution.dispatch(effect(4, payload), self.snapshot, time_at(108)).reason,
            "stream_stop_unconfirmed",
        )
        with self.assertRaises(ValueError):
            self.execution.dispatch(effect(1, ArmEffect()), self.snapshot, time_at(108))

    def test_revoked_or_expired_control_cannot_confirm_stop(self):
        self.enable()
        payload = TwistTargetEffect("map", Twist3(Vector3(1, 0, 0), Vector3(0, 0, 0)), "stream")
        self.execution.dispatch(effect(1, payload), self.snapshot, time_at(101))
        self.authority.revoke()
        stop = self.execution.tick(time_at(112))[0]
        self.assertEqual(stop.state, StopState.UNCONFIRMED)
        self.assertEqual(stop.reason, "action_send_disabled")
        self.assertEqual(self.port.transmitted, [])

    def test_stop_fenced_after_queue_and_policy_config_is_validated(self):
        self.enable()
        payload = TwistTargetEffect("map", Twist3(Vector3(1, 0, 0), Vector3(0, 0, 0)), "stream")
        self.execution.dispatch(effect(1, payload), self.snapshot, time_at(101))
        stop = self.execution.tick(time_at(112))[0]
        self.authority.set_link_session("new-session")
        self.assertEqual(self.port.transmit_next(time_at(113)).phase, CommandPhase.REJECTED)
        self.assertEqual(self.execution.stop_status("stream").state, StopState.UNCONFIRMED)
        with self.assertRaises(ValueError):
            replace(limits(), deadman_ns=0)

    def test_v1_command_port_is_owned_only_by_execution_and_fake_writer(self):
        root = Path(__file__).resolve().parents[1]
        owners = {
            path.name for path in (root / "core").glob("*.py")
            if "from contracts.vehicle.ports import VehicleCommandPort" in path.read_text(encoding="utf-8")
        }
        self.assertEqual(owners, {"vehicle_execution.py"})
        self.assertNotIn("VehicleCommandPort", (root / "core" / "mission_runtime.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

"""P5 Copter plugin, MAVLink codec, fenced writer and session tests."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import os
from pathlib import Path
import pty
import socket
import unittest

from pymavlink.dialects.v20 import ardupilotmega as mavlink

from contracts.core.geometry import FrameId, Pose3, Quaternion, Twist3, Vector3
from contracts.core.primitives import ResourceVersion, SchemaVersion
from contracts.core.serialization import to_json_value
from contracts.core.quality import ComponentFreshness, FreshnessState, QualityState
from contracts.core.time import TimePoint
from contracts.effects.vehicle import ArmEffect, EffectEnvelope, ModeEffect, PoseTargetEffect, TwistTargetEffect
from contracts.vehicle.command import (
    ArmCommand, CommandPhase, CommandStatus, DisarmCommand, LandCommand,
    ModeCommand, StopMotionCommand, TakeoffCommand,
)
from contracts.vehicle.models import VehicleHealth, VehicleStateSnapshot
from contracts.world.models import WorldSnapshot
from core.control_authority import ControlAuthority, ControlLease
from core.vehicle_execution import StopState, VehicleExecution
from core.vehicle_safety import SafetyLimits, VehicleSafetyPolicy
from deployment.copter_cycle import CopterCycleDriver
from infrastructure.transports.bytes import SerialByteTransport, TcpByteTransport
from protocols.mavlink.codec import MavlinkCodec
from protocols.mavlink.constants import TYPE_GROUND_ROVER, TYPE_QUADROTOR
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator
from vehicles.multirotor.diagnostic import (
    CopterBenchArmDiagnosticTranslator, CopterBenchModeDiagnosticTranslator,
    CopterStabilizeDiagnosticTranslator,
)
from vehicles.multirotor.mavlink_port import ArduPilotCommandPort
from vehicles.multirotor.mavlink_state import ArduPilotTelemetryState
from vehicles.multirotor.session import ArduPilotSession
from vehicles.rover.diagnostic import RoverHoldDiagnosticTranslator


def at(ns: int) -> TimePoint:
    return TimePoint(ns, datetime(2026, 1, 1, tzinfo=timezone.utc), "host")


def world() -> WorldSnapshot:
    vehicle = VehicleStateSnapshot(
        SchemaVersion(1, 0), "copter", ResourceVersion("v", 1), at(100),
        VehicleHealth(QualityState.VALID),
    )
    return WorldSnapshot(
        SchemaVersion(1, 0), "world", ResourceVersion("w", 1), at(100),
        vehicle=vehicle, freshness=(ComponentFreshness("vehicle", FreshnessState.FRESH),),
    )


def effect(index: int, payload, *, deadline: int = 180) -> EffectEnvelope:
    return EffectEnvelope(SchemaVersion(1, 0), f"effect-{index}", "run", "action", at(100), at(deadline), payload)


def policy() -> VehicleSafetyPolicy:
    return VehicleSafetyPolicy(SafetyLimits(
        max_request_ttl_ns=100, max_snapshot_age_ns=100, deadman_ns=10,
        min_altitude_m=0, max_altitude_m=20, max_takeoff_m=5,
        max_linear_mps=2, max_angular_rad_s=1,
        allowed_frames=frozenset({FrameId("odom"), FrameId("base_link")}), allowed_modes=frozenset({"GUIDED"}),
        min_x_m=-10, max_x_m=10, min_y_m=-10, max_y_m=10,
    ))


class MemoryTransport:
    def __init__(self):
        self.incoming = []
        self.writes = []
        self.fail_write = False
        self.closed = False

    def write(self, data):
        if self.fail_write:
            raise ConnectionError("uncertain write")
        self.writes.append(data)

    def read(self, max_bytes=4096):
        return self.incoming.pop(0) if self.incoming else None

    def close(self):
        self.closed = True


class P5MavlinkTests(unittest.TestCase):
    def setUp(self):
        self.transport = MemoryTransport()
        self.authority = ControlAuthority()
        self.codec = MavlinkCodec(source_system=250, source_component=191, target_system=1, target_component=1)
        self.translator = ArduPilotCommandTranslator(mode_ids={"GUIDED": 4})
        self.now_ns = 100
        self.port = ArduPilotCommandPort(
            authority=self.authority, transport=self.transport, codec=self.codec,
            translator=self.translator, now=lambda: at(self.now_ns),
        )
        self.sender = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
        self.other = mavlink.MAVLink(None, srcSystem=2, srcComponent=1)
        self.session = ArduPilotSession(
            transport=self.transport, codec=self.codec, authority=self.authority,
            commands=self.port, link_timeout_ns=50,
            expected_vehicle_type=TYPE_QUADROTOR,
            state_factory=lambda session_id: ArduPilotTelemetryState(
                vehicle_id="copter", generation_id=str(session_id), link_session_id=session_id,
                source_system=1, source_component=1, max_sample_skew_ns=5,
                max_field_age_ns=1000, link_timeout_ns=50,
            ),
            captured_at=lambda message, received: received,
        )
        self.ids = iter(f"cmd-{n}" for n in range(100))
        self.execution = VehicleExecution(self.port, self.authority, policy(), lambda: next(self.ids))

    def heartbeat(self, *, armed=False, mode=4, sender=None, vehicle_type=TYPE_QUADROTOR):
        maker = sender or self.sender
        return maker.heartbeat_encode(vehicle_type, 3, 128 if armed else 0, mode, 4).pack(maker)

    def ack(self, command, result=0, *, sender=None):
        maker = sender or self.sender
        return maker.command_ack_encode(command, result).pack(maker)

    def connect(self):
        self.transport.incoming.append(self.heartbeat())
        self.session.poll(at(100))
        self.authority.grant(ControlLease("lease", "run", "action", at(200)), at(100))
        self.authority.set_system_send(True)
        self.authority.set_action_send(True)

    def test_default_closed_and_protocol_bytes_only_after_writer(self):
        self.transport.incoming.append(self.heartbeat())
        self.session.poll(at(100))
        self.assertIsNotNone(self.session.session_id)
        self.assertEqual(self.execution.dispatch(effect(1, ArmEffect()), world(), at(101)).reason, "system_send_disabled")
        self.assertEqual(self.transport.writes, [])
        self.authority.grant(ControlLease("lease", "run", "action", at(200)), at(100))
        self.authority.set_system_send(True)
        self.authority.set_action_send(True)
        self.now_ns = 101
        receipt = self.execution.dispatch(effect(2, ArmEffect()), world(), at(101)).receipt
        self.assertEqual(receipt.phase, CommandPhase.ACCEPTED)
        self.assertEqual(self.transport.writes, [])
        self.assertEqual(self.session.write_next(at(102)).phase, CommandPhase.TRANSMITTED)
        decoded = MavlinkCodec(source_system=1, source_component=1, target_system=250, target_component=191).feed(self.transport.writes[0])
        self.assertEqual(decoded[0].get_type(), "COMMAND_LONG")
        self.assertEqual(decoded[0].command, mavlink.MAV_CMD_COMPONENT_ARM_DISARM)
        self.assertEqual(decoded[0].param1, 1)
        self.transport.incoming.append(self.ack(mavlink.MAV_CMD_COMPONENT_ARM_DISARM, sender=self.other))
        self.session.poll(at(103))
        self.assertEqual(self.port.status(receipt.command_id).phase, CommandPhase.TRANSMITTED)
        self.transport.incoming.append(self.ack(mavlink.MAV_CMD_COMPONENT_ARM_DISARM))
        self.session.poll(at(104))
        self.assertEqual(self.port.status(receipt.command_id).phase, CommandPhase.ACKNOWLEDGED)
        self.transport.incoming.append(self.heartbeat(armed=True))
        self.session.poll(at(105))
        self.assertEqual(self.port.status(receipt.command_id).phase, CommandPhase.COMPLETED)

    def test_link_timeout_revokes_both_sends_and_old_lease(self):
        self.connect()
        old_session = self.session.session_id
        self.now_ns = 101
        queued = self.execution.dispatch(effect(1, ArmEffect()), world(), at(101)).receipt
        self.session.tick(at(160))
        self.assertFalse(self.authority.system_send)
        self.assertFalse(self.authority.action_send)
        self.assertIsNone(self.authority.lease)
        self.assertEqual(self.port.status(queued.command_id).phase, CommandPhase.REJECTED)
        self.transport.incoming.append(self.heartbeat())
        self.session.poll(at(161))
        self.assertNotEqual(self.session.session_id, old_session)
        self.assertEqual(self.execution.dispatch(effect(2, ArmEffect()), world(), at(162)).reason,
                         "system_send_disabled")
        self.assertEqual(self.transport.writes, [])

    def test_copter_session_rejects_rover_heartbeat(self):
        self.transport.incoming.append(self.heartbeat(vehicle_type=TYPE_GROUND_ROVER))
        self.session.poll(at(100))
        self.assertIsNone(self.session.session_id)
        self.assertIsNone(self.authority.link_session_id)
        self.assertEqual(self.session.last_rejected_vehicle_type, TYPE_GROUND_ROVER)
        self.authority.grant(ControlLease("lease", "run", "action", at(200)), at(100))
        self.authority.set_system_send(True)
        self.authority.set_action_send(True)
        self.assertEqual(self.execution.dispatch(effect(1, ArmEffect()), world(), at(101)).reason, "link_disconnected")
        self.assertEqual(self.transport.writes, [])

    def test_coordinate_translation_and_rejection(self):
        self.connect()
        self.now_ns = 101
        pose = Pose3(Vector3(2, 3, 4), Quaternion(0, 0, 0, 1))
        self.execution.dispatch(effect(1, PoseTargetEffect("odom", pose, "pose")), world(), at(101))
        self.session.write_next(at(102))
        msg = MavlinkCodec(source_system=1, source_component=1, target_system=250, target_component=191).feed(self.transport.writes[-1])[0]
        self.assertEqual(msg.coordinate_frame, mavlink.MAV_FRAME_LOCAL_NED)
        self.assertEqual(msg.type_mask, 2552)
        self.assertEqual((msg.x, msg.y, msg.z), (3, 2, -4))
        self.now_ns = 103
        twist = Twist3(Vector3(1, 1, 0.5), Vector3(0, 0, 0.2))
        self.execution.dispatch(effect(2, TwistTargetEffect("base_link", twist, "body")), world(), at(103))
        self.session.write_next(at(104))
        msg = MavlinkCodec(source_system=1, source_component=1, target_system=250, target_component=191).feed(self.transport.writes[-1])[0]
        self.assertEqual(msg.coordinate_frame, mavlink.MAV_FRAME_BODY_NED)
        self.assertEqual((msg.vx, msg.vy, msg.vz), (1, -1, -0.5))
        self.assertAlmostEqual(msg.yaw_rate, -0.2, places=6)
        self.now_ns = 105
        invalid = Pose3(Vector3(1, 1, 1), Quaternion(0.1, 0, 0, 0.99498743710662))
        result = self.execution.dispatch(effect(3, PoseTargetEffect("odom", invalid, "tilted")), world(), at(105))
        self.assertEqual(result.receipt.phase, CommandPhase.REJECTED)
        self.assertEqual(len(self.transport.writes), 2)

    def test_one_shot_command_mapping(self):
        cases = (
            (ArmCommand(), mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1, 0),
            (DisarmCommand(), mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0),
            (TakeoffCommand(3), mavlink.MAV_CMD_NAV_TAKEOFF, 0, 3),
            (LandCommand(), mavlink.MAV_CMD_NAV_LAND, 0, 0),
            (ModeCommand("GUIDED"), mavlink.MAV_CMD_DO_SET_MODE, 1, 0),
        )
        for command, command_number, param1, param7 in cases:
            with self.subTest(command=type(command).__name__):
                instruction = self.translator.translate(command)
                packet = self.codec.encode(instruction)
                parsed = MavlinkCodec(source_system=1, source_component=1, target_system=250, target_component=191).feed(packet)[0]
                self.assertEqual(parsed.command, command_number)
                self.assertEqual(parsed.param1, param1)
                self.assertEqual(parsed.param7, param7)

    def test_deadman_zero_write_and_post_write_state_observation(self):
        self.connect()
        self.now_ns = 101
        target = TwistTargetEffect("odom", Twist3(Vector3(1, 0, 0), Vector3(0, 0, 0)), "stream")
        motion = self.execution.dispatch(effect(1, target), world(), at(101)).receipt
        self.session.write_next(at(102))
        self.now_ns = 112
        stop = self.execution.tick(at(112))[0]
        self.assertEqual(stop.state, StopState.ACCEPTED)
        self.assertEqual(self.port.status(motion.command_id).phase, CommandPhase.CANCELLED)
        self.assertEqual(self.session.write_next(at(113)).phase, CommandPhase.TRANSMITTED)
        msg = MavlinkCodec(source_system=1, source_component=1, target_system=250, target_component=191).feed(self.transport.writes[-1])[0]
        self.assertEqual((msg.vx, msg.vy, msg.vz, msg.yaw_rate), (0, 0, 0, 0))
        self.assertEqual(self.execution.stop_status("stream").state, StopState.TRANSMITTED)
        sample = self.sender.local_position_ned_encode(0, 0, 0, 0, 0, 0, 0)
        attitude = self.sender.attitude_encode(0, 0, 0, 0, 0, 0, 0)
        self.transport.incoming.append(sample.pack(self.sender) + attitude.pack(self.sender))
        self.session.poll(at(114))
        self.assertEqual(self.execution.stop_status("stream").state, StopState.CONFIRMED)

    def test_cycle_driver_schedules_deadman_and_reports_link_loss(self):
        self.connect()
        self.now_ns = 101
        target = TwistTargetEffect("odom", Twist3(Vector3(1, 0, 0), Vector3(0, 0, 0)), "stream")
        self.execution.dispatch(effect(1, target), world(), at(101))
        driver = CopterCycleDriver(session=self.session, execution=self.execution,
                                   clock=lambda: at(self.now_ns))
        self.assertEqual(driver.cycle().written.phase, CommandPhase.TRANSMITTED)
        self.now_ns = 112
        cycle = driver.cycle()
        self.assertEqual(cycle.stops[0].state, StopState.ACCEPTED)
        self.assertEqual(cycle.written.phase, CommandPhase.TRANSMITTED)
        self.assertFalse(cycle.disconnected)
        self.now_ns = 200
        self.assertTrue(driver.cycle().disconnected)
        self.assertEqual(self.execution.stop_status("stream").state, StopState.UNCONFIRMED)

    def test_revoke_disconnect_and_uncertain_write_fence(self):
        self.connect()
        self.now_ns = 101
        first = self.execution.dispatch(effect(1, ArmEffect()), world(), at(101)).receipt
        self.authority.revoke()
        self.assertEqual(self.session.write_next(at(102)).phase, CommandPhase.REJECTED)
        self.assertEqual(self.transport.writes, [])
        self.assertEqual(self.port.reasons[first.command_id], "lease_revoked")
        self.authority.grant(ControlLease("second", "run", "action", at(200)), at(103))
        self.authority.set_action_send(True)
        self.now_ns = 104
        second = self.execution.dispatch(effect(2, ArmEffect()), world(), at(104)).receipt
        self.transport.fail_write = True
        self.assertEqual(self.session.write_next(at(105)).phase, CommandPhase.UNKNOWN)
        self.assertIn("transport_write_uncertain", self.port.reasons[second.command_id])
        self.assertIsNone(self.session.write_next(at(106)))
        self.session.tick(at(200))
        self.assertIsNone(self.authority.link_session_id)
        self.assertEqual(self.port.status(second.command_id).phase, CommandPhase.UNKNOWN)

    def test_ack_timeout_unknown_and_no_same_command_replay(self):
        self.connect()
        self.now_ns = 101
        first = self.execution.dispatch(effect(1, ArmEffect(), deadline=110), world(), at(101)).receipt
        self.session.write_next(at(102))
        self.assertEqual(self.session.tick(at(110))[0].phase, CommandPhase.UNKNOWN)
        self.now_ns = 111
        second = self.execution.dispatch(effect(2, ArmEffect()), world(), at(111)).receipt
        self.assertEqual(second.phase, CommandPhase.ACCEPTED)
        self.assertIsNone(self.session.write_next(at(112)))
        self.transport.incoming.append(self.ack(mavlink.MAV_CMD_COMPONENT_ARM_DISARM))
        self.session.poll(at(113))
        self.assertEqual(self.port.status(first.command_id).phase, CommandPhase.UNKNOWN)
        self.assertEqual(self.port.status(second.command_id).phase, CommandPhase.ACCEPTED)
        self.assertEqual(to_json_value(CommandStatus(first.command_id, CommandPhase.UNKNOWN, at(110)))["phase"], "UNKNOWN")

    def test_unsupported_mapping_and_no_capture_clock(self):
        with self.assertRaises(ValueError):
            ArduPilotCommandTranslator(mode_ids={"GUIDED": 0x100000000})
        with self.assertRaises(ValueError):
            self.translator.translate(ModeCommand("AUTO"))
        with self.assertRaises(ValueError):
            ArduPilotSession(
                transport=MemoryTransport(), codec=self.codec, authority=self.authority,
                commands=self.port, link_timeout_ns=50, state_factory=lambda session_id: self.session._state,
                expected_vehicle_type=TYPE_QUADROTOR,
            )
        session = ArduPilotSession(
            transport=self.transport, codec=self.codec, authority=self.authority,
            commands=self.port, link_timeout_ns=50,
            expected_vehicle_type=TYPE_QUADROTOR,
            state_factory=lambda session_id: ArduPilotTelemetryState(
                vehicle_id="copter", generation_id=str(session_id), link_session_id=session_id,
                source_system=1, source_component=1, max_sample_skew_ns=5,
                max_field_age_ns=1000, link_timeout_ns=50,
            ),
        )
        self.transport.incoming.append(self.heartbeat())
        session.poll(at(100))
        self.assertIsNotNone(session.session_id)
        self.assertIsNone(session.snapshot())

    def test_tcp_transport_socketpair_has_no_command_methods(self):
        left, right = socket.socketpair()
        try:
            transport = TcpByteTransport(left)
            transport.write(b"abc")
            self.assertEqual(right.recv(3), b"abc")
            right.sendall(b"def")
            self.assertEqual(transport.read(), b"def")
            self.assertFalse(hasattr(transport, "submit"))
            transport.close()
            with self.assertRaises(ConnectionError):
                transport.write(b"x")
        finally:
            right.close()

    def test_serial_transport_pty_and_rover_diagnostic_scope(self):
        master, slave = pty.openpty()
        try:
            path = os.ttyname(slave)
            transport = SerialByteTransport.connect(path, timeout_s=0.05)
            transport.write(b"abc")
            self.assertEqual(os.read(master, 3), b"abc")
            os.write(master, b"def")
            self.assertEqual(transport.read(3), b"def")
            self.assertFalse(hasattr(transport, "submit"))
            transport.close()
            with self.assertRaises(ConnectionError):
                transport.write(b"x")
        finally:
            os.close(master)
            os.close(slave)
        rover = RoverHoldDiagnosticTranslator()
        self.assertEqual(rover.translate(ModeCommand("HOLD")).params[1], 4)
        for command in (ArmCommand(), TakeoffCommand(1), ModeCommand("GUIDED")):
            with self.subTest(command=type(command).__name__), self.assertRaises(ValueError):
                rover.translate(command)

    def test_copter_usb_diagnostic_allows_only_stabilize(self):
        copter = CopterStabilizeDiagnosticTranslator()
        self.assertEqual(copter.translate(ModeCommand("STABILIZE")).params[1], 0)
        for command in (ArmCommand(), TakeoffCommand(1), ModeCommand("GUIDED")):
            with self.subTest(command=type(command).__name__), self.assertRaises(ValueError):
                copter.translate(command)

    def test_copter_bench_diagnostic_limits_arm_and_disarm_scope(self):
        bench = CopterBenchArmDiagnosticTranslator()
        self.assertEqual(bench.translate(ArmCommand()).params[0], 1)
        self.assertEqual(bench.translate(DisarmCommand()).params[0], 0)
        self.assertEqual(bench.translate(ModeCommand("STABILIZE")).params[1], 0)
        for command in (TakeoffCommand(1), ModeCommand("GUIDED")):
            with self.subTest(command=type(command).__name__), self.assertRaises(ValueError):
                bench.translate(command)

    def test_copter_mode_bench_limits_round_trip_scope(self):
        bench = CopterBenchModeDiagnosticTranslator()
        self.assertEqual(bench.translate(ModeCommand("STABILIZE")).params[1], 0)
        self.assertEqual(bench.translate(ModeCommand("ACRO")).params[1], 1)
        for command in (ArmCommand(), TakeoffCommand(1), ModeCommand("GUIDED")):
            with self.subTest(command=type(command).__name__), self.assertRaises(ValueError):
                bench.translate(command)

    def test_only_vehicle_port_calls_byte_transport_write(self):
        root = Path(__file__).resolve().parents[1]
        writers = set()
        for directory in ("app", "application", "core", "deployment", "vehicles", "protocols"):
            for path in (root / directory).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                if any(
                    isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "write" for node in ast.walk(tree)
                ):
                    writers.add(path.relative_to(root).as_posix())
        self.assertEqual(writers, {"vehicles/multirotor/mavlink_port.py"})
        self.assertNotIn("ArduPilotSession", (root / "app" / "main.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

"""Parsed ArduPilot telemetry is normalized without any command or link writer."""

from __future__ import annotations

import ast
from dataclasses import fields
from datetime import datetime, timezone
import math
from pathlib import Path
import unittest

from application.state_chain import OfflineStateChain
from contracts.core.geometry import Vector3
from contracts.core.quality import QualityState
from contracts.core.time import TimePoint
from core.transform import rotate_vector
from localization.reported import ReportedPoseLocalization
from protocols.mavlink.telemetry import LocalPositionNed, decode_telemetry
from vehicles.multirotor import ArduPilotTelemetryState
from world_model import FreshnessLimits, WorldModel


def at(ns: int, domain: str = "receiver") -> TimePoint:
    return TimePoint(ns, datetime(2026, 1, 1, tzinfo=timezone.utc), domain)


class Message:
    def __init__(self, kind, *, system=1, component=1, **fields):
        self._kind = kind
        self._system = system
        self._component = component
        for name, value in fields.items():
            setattr(self, name, value)

    def get_type(self):
        return self._kind

    def get_srcSystem(self):
        return self._system

    def get_srcComponent(self):
        return self._component


class MavlinkStateAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = ArduPilotTelemetryState(
            vehicle_id="vehicle-a", generation_id="mav-gen", link_session_id="link-a",
            source_system=1, source_component=1, max_sample_skew_ns=10,
            max_field_age_ns=100, link_timeout_ns=100,
        )

    def feed(self, kind, time_ns, **fields):
        return self.adapter.ingest(Message(kind, **fields), captured_at=at(time_ns), received_at=at(time_ns + 1))

    def test_ned_frd_to_enu_flu_and_world_pipeline(self):
        self.feed("HEARTBEAT", 10, base_mode=128, custom_mode=4)
        self.feed("LOCAL_POSITION_NED", 12, x=2.0, y=3.0, z=-4.0, vx=5.0, vy=6.0, vz=-7.0)
        self.feed("ATTITUDE", 13, roll=0.0, pitch=0.0, yaw=0.0, rollspeed=0.0, pitchspeed=0.0, yawspeed=1.0)
        state = self.adapter.publish(at(20))
        self.assertEqual((state.reported_pose.value.position.x, state.reported_pose.value.position.y,
                          state.reported_pose.value.position.z), (3.0, 2.0, 4.0))
        self.assertEqual(state.reported_pose.frame_id, "odom")
        self.assertEqual(state.reported_pose.captured_at.monotonic_ns, 12)
        self.assertAlmostEqual(abs(state.reported_pose.value.orientation.z), math.sqrt(0.5))
        forward = rotate_vector(state.reported_pose.value.orientation, Vector3(1, 0, 0))
        self.assertAlmostEqual(forward.x, 0)
        self.assertAlmostEqual(forward.y, 1)
        self.assertEqual((state.reported_twist.value.linear.x, state.reported_twist.value.linear.y,
                          state.reported_twist.value.linear.z), (6.0, 5.0, 7.0))
        self.assertAlmostEqual(state.reported_twist.value.angular.z, -1.0)
        self.assertTrue(state.operation.armed)
        self.assertEqual(state.operation.native_mode, "ARDUPILOT_CUSTOM_4")
        self.assertFalse({"control_allowed", "source", "send_enabled", "lease", "authorization"} &
                         {field.name for field in fields(type(state))})
        self.assertFalse(hasattr(self.adapter, "send_raw_message"))
        self.assertFalse(hasattr(self.adapter, "submit"))

        model = WorldModel("world", FreshnessLimits(100, 100, 100))
        chain = OfflineStateChain(self.adapter, ReportedPoseLocalization(), model)
        world = chain.collect_and_publish(at(21))
        self.assertEqual(world.vehicle.reported_pose.value.position, state.reported_pose.value.position)
        self.assertEqual(world.localization.pose.frame_id, "odom")

    def test_gps_fix_battery_sentinels_and_link_are_independent(self):
        self.feed("GLOBAL_POSITION_INT", 10, lat=0, lon=0, alt=123000)
        before_fix = self.adapter.publish(at(12))
        self.assertIsNone(before_fix.global_position)
        self.feed("GPS_RAW_INT", 13, fix_type=3)
        self.feed("SYS_STATUS", 14, voltage_battery=65535, current_battery=-1, battery_remaining=-1)
        state = self.adapter.publish(at(20))
        self.assertEqual(state.global_position.value.latitude_deg, 0)
        self.assertEqual(state.global_position.value.longitude_deg, 0)
        self.assertEqual(state.global_position.value.altitude_m, 123)
        self.assertIsNone(state.battery.voltage_v)
        self.assertIsNone(state.battery.current_a)
        self.assertIsNone(state.battery.remaining_percent)
        self.assertEqual(state.health.quality, QualityState.DEGRADED)
        self.assertTrue(self.adapter.link_snapshot(at(20)).connected)
        self.assertFalse(self.adapter.link_snapshot(at(200)).connected)
        self.assertEqual(self.adapter.link_snapshot(at(200)).health, QualityState.UNAVAILABLE)

    def test_source_filter_skew_staleness_and_invalid_inputs(self):
        other = Message("HEARTBEAT", system=2, base_mode=128, custom_mode=4)
        self.assertFalse(self.adapter.ingest(other, captured_at=at(1), received_at=at(2)))
        self.feed("HEARTBEAT", 10, base_mode=128, custom_mode=4)
        self.feed("LOCAL_POSITION_NED", 11, x=1.0, y=2.0, z=3.0, vx=0.0, vy=0.0, vz=0.0)
        self.feed("ATTITUDE", 30, roll=0.0, pitch=0.0, yaw=0.0, rollspeed=0.0, pitchspeed=0.0, yawspeed=0.0)
        self.assertIsNone(self.adapter.publish(at(40)).reported_pose)
        self.assertEqual(self.adapter.publish(at(200)).health.quality, QualityState.INVALID)
        with self.assertRaises(ValueError):
            self.adapter.ingest(Message("LOCAL_POSITION_NED", x=0, y=0, z=0, vx=0, vy=0, vz=0),
                                captured_at=at(50), received_at=at(49))
        with self.assertRaises(ValueError):
            self.feed("LOCAL_POSITION_NED", 50, x=math.nan, y=0, z=0, vx=0, vy=0, vz=0)
        with self.assertRaises(ValueError):
            self.adapter.publish(at(90))

    def test_decoder_accepts_real_pymavlink_parsed_shape(self):
        from pymavlink import mavutil

        message = mavutil.mavlink.MAVLink_local_position_ned_message(1, 2.0, 3.0, -4.0, 5.0, 6.0, -7.0)
        fact = decode_telemetry(message)
        self.assertIsInstance(fact, LocalPositionNed)
        self.assertEqual((fact.north_m, fact.east_m, fact.down_m), (2.0, 3.0, -4.0))
        message._header.srcSystem = 1
        message._header.srcComponent = 1
        self.assertTrue(self.adapter.ingest(message, captured_at=at(10), received_at=at(11)))
        self.assertEqual(self.adapter.publish(at(12)).version.revision, 1)

    def test_adapter_has_no_connection_or_command_import(self):
        root = Path(__file__).resolve().parents[1]
        for relative in ("protocols/mavlink/telemetry.py", "vehicles/multirotor/mavlink_state.py"):
            tree = ast.parse((root / relative).read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imports.append(node.module or "")
                elif isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
            self.assertFalse(any(name.startswith(("legacy", "telemetry_link", "contracts.vehicle.command", "core.execution", "pymavlink"))
                                 for name in imports), relative)
            self.assertFalse(any(isinstance(node, ast.Attribute) and node.attr in {"send_raw_message", "mavlink_connection"}
                                 for node in ast.walk(tree)), relative)


if __name__ == "__main__":
    unittest.main()

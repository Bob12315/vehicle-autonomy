"""Rover protocol and common-runtime safety checks."""

from pathlib import Path
import unittest

from pymavlink.dialects.v20 import ardupilotmega as mavlink

from contracts.core.geometry import Pose3, Quaternion, Twist3, Vector3
from contracts.effects.vehicle import LandEffect, ModeEffect, TakeoffEffect, TwistTargetEffect
from contracts.vehicle.command import PoseTargetCommand, StopMotionCommand, TwistTargetCommand
from deployment.simulation_runtime import SimulationRuntime
from runtime.simulation_profile import SimulationProfile
from tests.test_simulation_runtime import Clock, Transport
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator
from vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
from vehicles.rover.mavlink_state import RoverTelemetryState


PROFILE = Path(__file__).resolve().parents[1] / "simulation/profiles/rover.toml"


class RoverPluginTests(unittest.TestCase):
    def setUp(self):
        self.profile = SimulationProfile.load(PROFILE)
        self.translator = ArduRoverCommandTranslator(mode_ids=self.profile.mode_ids)

    def test_rover_message_frames_and_signs(self):
        drive = self.translator.translate(TwistTargetCommand("base_link",
            Twist3(Vector3(-.5, 0, 0), Vector3(0, 0, .35)), "drive"))
        self.assertEqual((drive.frame, drive.type_mask, drive.vx, drive.yaw_rate),
                         (mavlink.MAV_FRAME_BODY_NED, 1479, -.5, -.35))
        stop = self.translator.translate(StopMotionCommand("drive"), stop_frame=drive.frame)
        self.assertEqual((stop.vx, stop.vy, stop.yaw_rate), (0, 0, 0))
        goto = self.translator.translate(PoseTargetCommand("odom",
            Pose3(Vector3(2, 1, 0), Quaternion(0, 0, 0, 1)), "goto"))
        self.assertEqual((goto.frame, goto.type_mask, goto.x, goto.y),
                         (mavlink.MAV_FRAME_LOCAL_NED, 3576, 1, 2))
        with self.assertRaises(ValueError):
            self.translator.translate(TwistTargetCommand("odom",
                Twist3(Vector3(.5, 0, 0), Vector3(0, 0, 0)), "bad"))

    def test_rover_type_and_flight_effects_fail_closed(self):
        clock = Clock()
        transport = Transport()
        with self.assertRaises(ValueError):
            SimulationRuntime(self.profile,
                translator=ArduPilotCommandTranslator(mode_ids={"GUIDED": 4}),
                transport_factory=lambda *a, **kw: transport, clock=clock)
        runtime = SimulationRuntime(self.profile, translator=self.translator,
            transport_factory=lambda *a, **kw: transport, clock=clock)
        sender = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
        runtime.connect()
        transport.incoming.append(sender.heartbeat_encode(mavlink.MAV_TYPE_GROUND_ROVER, 3, 0, 4, 4).pack(sender))
        clock.advance()
        runtime.cycle()
        self.assertIsNotNone(runtime.session_id)
        runtime.begin_run(allow_send=True)
        for effect in (TakeoffEffect(1), LandEffect()):
            self.assertEqual(runtime.submit_effect(effect).reason, "rover_flight_effect_unsupported")
        self.assertEqual(transport.writes, [])
        runtime.shutdown()

    def test_guided_drive_uses_only_fenced_writer(self):
        clock = Clock()
        transport = Transport()
        runtime = SimulationRuntime(self.profile, translator=self.translator,
            transport_factory=lambda *a, **kw: transport, clock=clock)
        sender = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
        heartbeat = sender.heartbeat_encode(mavlink.MAV_TYPE_GROUND_ROVER, 3, 128, 15, 4).pack(sender)
        state = (sender.local_position_ned_encode(0, 0, 0, 0, 0, 0, 0).pack(sender)
                 + sender.attitude_encode(0, 0, 0, 0, 0, 0, 0).pack(sender))
        runtime.connect()
        transport.incoming.append(heartbeat + state)
        clock.advance()
        runtime.cycle()
        runtime.begin_run()
        drive = TwistTargetEffect("base_link", Twist3(Vector3(.5, 0, 0), Vector3(0, 0, .35)), "drive")
        self.assertEqual(runtime.submit_effect(drive).reason, "system_send_disabled")
        self.assertEqual(transport.writes, [])
        runtime.end_run()
        runtime.begin_run(allow_send=True)
        self.assertIsNone(runtime.submit_effect(drive).reason)
        clock.advance()
        runtime.cycle()
        self.assertEqual(len(transport.writes), 1)
        parser = mavlink.MAVLink(None)
        message = None
        for byte in transport.writes[0]:
            message = parser.parse_char(bytes((byte,))) or message
        self.assertEqual(message.get_type(), "SET_POSITION_TARGET_LOCAL_NED")
        self.assertEqual((message.coordinate_frame, message.vx, round(message.yaw_rate, 2)),
                         (mavlink.MAV_FRAME_BODY_NED, .5, -.35))
        runtime.shutdown()

    def test_rover_global_position_origin_projects_to_enu(self):
        clock = Clock()
        receiver = RoverTelemetryState(vehicle_id="rover", generation_id="rover-generation",
            link_session_id="rover-link", source_system=1, source_component=1,
            max_sample_skew_ns=500_000_000, max_field_age_ns=3_000_000_000,
            link_timeout_ns=3_000_000_000)
        sender = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
        parser = mavlink.MAVLink(None)

        def feed(encoded):
            message = None
            for byte in encoded:
                message = parser.parse_char(bytes((byte,))) or message
            self.assertIsNotNone(message)
            receiver.ingest(message, captured_at=clock(), received_at=clock())

        feed(sender.gps_global_origin_encode(-353632600, 1491652000, 584000).pack(sender))
        feed(sender.global_position_int_encode(0, -353632510, 1491652110, 584000,
                                               0, 100, 50, 0, 0).pack(sender))
        feed(sender.attitude_encode(0, 0, 0, 0, 0, 0, 0).pack(sender))
        feed(sender.heartbeat_encode(mavlink.MAV_TYPE_GROUND_ROVER, 3, 0, 15, 4).pack(sender))
        state = receiver.publish(clock())
        self.assertIsNotNone(state.reported_pose)
        self.assertAlmostEqual(state.reported_pose.value.position.x, 1.0, delta=.2)
        self.assertAlmostEqual(state.reported_pose.value.position.y, 1.0, delta=.2)
        self.assertEqual((state.reported_twist.value.linear.x,
                          state.reported_twist.value.linear.y), (.5, 1.0))


if __name__ == "__main__":
    unittest.main()

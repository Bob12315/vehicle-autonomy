"""Common simulation loop: authority, telemetry, writer and session epochs."""

from datetime import datetime, timezone
from pathlib import Path
import unittest

from pymavlink.dialects.v20 import ardupilotmega as mavlink

from contracts.core.geometry import Twist3, Vector3
from contracts.core.time import TimePoint
from contracts.effects.vehicle import ModeEffect, TwistTargetEffect
from deployment.simulation_runtime import SimulationRuntime
from runtime.simulation_profile import SimulationProfile
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator


PROFILE = Path(__file__).resolve().parents[1] / "simulation/profiles/copter.toml"


class Clock:
    def __init__(self):
        self.ns = 1_000_000_000

    def __call__(self):
        return TimePoint(self.ns, datetime(2026, 1, 1, tzinfo=timezone.utc),
                         "host-monotonic-simulation")

    def advance(self):
        self.ns += 100_000_000


class Transport:
    def __init__(self):
        self.incoming = []
        self.writes = []
        self.disconnected = False
        self.closed = False

    def read(self, max_bytes=4096):
        if self.disconnected:
            raise ConnectionError("test disconnect")
        return self.incoming.pop(0) if self.incoming else None

    def write(self, data):
        self.writes.append(data)

    def close(self):
        self.closed = True


class SimulationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.transports = []
        self.sender = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
        profile = SimulationProfile.load(PROFILE)
        self.runtime = SimulationRuntime(profile,
            translator=ArduPilotCommandTranslator(mode_ids=profile.mode_ids),
            transport_factory=self.make_transport, clock=self.clock)

    def make_transport(self, host, port, *, timeout_s):
        self.assertEqual((host, port), ("127.0.0.1", 5760))
        transport = Transport()
        self.transports.append(transport)
        return transport

    def heartbeat(self, mode=0, armed=False):
        return self.sender.heartbeat_encode(mavlink.MAV_TYPE_QUADROTOR, 3,
                                            128 if armed else 0, mode, 4).pack(self.sender)

    def state_messages(self):
        return (self.sender.local_position_ned_encode(0, 0, 0, 0, 0, 0, 0).pack(self.sender)
                + self.sender.attitude_encode(0, 0, 0, 0, 0, 0, 0).pack(self.sender))

    def cycle(self, data=None):
        self.clock.advance()
        if data is not None:
            self.transports[-1].incoming.append(data)
        return self.runtime.cycle()

    def test_mode_requires_explicit_send_then_ack_and_later_heartbeat(self):
        self.runtime.connect()
        self.cycle(self.heartbeat() + self.state_messages())
        self.runtime.begin_run()
        denied = self.runtime.submit_effect(ModeEffect("GUIDED"), effect_id="denied")
        self.assertEqual(denied.reason, "system_send_disabled")
        self.assertEqual(self.transports[0].writes, [])
        self.runtime.end_run()
        self.runtime.begin_run(allow_send=True)
        approved = self.runtime.submit_effect(ModeEffect("GUIDED"), effect_id="mode")
        self.assertIsNone(approved.reason)
        self.assertEqual(self.runtime.submit_effect(ModeEffect("GUIDED"), effect_id="mode"), approved)
        with self.assertRaises(ValueError):
            self.runtime.submit_effect(ModeEffect("LOITER"), effect_id="mode")
        self.cycle()
        self.assertEqual(len(self.transports[0].writes), 1)
        self.assertEqual(self.runtime.effect_status("mode")["phase"], "TRANSMITTED")
        self.cycle(self.sender.command_ack_encode(mavlink.MAV_CMD_DO_SET_MODE, 0).pack(self.sender))
        self.assertEqual(self.runtime.effect_status("mode")["phase"], "ACKNOWLEDGED")
        self.cycle(self.heartbeat(mode=4))
        self.assertEqual(self.runtime.effect_status("mode")["phase"], "COMPLETED")
        self.runtime.shutdown()
        self.assertTrue(self.transports[0].closed)

    def test_motion_needs_pose_and_reconnect_does_not_replay(self):
        self.runtime.connect()
        self.cycle(self.heartbeat(mode=4, armed=True))
        old_session = self.runtime.session_id
        self.runtime.begin_run(allow_send=True)
        motion = TwistTargetEffect("base_link", Twist3(Vector3(.5, 0, 0), Vector3(0, 0, 0)), "drive")
        self.assertEqual(self.runtime.submit_effect(motion, effect_id="missing").reason,
                         "motion_state_unavailable")
        self.cycle(self.state_messages())
        self.assertIsNone(self.runtime.submit_effect(motion, effect_id="ready").reason)
        self.cycle()
        self.assertEqual(len(self.transports[0].writes), 1)
        self.transports[0].disconnected = True
        self.cycle()
        self.assertFalse(self.runtime.authority.system_send)
        self.assertFalse(self.runtime.authority.action_send)
        self.assertTrue(self.transports[0].closed)
        self.runtime.connect()
        self.cycle(self.heartbeat() + self.state_messages())
        self.assertNotEqual(self.runtime.session_id, old_session)
        self.assertEqual(self.transports[1].writes, [])
        self.runtime.begin_run()
        self.assertEqual(self.runtime.submit_effect(ModeEffect("GUIDED"), effect_id="new").reason,
                         "system_send_disabled")
        self.assertEqual(self.transports[1].writes, [])
        self.runtime.shutdown()

    def test_cancelled_motion_writes_zero_and_waits_for_new_stop_state(self):
        self.runtime.connect()
        self.cycle(self.heartbeat(mode=4, armed=True) + self.state_messages())
        self.runtime.begin_run(allow_send=True)
        motion = TwistTargetEffect("base_link", Twist3(Vector3(.5, 0, 0), Vector3(0, 0, 0)), "drive")
        self.assertIsNone(self.runtime.submit_effect(motion, effect_id="motion").reason)
        self.cycle()
        self.assertEqual(len(self.transports[0].writes), 1)

        def supply_stop_state(_seconds):
            self.clock.advance()
            self.transports[0].incoming.append(self.state_messages())

        self.runtime._sleep = supply_stop_state
        self.assertEqual(self.runtime.end_run(), {"drive": "CONFIRMED"})
        self.assertEqual(len(self.transports[0].writes), 2)
        decoded = mavlink.MAVLink(None)
        messages = [decoded.parse_char(bytes((byte,))) for byte in self.transports[0].writes[-1]]
        stop = next(message for message in messages if message is not None)
        self.assertEqual((stop.vx, stop.vy, stop.vz, stop.yaw_rate), (0, 0, 0, 0))
        self.assertFalse(self.runtime.authority.system_send)
        self.runtime.shutdown()


if __name__ == "__main__":
    unittest.main()

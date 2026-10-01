"""Source freshness must survive RX delay and epoch changes."""
from datetime import datetime, timezone
import unittest
from pymavlink.dialects.v20 import ardupilotmega as mav
from contracts.core.time import TimePoint
from deployment.simulation_clock import SimulationSourceClock


class SourceClockTests(unittest.TestCase):
    def received(self, ns):
        return TimePoint(ns, datetime(2026, 10, 2, tzinfo=timezone.utc), 'simulation-test')

    def test_delayed_and_repeated_source_remain_old(self):
        for kind in ('pose', 'attitude'):
            with self.subTest(kind=kind):
                sender = mav.MAVLink(None)
                message = (sender.local_position_ned_encode(1000, 0, 0, 0, 0, 0, 0)
                           if kind == 'pose' else sender.attitude_encode(1000, 0, 0, 0, 0, 0, 0))
                clock = SimulationSourceClock()
                self.assertEqual(clock.capture(message, self.received(10_000_000_000)).monotonic_ns, 10_000_000_000)
                message.time_boot_ms = 1100
                captured = clock.capture(message, self.received(13_600_000_000))
                self.assertEqual(captured.monotonic_ns, 10_100_000_000)
                self.assertEqual(self.received(13_600_000_000).elapsed_ns_since(captured), 3_500_000_000)
                self.assertEqual(clock.capture(message, self.received(14_000_000_000)).monotonic_ns, captured.monotonic_ns)

    def test_regression_future_and_new_epoch(self):
        sender = mav.MAVLink(None)
        message = sender.global_position_int_encode(1000, 0, 0, 0, 0, 0, 0, 0, 0)
        clock = SimulationSourceClock()
        clock.capture(message, self.received(10_000_000_000))
        message.time_boot_ms = 999
        with self.assertRaises(ValueError):
            clock.capture(message, self.received(10_100_000_000))
        clock = SimulationSourceClock()
        message.time_boot_ms = 1000
        clock.capture(message, self.received(10_000_000_000))
        message.time_boot_ms = 2000
        with self.assertRaises(ValueError):
            clock.capture(message, self.received(10_100_000_000))
        message.time_boot_ms = 1
        fresh = SimulationSourceClock().capture(message, self.received(20_000_000_000))
        self.assertEqual(fresh.monotonic_ns, 20_000_000_000)

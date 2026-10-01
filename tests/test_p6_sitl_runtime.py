"""Offline end-to-end P6 control and failure behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pymavlink.dialects.v20 import ardupilotmega as mavlink

from contracts.core.time import TimePoint
from contracts.vehicle.command import ArmCommand, ModeCommand
from deployment.sitl_runtime import SitlRuntime, run_sitl
from protocols.mavlink.constants import TYPE_QUADROTOR, CMD_SET_MODE
from runtime.sitl import SitlProfile
from vehicles.multirotor.sitl_guard import SitlModeTranslator


PROFILE = Path(__file__).resolve().parents[1] / "runtime" / "sitl.toml"


class Clock:
    def __init__(self):
        self.ns = 1_000_000_000

    def __call__(self):
        return TimePoint(self.ns, datetime(2026, 1, 1, tzinfo=timezone.utc), "sitl-host")

    def advance(self, ns=100_000_000):
        self.ns += ns


class Transport:
    def __init__(self):
        self.incoming = []
        self.writes = []
        self.closed = False
        self.disconnect = False
        self.fail_write = False

    def read(self, max_bytes=4096):
        if self.disconnect:
            raise ConnectionError("lost")
        return self.incoming.pop(0) if self.incoming else None

    def write(self, data):
        if self.fail_write:
            raise ConnectionError("uncertain")
        self.writes.append(data)

    def close(self):
        self.closed = True


class P6SitlRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.transport = Transport()
        self.sender = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
        self.profile = SitlProfile.load(PROFILE)

    def heartbeat(self, *, mode=0, armed=False):
        return self.sender.heartbeat_encode(TYPE_QUADROTOR, 3, 128 if armed else 0,
                                             mode, 4).pack(self.sender)

    def ack(self):
        return self.sender.command_ack_encode(CMD_SET_MODE, 0).pack(self.sender)

    def make_runtime(self, allow_send=True):
        runtime = SitlRuntime(self.profile, allow_send=allow_send,
                              transport=self.transport, clock=self.clock)
        self.transport.incoming.append(self.heartbeat())
        runtime.cycle()
        runtime.start_mission()
        self.clock.advance()
        return runtime

    def test_start_without_heartbeat_reports_missing_state(self):
        runtime = SitlRuntime(self.profile, transport=self.transport, clock=self.clock)
        with self.assertRaisesRegex(RuntimeError, "fresh SITL vehicle state required"):
            runtime.start_mission()
        runtime.shutdown()

    def test_ack_and_later_unarmed_mode_state_required_for_success(self):
        runtime = self.make_runtime()
        self.assertEqual(runtime.cycle()["status"], "RUNNING")
        self.assertEqual(len(self.transport.writes), 1)
        effect = next(iter(runtime.get_status()["effects"].values()))
        self.assertEqual(effect["phase"], "TRANSMITTED")
        self.clock.advance()
        self.transport.incoming.append(self.ack())
        self.assertEqual(runtime.cycle()["status"], "RUNNING")
        self.assertEqual(len(self.transport.writes), 1)
        self.clock.advance()
        self.transport.incoming.append(self.heartbeat(mode=4))
        self.assertEqual(runtime.cycle()["status"], "RUNNING")
        self.clock.advance()
        self.assertEqual(runtime.cycle()["status"], "EXITING")
        self.clock.advance()
        self.assertEqual(runtime.cycle()["status"], "SUCCEEDED")
        self.assertEqual(len(self.transport.writes), 1)
        self.assertEqual(next(iter(runtime.get_status()["effects"].values()))["phase"], "COMPLETED")
        runtime.shutdown()
        self.assertTrue(self.transport.closed)

    def test_default_send_disabled_rejects_without_write(self):
        runtime = self.make_runtime(allow_send=False)
        runtime.cycle()
        self.assertEqual(self.transport.writes, [])
        self.assertEqual(next(iter(runtime.get_status()["effects"].values()))["reason"],
                         "system_send_disabled")
        self.clock.advance()
        runtime.cycle()
        self.clock.advance()
        self.assertEqual(runtime.cycle()["status"], "FAILED")
        runtime.shutdown()

    def test_uncertain_write_never_replays_after_reconnect(self):
        runtime = self.make_runtime()
        self.transport.fail_write = True
        runtime.cycle()
        self.assertEqual(next(iter(runtime.get_status()["effects"].values()))["phase"], "UNKNOWN")
        self.assertEqual(self.transport.writes, [])
        self.transport.fail_write = False
        self.clock.advance()
        self.transport.incoming.append(self.heartbeat())
        runtime.cycle()
        self.clock.advance()
        self.assertEqual(runtime.cycle()["status"], "FAILED")
        self.assertEqual(self.transport.writes, [])
        runtime.shutdown()

    def test_disconnect_revokes_and_does_not_replay_old_effect(self):
        runtime = self.make_runtime()
        runtime.cycle()
        self.transport.disconnect = True
        self.clock.advance()
        status = runtime.cycle()
        self.assertEqual(status["status"], "FAILED")
        self.assertIsNone(status["link_session_id"])
        self.assertFalse(runtime.authority.system_send)
        self.assertEqual(len(self.transport.writes), 1)
        self.transport.disconnect = False
        self.transport.incoming.append(self.heartbeat())
        self.clock.advance()
        runtime.cycle()
        self.assertEqual(len(self.transport.writes), 1)
        runtime.shutdown()

    def test_stale_state_cycle_delay_cancel_and_shutdown(self):
        runtime = self.make_runtime()
        runtime.cycle()
        self.clock.advance(3_500_000_000)
        self.assertEqual(runtime.cycle()["status"], "FAILED")
        self.assertFalse(runtime.authority.system_send)
        runtime.shutdown()
        runtime2 = self.make_runtime()
        runtime2.cycle()
        runtime2.cancel_mission()
        self.assertEqual(len(self.transport.writes), 2)
        self.clock.advance()
        runtime2.cycle()
        self.assertIn(runtime2.get_status()["status"], ("CANCELLED", "EXITING"))
        runtime2.shutdown()

    def test_stale_state_and_expired_effect_are_distinct(self):
        profile = replace(self.profile, link_timeout_ns=5_000_000_000)
        runtime = SitlRuntime(profile, allow_send=True,
                              transport=self.transport, clock=self.clock)
        self.transport.incoming.append(self.heartbeat())
        runtime.cycle()
        runtime.start_mission()
        self.clock.advance(3_500_000_000)
        runtime._last_cycle = self.clock()
        self.assertEqual(runtime.cycle()["error"], "vehicle_state_stale")
        runtime.shutdown()

        self.setUp()
        runtime = self.make_runtime()
        original = runtime._execution.dispatch
        runtime._execution.dispatch = lambda envelope, world, now: original(
            envelope, world, TimePoint(now.monotonic_ns + 6_000_000_000,
                                       now.utc, now.clock_domain_id))
        runtime.cycle()
        self.assertEqual(self.transport.writes, [])
        self.assertEqual(next(iter(runtime.get_status()["effects"].values()))["reason"],
                         "invalid_effect_time")
        runtime.shutdown()

    def test_final_translation_and_write_guard_reject_arm_and_armed_state(self):
        translator = SitlModeTranslator(mode_ids={"GUIDED": 4})
        with self.assertRaisesRegex(ValueError, "only a mode"):
            translator.translate(ArmCommand())
        runtime = SitlRuntime(self.profile, allow_send=True,
                              transport=self.transport, clock=self.clock)
        self.transport.incoming.append(self.heartbeat(armed=True))
        runtime.cycle()
        self.assertEqual(runtime._write_guard(SimpleNamespace(command=ModeCommand("GUIDED"))),
                         "vehicle_armed")
        runtime.shutdown()

    def test_config_rejects_non_loopback_missing_safety_and_invalid_period(self):
        source = PROFILE.read_text()
        for replacement in (
            source.replace('host = "127.0.0.1"', 'host = "192.0.2.1"'),
            source.replace("[safety]", "[unsafe]"),
            source.replace("period_ns = 100000000", "period_ns = 2000000000"),
            source.replace('vehicle_type = "ARDUCOPTER_QUADROTOR"', 'vehicle_type = "ROVER"'),
        ):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "profile.toml"
                path.write_text(replacement)
                with self.assertRaises(ValueError):
                    SitlProfile.load(path)

    def test_cancel_then_start_new_run_uses_new_effect_and_lease(self):
        runtime = self.make_runtime()
        first_run = runtime.get_status()["run_id"]
        runtime.cancel_mission()
        self.clock.advance()
        runtime.cycle()
        self.transport.incoming.append(self.heartbeat())
        self.clock.advance()
        runtime.cycle()
        self.assertEqual(runtime.get_status()["status"], "CANCELLED")
        runtime.start_mission()
        self.assertNotEqual(runtime.get_status()["run_id"], first_run)
        self.clock.advance()
        runtime.cycle()
        self.assertEqual(len(self.transport.writes), 1)
        runtime.shutdown()

    def test_inflight_cancel_requires_new_session(self):
        runtime = self.make_runtime()
        runtime.cycle()
        runtime.cancel_mission()
        self.clock.advance()
        runtime.cycle()
        with self.assertRaisesRegex(RuntimeError, "new link session"):
            runtime.start_mission()
        runtime.shutdown()

    def test_ctrl_c_cancels_and_closes(self):
        class InterruptedRuntime:
            def __init__(self):
                self.calls = 0
                self.cancelled = False
                self.closed = False

            def cycle(self):
                self.calls += 1
                if self.calls > 1:
                    raise KeyboardInterrupt

            def get_status(self):
                return {"vehicle_quality": "VALID", "status": "CANCELLED" if self.cancelled else "RUNNING"}

            def start_mission(self):
                return self.get_status()

            def cancel_mission(self):
                self.cancelled = True

            def shutdown(self):
                self.closed = True

        fake = InterruptedRuntime()
        with patch("deployment.sitl_runtime.SitlRuntime", return_value=fake):
            self.assertEqual(run_sitl(self.profile)["status"], "CANCELLED")
        self.assertTrue(fake.cancelled)
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()

"""SITL-only mode, arm and disarm Mission closure."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from pymavlink.dialects.v20 import ardupilotmega as mavlink

from contracts.vehicle.command import ArmCommand, DisarmCommand, TakeoffCommand
from contracts.core.quality import QualityState
from deployment.sitl_runtime import SitlRuntime
from protocols.mavlink.constants import CMD_ARM_DISARM, CMD_SET_MODE, TYPE_QUADROTOR
from runtime.sitl import SitlProfile
from tests.test_p6_sitl_runtime import Clock, Transport
from vehicles.multirotor.sitl_guard import SitlArmTranslator, sitl_arm_write_guard


ARM_PROFILE = Path(__file__).resolve().parents[1] / "runtime" / "sitl_arm.toml"


class SitlArmMissionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.transport = Transport()
        self.sender = mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
        self.profile = SitlProfile.load(ARM_PROFILE)

    def heartbeat(self, *, mode=0, armed=False):
        return self.sender.heartbeat_encode(TYPE_QUADROTOR, 3, 128 if armed else 0,
                                             mode, 4).pack(self.sender)

    def ack(self):
        return self.sender.command_ack_encode(CMD_SET_MODE, 0).pack(self.sender)

    def make_runtime(self):
        runtime = SitlRuntime(self.profile, allow_send=True, allow_arm=True,
                              arm_then_disarm=True, transport=self.transport,
                              clock=self.clock)
        self.transport.incoming.append(self.heartbeat())
        runtime.cycle()
        runtime.start_mission()
        return runtime

    def cycle(self, runtime, *, mode=4, armed=False, heartbeat=True):
        self.clock.advance()
        if heartbeat:
            self.transport.incoming.append(self.heartbeat(mode=mode, armed=armed))
        return runtime.cycle()

    def advance_until_writes(self, runtime, count, *, armed=False):
        for _ in range(10):
            self.cycle(runtime, armed=armed)
            if len(self.transport.writes) == count:
                return
        self.fail(f"expected {count} writes; got {len(self.transport.writes)}")

    def test_permission_and_translator_restrict_scope_before_connection(self):
        with self.assertRaisesRegex(ValueError, "explicit SEND"):
            SitlRuntime(self.profile, arm_then_disarm=True, allow_send=False,
                        allow_arm=True, transport=self.transport, clock=self.clock)
        translator = SitlArmTranslator(mode_ids={"GUIDED": 4})
        self.assertIsNotNone(translator.translate(ArmCommand()))
        self.assertIsNotNone(translator.translate(DisarmCommand()))
        with self.assertRaisesRegex(ValueError, "only mode, arm and disarm"):
            translator.translate(TakeoffCommand(1.0))
        state = SimpleNamespace(
            health=SimpleNamespace(quality=QualityState.VALID),
            operation=SimpleNamespace(armed=False, native_mode="ARDUPILOT_CUSTOM_0"),
        )
        self.assertEqual(sitl_arm_write_guard(SimpleNamespace(command=ArmCommand()), state,
                                              "GUIDED", 4), "target_mode_required")
        self.assertEqual(sitl_arm_write_guard(SimpleNamespace(command=DisarmCommand()), state,
                                              "GUIDED", 4), "already_disarmed")

    def test_mode_then_arm_then_disarm_needs_ack_and_later_state_for_each(self):
        runtime = self.make_runtime()
        self.cycle(runtime, mode=0)
        self.assertEqual(len(self.transport.writes), 1)
        self.transport.incoming.append(self.ack())
        self.cycle(runtime, mode=0, heartbeat=False)
        self.assertEqual(runtime.get_status()["step_id"], "mode")
        self.advance_until_writes(runtime, 2)
        self.assertEqual(runtime.get_status()["step_id"], "arm")
        self.assertEqual(runtime.authority.lease.action_instance_id,
                         f"{runtime.get_status()['run_id']}:arm:1")
        self.transport.incoming.append(self.sender.command_ack_encode(CMD_ARM_DISARM, 0).pack(self.sender))
        self.cycle(runtime, heartbeat=False)
        self.assertEqual(runtime.get_status()["step_id"], "arm")
        self.advance_until_writes(runtime, 3, armed=True)
        self.assertEqual(runtime.get_status()["step_id"], "disarm")
        self.transport.incoming.append(self.sender.command_ack_encode(CMD_ARM_DISARM, 0).pack(self.sender))
        self.cycle(runtime, heartbeat=False)
        for _ in range(10):
            status = self.cycle(runtime, armed=False)
            if status["status"] == "SUCCEEDED":
                break
        self.assertEqual(status["status"], "SUCCEEDED")
        self.assertFalse(status["armed"])
        self.assertEqual(len(self.transport.writes), 3)
        self.assertEqual([item["phase"] for item in status["effects"].values()],
                         ["COMPLETED", "COMPLETED", "COMPLETED"])
        runtime.shutdown()

    def test_arm_rejection_never_advances_to_disarm_or_success(self):
        runtime = self.make_runtime()
        self.cycle(runtime, mode=0)
        self.transport.incoming.append(self.ack())
        self.cycle(runtime, mode=0, heartbeat=False)
        self.advance_until_writes(runtime, 2)
        self.transport.incoming.append(self.sender.command_ack_encode(CMD_ARM_DISARM, 4).pack(self.sender))
        self.cycle(runtime, heartbeat=False)
        for _ in range(4):
            status = self.cycle(runtime, armed=False)
            if status["status"] == "FAILED":
                break
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(len(self.transport.writes), 2)
        self.assertFalse(status["armed"])
        runtime.shutdown()

    def test_cancel_after_arm_uses_fenced_disarm_cleanup(self):
        runtime = self.make_runtime()
        self.cycle(runtime, mode=0)
        self.transport.incoming.append(self.ack())
        self.cycle(runtime, mode=0, heartbeat=False)
        self.advance_until_writes(runtime, 2)
        self.transport.incoming.append(self.sender.command_ack_encode(CMD_ARM_DISARM, 0).pack(self.sender))
        self.cycle(runtime, heartbeat=False)
        for _ in range(5):
            status = self.cycle(runtime, armed=True)
            if status["effects"] and list(status["effects"].values())[-1]["phase"] == "COMPLETED":
                break
        self.assertTrue(status["armed"])
        runtime.cancel_mission()

        original_write = self.transport.write
        original_read = self.transport.read
        cleanup_written = False
        ack_read = False

        def write(data):
            nonlocal cleanup_written
            original_write(data)
            cleanup_written = True
            self.transport.incoming.append(
                self.sender.command_ack_encode(CMD_ARM_DISARM, 0).pack(self.sender))

        def read(max_bytes=4096):
            nonlocal ack_read
            self.clock.advance()
            chunk = original_read(max_bytes)
            if cleanup_written and chunk is not None and not ack_read:
                ack_read = True
                self.transport.incoming.append(self.heartbeat(mode=4, armed=False))
            return chunk

        self.transport.write = write
        self.transport.read = read
        final = runtime.shutdown()
        self.assertEqual(final["disarm_cleanup"], "CONFIRMED")
        self.assertFalse(final["armed"])
        self.assertEqual(len(self.transport.writes), 3)

    def test_link_loss_while_armed_reports_unconfirmed_cleanup(self):
        runtime = self.make_runtime()
        self.cycle(runtime, mode=0)
        self.transport.incoming.append(self.ack())
        self.cycle(runtime, mode=0, heartbeat=False)
        self.advance_until_writes(runtime, 2)
        self.transport.incoming.append(self.sender.command_ack_encode(CMD_ARM_DISARM, 0).pack(self.sender))
        self.cycle(runtime, heartbeat=False)
        self.cycle(runtime, armed=True)
        self.transport.disconnect = True
        final = runtime.shutdown()
        self.assertEqual(final["disarm_cleanup"], "UNCONFIRMED_LINK_LOST")
        self.assertEqual(len(self.transport.writes), 2)

    def test_unknown_arm_write_is_not_reported_disarmed_confirmed(self):
        runtime = self.make_runtime()
        self.cycle(runtime, mode=0)
        self.transport.incoming.append(self.ack())
        self.cycle(runtime, mode=0, heartbeat=False)
        for _ in range(5):
            status = self.cycle(runtime, armed=False)
            if list(status["effects"].values())[-1]["phase"] == "COMPLETED":
                break
        self.transport.fail_write = True
        for _ in range(6):
            status = self.cycle(runtime, armed=False)
            if len(status["effects"]) == 2:
                break
        self.assertEqual(list(status["effects"].values())[-1]["phase"], "UNKNOWN")
        self.transport.fail_write = False
        self.cycle(runtime, armed=False)
        self.cycle(runtime, armed=False)
        final = runtime.shutdown()
        self.assertEqual(final["disarm_cleanup"], "UNCONFIRMED_ARM_OUTCOME")
        self.assertEqual(len(self.transport.writes), 1)


if __name__ == "__main__":
    unittest.main()

"""Deterministic fault matrix at the real runtime/codec/writer boundary."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import unittest

from pymavlink.dialects.v20 import ardupilotmega as mav

from contracts.core.geometry import Twist3, Vector3
from contracts.core.primitives import SchemaVersion
from contracts.core.time import TimePoint
from contracts.effects.vehicle import ArmEffect, EffectEnvelope, ModeEffect, TwistTargetEffect
from contracts.vehicle.command import CancelCommandRequest, CommandPhase
from core.control_authority import ControlLease
from deployment.simulation_runtime import SimulationRuntime
from protocols.mavlink.codec import MavlinkCodec
from runtime.simulation_profile import SimulationProfile
from vehicles.multirotor.ardupilot_commands import ArduPilotCommandTranslator
from vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator


ROOT = Path(__file__).resolve().parents[2]


class Clock:
    def __init__(self):
        self.ns = 10_000_000_000
        self.domain = "host-monotonic-simulation"

    def __call__(self):
        return TimePoint(self.ns, datetime(2026, 10, 2, tzinfo=timezone.utc), self.domain)


class FaultTransport:
    def __init__(self):
        self.incoming = []
        self.writes = []
        self.attempts = []
        self.disconnected = False
        self.fail_write = False
        self.closed = False

    def read(self, max_bytes=4096):
        if self.disconnected:
            raise ConnectionError("injected link cut")
        return self.incoming.pop(0) if self.incoming else None

    def write(self, data):
        self.attempts.append(data)
        if self.fail_write:
            raise OSError("injected partial/uncertain write")
        self.writes.append(data)

    def close(self):
        self.closed = True


class Rig:
    def __init__(self, kind):
        self.kind = kind
        self.clock = Clock()
        self.profile = SimulationProfile.load(ROOT / f"simulation/profiles/{kind}.toml")
        self.transports = []
        self.sender = mav.MAVLink(None, srcSystem=1, srcComponent=1)
        self.events = []
        translator = (ArduRoverCommandTranslator if kind == "rover" else ArduPilotCommandTranslator)(
            mode_ids=self.profile.mode_ids)
        self.runtime = SimulationRuntime(self.profile, translator=translator, clock=self.clock,
            transport_factory=self.transport, event_sink=self.events.append,
            sleep=lambda _: self.supply_zero())
        self.runtime.connect()
        self.step(self.heartbeat() + self.position(origin=True))

    def transport(self, *args, **kwargs):
        transport = FaultTransport()
        self.transports.append(transport)
        return transport

    @property
    def wire(self):
        return self.transports[-1]

    def heartbeat(self, *, mode=None, armed=True, vehicle_type=None):
        mode = self.profile.mode_ids["GUIDED"] if mode is None else mode
        return self.sender.heartbeat_encode(vehicle_type or self.profile.mav_type, 3,
                                            128 if armed else 0, mode, 4).pack(self.sender)

    def position(self, *, origin=False, speed=0.0):
        data = b""
        boot_ms = self.clock.ns // 1_000_000
        if self.kind == "rover":
            if origin:
                data += self.sender.gps_global_origin_encode(-353632620, 1491652370, 584000).pack(self.sender)
            data += self.sender.global_position_int_encode(boot_ms, -353632620, 1491652370,
                584000, 0, 0, int(speed * 100), 0, 0).pack(self.sender)
        else:
            data += self.sender.local_position_ned_encode(boot_ms, 0, 0, 0, 0, speed, 0).pack(self.sender)
        return data + self.sender.attitude_encode(boot_ms, 0, 0, 0, 0, 0, 0).pack(self.sender)

    def step(self, data=None, *, advance=100_000_000):
        self.clock.ns += advance
        if data is not None:
            self.wire.incoming.append(data)
        return self.runtime.cycle()

    def fresh(self, *, speed=0.0):
        return self.step(self.heartbeat() + self.position(speed=speed))

    def start(self, *, allow_send=True):
        self.runtime.begin_run(allow_send=allow_send)

    def motion(self, name="motion"):
        return self.runtime.submit_effect(TwistTargetEffect("base_link",
            Twist3(Vector3(.4, 0, 0), Vector3(0, 0, 0)), "drive"), effect_id=name)

    def supply_zero(self):
        self.clock.ns += 100_000_000
        self.wire.incoming.append(self.heartbeat() + self.position())

    def close(self):
        if self.runtime._session is not None:
            self.runtime._close_link("fixture_cleanup")
        self.runtime.shutdown()


class DualVehicleFaultTests(unittest.TestCase):
    def each(self):
        for kind in ("copter", "rover"):
            rig = Rig(kind)
            self.addCleanup(rig.close)
            yield rig

    def test_unauthorized_all_gates_and_wrong_lease_scope_zero_tx(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start(allow_send=False)
                self.assertEqual(rig.motion("default").reason, "system_send_disabled")
                rig.runtime.end_run()
                rig.start()
                rig.runtime.authority.set_action_send(False)
                self.assertEqual(rig.motion("action-off").reason, "action_send_disabled")
                rig.runtime.authority.set_action_send(True)
                rig.runtime.authority.revoke()
                rig.runtime.authority.set_action_send(True)
                self.assertEqual(rig.motion("no-lease").reason, "no_lease")
                expiry = replace(rig.clock(), monotonic_ns=rig.clock.ns + 10_000_000_000)
                rig.runtime.authority.grant(ControlLease("wrong", "wrong-run", "wrong-action", expiry), rig.clock())
                rig.runtime.authority.set_action_send(True)
                self.assertEqual(rig.motion("wrong-scope").reason, "lease_scope_mismatch")
                self.assertEqual(rig.wire.writes, [])

    def test_duplicate_effect_exactly_one_write_and_conflict_rejected(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                first = rig.motion("same")
                self.assertEqual(rig.motion("same"), first)
                with self.assertRaises(ValueError):
                    rig.runtime.submit_effect(ArmEffect(), effect_id="same")
                rig.fresh()
                self.assertEqual(len(rig.wire.writes), 1)

    def test_expired_effect_rejected_without_wire_output(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                created = replace(rig.clock(), monotonic_ns=rig.clock.ns - 200_000_000)
                deadline = replace(rig.clock(), monotonic_ns=rig.clock.ns - 100_000_000)
                effect = EffectEnvelope(SchemaVersion(1, 0), "expired", rig.runtime._run_id,
                    rig.runtime._action_id, created, deadline, ArmEffect())
                result = rig.runtime._execution.dispatch(effect, rig.runtime.world_snapshot(), rig.clock())
                self.assertEqual(result.reason, "invalid_effect_time")
                rig.fresh()
                self.assertEqual(rig.wire.writes, [])

    def test_temporary_disconnect_reconnect_and_old_queue_isolation(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                old_session = rig.runtime.session_id
                rig.motion("queued-old")
                old_wire = rig.wire
                old_wire.disconnected = True
                self.assertIsNotNone(rig.step().fault)
                self.assertFalse(rig.runtime.authority.system_send)
                self.assertFalse(rig.runtime.authority.action_send)
                self.assertIsNone(rig.runtime.authority.lease)
                self.assertEqual(rig.runtime.effect_status("queued-old")["phase"], "REJECTED")
                rig.runtime.connect()
                rig.step(rig.heartbeat() + rig.position(origin=True))
                self.assertNotEqual(rig.runtime.session_id, old_session)
                rig.start(allow_send=False)
                self.assertEqual(rig.motion("new-readonly").reason, "system_send_disabled")
                self.assertEqual(old_wire.writes + rig.wire.writes, [])

    def test_long_disconnect_heartbeat_timeout_is_unknown_and_no_physical_claim(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                rig.motion()
                rig.fresh(speed=.4)
                for _ in range(32):
                    result = rig.step()
                    if result.fault:
                        break
                self.assertIsNotNone(result.fault)
                self.assertEqual(rig.runtime.end_run(), {"drive": "UNCONFIRMED"})
                self.assertTrue(rig.wire.closed)
                self.assertFalse(rig.runtime.authority.system_send)

    def test_state_timeout_retaining_heartbeat_blocks_motion(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                for _ in range(32):
                    result = rig.step(rig.heartbeat())
                    if result.fault:
                        break
                self.assertEqual(result.fault, "vehicle_state_or_link_stale")
                self.assertIsNone(rig.runtime.world_snapshot().vehicle)
                self.assertEqual(rig.wire.writes, [])
                with self.assertRaises(RuntimeError):
                    rig.motion("after-stale")

    def test_telemetry_stale_all_rx_closes_authorization(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                for _ in range(32):
                    result = rig.step()
                    if result.fault:
                        break
                self.assertIsNotNone(result.fault)
                self.assertEqual(rig.wire.writes, [])
                self.assertFalse(rig.runtime.authority.system_send)
                self.assertFalse(rig.runtime.authority.action_send)

    def test_ack_timeout_does_not_complete_from_state_or_retry_arm(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                rig.runtime.submit_effect(ArmEffect(), effect_id="arm")
                rig.fresh()
                for _ in range(51):
                    rig.fresh()
                self.assertEqual(rig.runtime.effect_status("arm")["phase"], "UNKNOWN")
                self.assertIn("ack_timeout", rig.runtime.effect_status("arm")["reason"])
                rig.runtime.submit_effect(ArmEffect(), effect_id="explicit-new-arm")
                rig.fresh()
                self.assertEqual(len(rig.wire.writes), 1)

    def test_command_state_timeout_after_ack_is_unknown(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                target = "HOLD" if rig.kind == "rover" else "LOITER"
                rig.runtime.submit_effect(ModeEffect(target), effect_id="mode")
                rig.fresh()
                ack = rig.sender.command_ack_encode(mav.MAV_CMD_DO_SET_MODE, 0).pack(rig.sender)
                rig.step(ack + rig.heartbeat() + rig.position())
                self.assertEqual(rig.runtime.effect_status("mode")["phase"], "ACKNOWLEDGED")
                for _ in range(51):
                    rig.fresh()
                self.assertEqual(rig.runtime.effect_status("mode")["phase"], "UNKNOWN")
                self.assertIn("state_confirmation_timeout", rig.runtime.effect_status("mode")["reason"])

    def test_deadman_transmits_zero_then_requires_new_state(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                rig.motion()
                rig.fresh(speed=.4)
                for _ in range(11):
                    rig.fresh(speed=.4)
                status = rig.runtime._execution.stop_status("drive")
                self.assertEqual(status.state.value, "TRANSMITTED")
                self.assertEqual(len(rig.wire.writes), 2)
                codec = MavlinkCodec(source_system=1, source_component=1, target_system=250, target_component=191)
                stop = codec.feed(rig.wire.writes[-1])[0]
                self.assertEqual((stop.vx, stop.vy, stop.vz, stop.yaw_rate), (0, 0, 0, 0))
                rig.fresh()
                self.assertEqual(rig.runtime._execution.stop_status("drive").state.value, "CONFIRMED")

    def test_cancel_before_write_and_cancel_motion_after_transmit(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                result = rig.runtime.submit_effect(ArmEffect(), effect_id="queued-arm")
                rig.runtime._port.cancel(CancelCommandRequest(result.receipt.command_id, rig.clock()))
                rig.fresh()
                self.assertEqual(rig.wire.writes, [])
                rig.motion()
                rig.fresh(speed=.4)
                rig.supply_zero()
                result = rig.runtime.end_run()
                self.assertEqual(result, {"drive": "CONFIRMED"})
                self.assertEqual(len(rig.wire.writes), 2)
                self.assertFalse(rig.runtime.authority.system_send)

    def test_interrupted_velocity_uncertain_write_revokes_and_never_replays(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                rig.motion()
                rig.wire.fail_write = True
                result = rig.fresh(speed=.4)
                self.assertEqual(result.fault, "transport_write_uncertain")
                self.assertEqual(rig.runtime.effect_status("motion")["phase"], "UNKNOWN")
                self.assertFalse(rig.runtime.authority.system_send)
                self.assertIsNone(rig.runtime.authority.lease)
                rig.runtime.connect()
                rig.step(rig.heartbeat() + rig.position(origin=True))
                self.assertEqual(rig.wire.attempts, [])

    def test_cycle_deadline_and_clock_regression_close_link(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                rig.motion()
                self.assertEqual(rig.step(advance=300_000_000).fault, "cycle_deadline_missed")
                self.assertEqual(rig.wire.writes, [])
                rig.runtime.connect()
                rig.step(rig.heartbeat() + rig.position(origin=True))
                rig.start()
                rig.clock.ns -= 1
                self.assertEqual(rig.runtime.cycle().fault, "cycle_clock_regressed")
                self.assertFalse(rig.runtime.authority.system_send)

    def test_runtime_restart_defaults_readonly_and_shutdown_confirms_stop(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                rig.motion()
                rig.fresh(speed=.4)
                rig.supply_zero()
                self.assertEqual(rig.runtime.shutdown(), {"drive": "CONFIRMED"})
                self.assertTrue(rig.wire.closed)
                self.assertFalse(rig.runtime.authority.system_send)
                restarted = Rig(rig.kind)
                self.addCleanup(restarted.close)
                self.assertFalse(restarted.runtime.authority.system_send)
                self.assertFalse(restarted.runtime.authority.action_send)
                self.assertIsNone(restarted.runtime.authority.lease)
                self.assertEqual(restarted.wire.writes, [])

    def test_future_wrong_domain_stale_state_rejected_before_motion(self):
        for rig in self.each():
            with self.subTest(vehicle=rig.kind):
                rig.start()
                world = rig.runtime.world_snapshot()
                for label, delta, domain in (("future", 1, rig.clock.domain),
                                             ("stale", -4_000_000_000, rig.clock.domain),
                                             ("wrong-domain", 0, "foreign-clock")):
                    captured = replace(rig.clock(), monotonic_ns=rig.clock.ns + delta,
                                       clock_domain_id=domain)
                    state = replace(world.vehicle,
                        reported_pose=replace(world.vehicle.reported_pose, captured_at=captured),
                        reported_twist=replace(world.vehicle.reported_twist, captured_at=captured))
                    effect = EffectEnvelope(SchemaVersion(1, 0), label, rig.runtime._run_id,
                        rig.runtime._action_id, rig.clock(),
                        replace(rig.clock(), monotonic_ns=rig.clock.ns + 1_000_000_000),
                        TwistTargetEffect("base_link", Twist3(Vector3(.4, 0, 0), Vector3(0, 0, 0)), label))
                    result = rig.runtime._execution.dispatch(effect, replace(world, vehicle=state), rig.clock())
                    self.assertIsNotNone(result.reason)
                self.assertEqual(rig.wire.writes, [])


if __name__ == "__main__":
    unittest.main()

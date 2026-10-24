"""Cancellation and Action/session fences for latched native vehicle motion."""
import unittest

from pymavlink.dialects.v20 import ardupilotmega as mav
from vehicle_autonomy.contracts.core.geometry import GeoPoint
from vehicle_autonomy.contracts.effects.vehicle import FixedWingTargetEffect, ModeEffect
from tests import test_plane_control, test_rover_native_rtl
from tests.test_simulation_runtime import Transport


def authority_scope(runtime):
    a = runtime.authority
    return (runtime._action_id, a.lease, a.authorization_generation,
            a.send_generation, a.system_send, a.action_send)


class NativeRecoveryBoundaryTests(unittest.TestCase):
    def fixture(self, kind):
        case = (test_plane_control.PlaneControlTests() if kind == 'plane'
                else test_rover_native_rtl.RoverNativeRtlTests())
        case.setUp()
        self.addCleanup(case.tearDown)
        return case if kind == 'plane' else case.f

    def test_plane_cancellation_cancels_queued_target_and_rtl_before_recovery_write(self):
        for effect in (FixedWingTargetEffect(GeoPoint(-35.363262, 149.165237, 634)), ModeEffect('RTL')):
            with self.subTest(effect=type(effect).__name__):
                f = self.fixture('plane')
                f.begin(mode=12, armed=True, height=50, speed=17)
                self.assertIsNone(f.runtime.submit_effect(effect, effect_id='queued').reason)
                self.assertEqual(f.transport.writes, [])
                def advance(seconds):
                    frame = mav.MAVLink(None).parse_buffer(f.transport.writes[-1])[0]
                    f.feed(mode=int(frame.param2) if frame.command == 176 else 15,
                           armed=True, height=50, speed=17, ack=frame.command)
                f.runtime._sleep = advance
                self.assertEqual(f.runtime.end_run(), {'fixed-wing-flight': 'UNCONFIRMED'})
                frames = [mav.MAVLink(None).parse_buffer(raw)[0] for raw in f.transport.writes]
                self.assertEqual([(m.command, m.param2) for m in frames], [(176, 12)])
                self.assertEqual(f.runtime.effect_status('queued')['phase'], 'CANCELLED')
                self.assertTrue(f.runtime.world_snapshot().vehicle.operation.armed)

    def test_rover_cancellation_cancels_queued_rtl_before_hold_write(self):
        f = self.fixture('rover')
        f.begin(mode=15, armed=True, speed=.5)
        self.assertIsNone(f.runtime.submit_effect(ModeEffect('RTL'), effect_id='queued').reason)
        self.assertEqual(f.transport.writes, [])
        def advance(seconds):
            frame = mav.MAVLink(None).parse_buffer(f.transport.writes[-1])[0]
            f.feed(mode=int(frame.param2), armed=True, speed=0, ack=176)
        f.runtime._sleep = advance
        self.assertEqual(f.runtime.end_run(), {'native-rover-rtl': 'CONFIRMED'})
        frames = [mav.MAVLink(None).parse_buffer(raw)[0] for raw in f.transport.writes]
        self.assertEqual([(m.command, m.param2) for m in frames], [(176, 4)])
        self.assertEqual(f.runtime.effect_status('queued')['phase'], 'CANCELLED')
        self.assertEqual(f.runtime.world_snapshot().vehicle.operation.native_mode, 'ARDUPILOT_CUSTOM_4')

    def test_plane_transmitted_takeoff_blocks_action_handoff_without_mutating_authority(self):
        f = self.fixture('plane')
        f._transmit_takeoff_on_stationary_ground()
        before = authority_scope(f.runtime)
        with self.assertRaisesRegex(RuntimeError, 'stop barrier'):
            f.runtime.authorize_action('replacement', allow_send=True)
        self.assertEqual(authority_scope(f.runtime), before)
        self.assertEqual(len(f.transport.writes), 1)
        # Refusing a handoff must not suppress valid current-Action confirmation.
        f.feed(mode=13, armed=True, ack=176)
        self.assertEqual(f.runtime.effect_status('takeoff-exit')['phase'], 'COMPLETED')
        self.assertTrue(f.runtime.world_snapshot().vehicle.operation.armed)
        self.assertEqual(len(f.transport.writes), 1)

    def test_rover_native_rtl_blocks_action_handoff_without_mutating_authority(self):
        f = self.fixture('rover')
        f.begin(mode=15, armed=True, speed=.5)
        f.runtime.submit_effect(ModeEffect('RTL'), effect_id='rtl')
        f.feed(mode=15, armed=True, speed=.5)
        before = authority_scope(f.runtime)
        with self.assertRaisesRegex(RuntimeError, 'stop barrier'):
            f.runtime.authorize_action('replacement', allow_send=True)
        self.assertEqual(authority_scope(f.runtime), before)
        f.feed(mode=11, armed=True, speed=.5, ack=176)
        self.assertEqual(f.runtime.effect_status('rtl')['phase'], 'COMPLETED')
        self.assertEqual(len(f.transport.writes), 1)

    def reconnect_read_only(self, kind):
        f = self.fixture(kind)
        is_plane = kind == 'plane'
        mode = 12 if is_plane else 11
        state = dict(armed=True, height=50 if is_plane else 0, speed=17 if is_plane else .5)
        f.begin(mode=mode, **state)
        f.runtime.submit_effect(ModeEffect('LOITER' if is_plane else 'RTL'), effect_id='native')
        f.feed(mode=mode, **state)
        f.feed(mode=mode, ack=176, **state)
        old_session = f.runtime.session_id
        old_transport = f.transport
        f.runtime._close_link('test_loss')
        f.transport = Transport()
        f.origin_sent = False
        f.runtime.connect()
        f.feed(mode=mode, **state)
        self.assertNotEqual(f.runtime.session_id, old_session)
        self.assertEqual(str(f.runtime.world_snapshot().vehicle.telemetry.link_session_id), f.runtime.session_id)
        self.assertTrue(f.runtime.world_snapshot().vehicle.operation.armed)
        self.assertFalse(f.runtime.authority.system_send)
        self.assertFalse(f.runtime.authority.action_send)
        self.assertIsNone(f.runtime.authority.lease)
        self.assertEqual(f.runtime.shutdown(), {
            'fixed-wing-flight' if is_plane else 'native-rover-rtl': 'UNCONFIRMED'})
        self.assertEqual(f.transport.writes, [])
        self.assertEqual(len(old_transport.writes), 1)
        self.assertEqual(f.runtime.effect_status('native')['phase'], 'COMPLETED')

    def test_plane_read_only_reconnect_preserves_negative_flight_uncertainty(self):
        self.reconnect_read_only('plane')

    def test_rover_read_only_reconnect_preserves_negative_rtl_uncertainty(self):
        self.reconnect_read_only('rover')

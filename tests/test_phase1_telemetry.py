"""Phase-one diagnostic contracts must not manufacture control freshness."""
from dataclasses import replace
import math
import unittest

from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.vehicle.telemetry import TelemetryAvailability as A
from vehicle_autonomy.vehicles.ardupilot.telemetry_state import ArduPilotTelemetryState
from tests.test_mavlink_state_adapter import Message, at


class Phase1TelemetryTests(unittest.TestCase):
    def adapter(self, session='session-a'):
        return ArduPilotTelemetryState(vehicle_id='test', generation_id=session,
            link_session_id=session, source_system=1, source_component=1,
            max_sample_skew_ns=10, max_field_age_ns=100, link_timeout_ns=100)

    def test_missing_unknown_capture_and_query_age_are_explicit(self):
        state = self.adapter()
        empty = state.telemetry_snapshot(at(1))
        self.assertTrue(all(f.availability is A.MISSING and f.value is None for f in empty.fields))
        state.ingest(Message('HEARTBEAT', base_mode=128, custom_mode=4, type=2, autopilot=3,
                             system_status=4), captured_at=at(10), received_at=at(11))
        snap = state.publish(at(12))
        hb = snap.telemetry.field('HEARTBEAT')
        self.assertEqual(hb.availability, A.UNKNOWN_CAPTURE_TIME)
        self.assertIsNone(hb.captured_at)
        self.assertTrue(hb.value.armed)
        self.assertEqual(hb.value.mav_type, 2)
        stale = state.telemetry_snapshot(at(200)).field('HEARTBEAT')
        self.assertEqual(stale.availability, A.STALE)
        self.assertFalse(stale.receive_fresh)
        self.assertEqual(state.snapshot().published_at, at(12))
        self.assertEqual(to_json_value(snap)['telemetry']['link_session_id'], 'session-a')
        self.assertEqual(snap.schema_version.minor, 1)

    def test_duplicate_and_reordered_payloads_never_refresh_sensor_state(self):
        state = self.adapter()
        def feed(capture, receive, x):
            return state.ingest(Message('LOCAL_POSITION_NED', x=x, y=2., z=-3., vx=4., vy=5., vz=-6.),
                                captured_at=at(capture), received_at=at(receive))
        self.assertTrue(feed(10, 11, 1.))
        self.assertFalse(feed(10, 50, 999.))
        self.assertFalse(feed(9, 60, 999.))
        sample = state.telemetry_snapshot(at(70)).field('LOCAL_POSITION_NED')
        self.assertEqual(sample.value.position_enu_m.y, 1.)
        self.assertEqual(sample.value.velocity_enu_mps.z, 6.)
        self.assertEqual((sample.duplicates, sample.out_of_order), (1, 1))
        self.assertEqual(sample.received_at, at(11))
        self.assertEqual(state.telemetry_snapshot(at(111)).field('LOCAL_POSITION_NED').availability, A.STALE)

    def test_frd_angular_rates_and_global_velocity_normalize(self):
        state = self.adapter()
        state.ingest(Message('ATTITUDE', roll=.1, pitch=.2, yaw=.3, rollspeed=1., pitchspeed=2., yawspeed=3.),
                     captured_at=at(10), received_at=at(11))
        attitude = state.telemetry_snapshot(at(12)).field('ATTITUDE').value
        self.assertEqual((attitude.angular_velocity_flu_rad_s.x, attitude.angular_velocity_flu_rad_s.y,
                          attitude.angular_velocity_flu_rad_s.z), (1., -2., -3.))
        q = attitude.orientation_flu_enu
        self.assertAlmostEqual(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w, 1.)
        state.ingest(Message('GLOBAL_POSITION_INT', lat=0, lon=0, alt=1000, vx=100, vy=200, vz=-300),
                     captured_at=at(13), received_at=at(14))
        global_ = state.telemetry_snapshot(at(15)).field('GLOBAL_POSITION_INT').value
        self.assertEqual((global_.velocity_enu_mps.x, global_.velocity_enu_mps.y, global_.velocity_enu_mps.z), (2., 1., 3.))
        self.assertIsNone(global_.position_enu_m)
        self.assertEqual(global_.geographic.altitude_m, 1.)

    def test_ekf_power_ack_text_are_typed_with_unknown_sampling(self):
        state = self.adapter()
        for message in (
            Message('EKF_STATUS_REPORT', flags=19, velocity_variance=.1, pos_horiz_variance=.2,
                    pos_vert_variance=.3, compass_variance=.4, terrain_alt_variance=.5),
            Message('SYS_STATUS', voltage_battery=12000, current_battery=230, battery_remaining=80),
            Message('POWER_STATUS', Vcc=5000, Vservo=0, flags=1),
            Message('COMMAND_ACK', command=176, result=0, progress=255),
            Message('STATUSTEXT', severity=4, text=b'Warning\0', id=2, chunk_seq=1),
        ):
            state.ingest(message, captured_at=at(10), received_at=at(11))
        view = state.telemetry_snapshot(at(12))
        self.assertEqual(view.field('EKF_STATUS_REPORT').value.flags, 19)
        self.assertEqual(view.field('SYS_STATUS').value.voltage_v, 12.)
        self.assertEqual(view.field('POWER_STATUS').value.reported_5v_rail_v, 5.)
        self.assertEqual(view.field('POWER_STATUS').value.reported_servo_rail_v, 0.)
        self.assertIsNone(view.field('COMMAND_ACK').value.progress_percent)
        text = view.field('STATUSTEXT')
        self.assertEqual(text.value.text, 'Warning')
        self.assertEqual(text.value.chunk_sequence, 1)  # no invented complete multi-chunk string
        self.assertEqual(text.availability, A.UNKNOWN_CAPTURE_TIME)

    def test_invalid_telemetry_is_visible_and_fail_closed(self):
        state = self.adapter()
        with self.assertRaises(ValueError):
            state.ingest(Message('ATTITUDE', roll=math.nan, pitch=0., yaw=0.,
                                 rollspeed=0., pitchspeed=0., yawspeed=0.), captured_at=at(10), received_at=at(11))
        sample = state.telemetry_snapshot(at(12)).field('ATTITUDE')
        self.assertEqual(sample.availability, A.INVALID)
        self.assertEqual(sample.invalid, 1)
        self.assertIsNone(sample.value)
        with self.assertRaises(ValueError):
            state.ingest(Message('GLOBAL_POSITION_INT', lat=910000000, lon=0, alt=0),
                         captured_at=at(13), received_at=at(14))

    def test_unknown_sensor_time_and_source_filter_and_new_epoch(self):
        state = self.adapter()
        gps = Message('GPS_RAW_INT', fix_type=3, satellites_visible=255, eph=65535, epv=65535)
        state.observe_telemetry(gps, captured_at=None, received_at=at(10))
        sample = state.telemetry_snapshot(at(11)).field('GPS_RAW_INT')
        self.assertEqual(sample.availability, A.UNKNOWN_CAPTURE_TIME)
        self.assertIsNone(sample.value.hdop)
        other = Message('HEARTBEAT', system=2, base_mode=128, custom_mode=4)
        self.assertFalse(state.ingest(other, captured_at=at(12), received_at=at(13)))
        self.assertEqual(state.telemetry_snapshot(at(14)).field('HEARTBEAT').observations, 0)
        fresh = self.adapter('session-b').telemetry_snapshot(at(20))
        self.assertEqual(fresh.link_session_id, 'session-b')
        self.assertTrue(all(f.availability is A.MISSING for f in fresh.fields))

    def test_motion_history_keeps_each_qualified_sample_in_a_receive_batch(self):
        state=self.adapter()
        for i in range(132):
            stamp=10+i*2
            state.ingest(Message('ATTITUDE',roll=0.,pitch=0.,yaw=i*.001,rollspeed=0.,pitchspeed=0.,yawspeed=0.),
                captured_at=at(stamp),received_at=at(stamp+1))
            state.ingest(Message('LOCAL_POSITION_NED',x=float(i),y=2.,z=-3.,vx=0.,vy=0.,vz=0.),
                captured_at=at(stamp),received_at=at(stamp+1))
        history=state.motion_history()
        self.assertEqual(history.link_session_id,'session-a')
        self.assertEqual(len(history.positions),128);self.assertEqual(len(history.attitudes),128)
        self.assertEqual(history.positions[0].captured_at,at(18))
        self.assertEqual(history.positions[-1].value.y,131.)
        self.assertFalse(state.ingest(Message('ATTITUDE',roll=1.,pitch=1.,yaw=1.,rollspeed=0.,pitchspeed=0.,yawspeed=0.),
            captured_at=at(272),received_at=at(280)))
        self.assertEqual(state.motion_history(),history)
        # Publishing/querying cannot append synthesized attitude samples.
        state.publish(at(281));state.telemetry_snapshot(at(282))
        self.assertEqual(state.motion_history(),history)
        self.assertFalse(self.adapter('new-session').motion_history().attitudes)

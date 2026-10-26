import unittest
from tests import test_p5_mavlink as fixtures
from pymavlink.dialects.v20 import ardupilotmega as mav
from vehicle_autonomy.vehicles.ardupilot.mavlink.codec import TimesyncQuery
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect

class TimesyncWriterTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.P5MavlinkTests();self.f.setUp();self.f.connect()
    def test_shared_actual_sequence_with_queued_control_and_no_gate_grant(self):
        f=self.f;f.authority.set_system_send(False);f.authority.set_action_send(False)
        f.port.write_timesync(123)
        self.assertFalse(f.authority.system_send);self.assertFalse(f.authority.action_send)
        f.authority.set_system_send(True);f.authority.set_action_send(True)
        receipt=f.execution.dispatch(fixtures.effect(1,ArmEffect()),fixtures.world(),fixtures.at(100)).receipt
        f.now_ns=101;f.port.write_next();f.port.write_timesync(124)
        frames=[m for data in f.transport.writes for m in mav.MAVLink(None).parse_buffer(data) or []]
        self.assertEqual([m.get_type() for m in frames],['TIMESYNC','COMMAND_LONG','TIMESYNC'])
        self.assertEqual([m.get_seq() for m in frames],[0,1,2])
        self.assertEqual(f.port.wire_attempted_bytes,sum(map(len,f.transport.writes)))
    def test_disconnected_bad_query_and_failed_transport_do_not_allow_more_writes(self):
        f=self.f
        with self.assertRaises(ValueError):f.port.write_timesync(-1)
        self.assertEqual(f.transport.writes,[])
        f.transport.fail_write=True
        with self.assertRaises(ConnectionError):f.port.write_timesync(1)
        before=len(f.transport.attempts)
        with self.assertRaises(ConnectionError):f.port.write_timesync(2)
        self.assertEqual(len(f.transport.attempts),before)
        f=self.f=fixtures.P5MavlinkTests();f.setUp()
        with self.assertRaises(ConnectionError):f.port.write_timesync(1)
        self.assertEqual(f.transport.writes,[])

    def test_due_queries_cannot_starve_valid_control_even_with_slow_caller(self):
        from types import SimpleNamespace
        f=self.f;nonce=iter(range(1,20))
        f.session._time_sync=SimpleNamespace(request_due=lambda _:next(nonce),sent=lambda *args:None)
        f.session._clock=lambda:fixtures.at(f.now_ns)
        f.execution.dispatch(fixtures.effect(1,ArmEffect()),fixtures.world(),fixtures.at(100))
        f.session.write_next(fixtures.at(100));f.now_ns=101;f.session.write_next(fixtures.at(101))
        frames=[m for data in f.transport.writes for m in mav.MAVLink(None).parse_buffer(data) or []]
        self.assertEqual([m.get_type() for m in frames],['TIMESYNC','COMMAND_LONG'])
        self.assertEqual(len(f.transport.attempts),2)

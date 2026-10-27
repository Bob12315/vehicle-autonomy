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

    def test_control_ack_has_priority_and_source_queries_resume_before_state(self):
        from types import SimpleNamespace
        f=self.f;nonce=iter(range(1,20))
        f.session._time_sync=SimpleNamespace(request_due=lambda _:next(nonce),sent=lambda *args:None,observe=lambda *args:None)
        f.session._clock=lambda:fixtures.at(f.now_ns)
        receipt=f.execution.dispatch(fixtures.effect(1,ArmEffect()),fixtures.world(),fixtures.at(100)).receipt
        f.session.write_next(fixtures.at(100));f.now_ns=101;f.session.write_next(fixtures.at(101))
        self.assertEqual(len(f.transport.attempts),1)
        f.transport.incoming.append(f.ack(400));f.session.poll(fixtures.at(102))
        self.assertEqual(f.port.status(receipt.command_id).phase.value,'ACKNOWLEDGED')
        self.assertTrue(f.port.protocol_query_slot_available)
        f.now_ns=103;f.session.write_next(fixtures.at(103))
        f.transport.incoming.append(f.heartbeat(armed=True));f.session.poll(fixtures.at(104))
        self.assertEqual(f.port.status(receipt.command_id).phase.value,'COMPLETED')
        frames=[m for data in f.transport.writes for m in mav.MAVLink(None).parse_buffer(data) or []]
        self.assertEqual([m.get_type() for m in frames],['COMMAND_LONG','TIMESYNC'])
        self.assertEqual(len(f.transport.attempts),2)

    def test_optional_clock_io_is_bounded_without_changing_existing_profile(self):
        from tests import test_simulation_runtime as simulation
        from tests.mavlink_fixture import receive_signing
        for enabled,expected in ((False,.05),(True,.01)):
            with self.subTest(source_time_sync=enabled):
                profile=simulation.SimulationProfile.load(simulation.PROFILE);timeouts=[]
                def connect(host,port,*,timeout_s):
                    timeouts.append(timeout_s);return simulation.Transport()
                runtime=simulation.SimulationRuntime(profile,translator=simulation.ArduPilotCommandTranslator(mode_ids=profile.mode_ids),transport_factory=connect,clock=simulation.Clock(),receive_signing=receive_signing(),source_time_sync=enabled,time_sync_uart_baud=115200 if enabled else None)
                try:
                    runtime.connect();self.assertEqual(timeouts,[expected])
                    self.assertEqual(runtime.profile.period_ns,100_000_000)
                    self.assertFalse(runtime.authority.system_send);self.assertFalse(runtime.authority.action_send)
                    self.assertIsNone(runtime.authority.lease)
                finally:runtime.shutdown()

    def test_stream_setpoints_do_not_starve_clock_and_share_actual_writer_order(self):
        from types import SimpleNamespace
        from vehicle_autonomy.contracts.effects.vehicle import TwistTargetEffect
        from vehicle_autonomy.contracts.core.geometry import Twist3,Vector3
        f=self.f;nonce=iter(range(1,20));f.now_ns=101
        f.session._time_sync=SimpleNamespace(request_due=lambda _:next(nonce),sent=lambda *args:None,observe=lambda *args:None)
        f.session._clock=lambda:fixtures.at(f.now_ns)
        target=TwistTargetEffect('base_link',Twist3(Vector3(.01,0,0),Vector3(0,0,0)),'native-stream')
        receipt=f.execution.dispatch(fixtures.effect(1,target),fixtures.world(),fixtures.at(101)).receipt
        self.assertTrue(f.port.protocol_query_slot_available)
        f.session.write_next(fixtures.at(101));f.now_ns=102;f.session.write_next(fixtures.at(102))
        frames=[m for data in f.transport.writes for m in mav.MAVLink(None).parse_buffer(data) or []]
        self.assertEqual([m.get_type() for m in frames],['TIMESYNC','SET_POSITION_TARGET_LOCAL_NED'])
        self.assertEqual([m.get_seq() for m in frames],[0,1]);self.assertEqual(len(f.transport.attempts),2)

    def test_actual_tcp_connection_disables_small_frame_batching(self):
        import socket
        from vehicle_autonomy.vehicles.ardupilot.transports.bytes import TcpByteTransport
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1)
        try:
            transport=TcpByteTransport.connect('127.0.0.1',listener.getsockname()[1],timeout_s=.05)
            peer,_=listener.accept()
            try:
                self.assertEqual(transport._connection.getsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY),1)
                transport.write(b'one-frame');self.assertEqual(peer.recv(128),b'one-frame')
                peer.sendall(b'reply');self.assertEqual(transport.read(),b'reply')
                self.assertFalse(hasattr(transport,'submit'))
            finally:transport.close();peer.close()
        finally:listener.close()

    def test_idle_cycle_cannot_consume_control_priority_after_actual_query(self):
        from types import SimpleNamespace
        from vehicle_autonomy.contracts.effects.vehicle import TwistTargetEffect
        from vehicle_autonomy.contracts.core.geometry import Twist3,Vector3
        f=self.f;nonce=iter((1,None,2,3))
        f.session._time_sync=SimpleNamespace(request_due=lambda _:next(nonce),sent=lambda *args:None)
        f.session._clock=lambda:fixtures.at(f.now_ns)
        f.now_ns=101;f.session.write_next(fixtures.at(101))
        f.now_ns=102;self.assertIsNone(f.session.write_next(fixtures.at(102)))
        self.assertEqual(len(f.transport.attempts),1)
        target=TwistTargetEffect('base_link',Twist3(Vector3(.01,0,0),Vector3(0,0,0)),'native-stream')
        f.now_ns=103;f.execution.dispatch(fixtures.effect(1,target),fixtures.world(),fixtures.at(103))
        f.session.write_next(fixtures.at(103))
        frames=[m for data in f.transport.writes for m in mav.MAVLink(None).parse_buffer(data) or []]
        self.assertEqual([m.get_type() for m in frames],['TIMESYNC','SET_POSITION_TARGET_LOCAL_NED'])
        f.now_ns=104;f.session.write_next(fixtures.at(104))
        frames=[m for data in f.transport.writes for m in mav.MAVLink(None).parse_buffer(data) or []]
        self.assertEqual([m.get_type() for m in frames],['TIMESYNC','SET_POSITION_TARGET_LOCAL_NED','TIMESYNC'])
        self.assertEqual([m.get_seq() for m in frames],[0,1,2])
        self.assertEqual(len(f.transport.attempts),3)

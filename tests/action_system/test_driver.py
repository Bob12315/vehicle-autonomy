"""Driver admission and exit using the actual signed in-memory AP composition."""
from concurrent.futures import Future
from threading import RLock
import unittest

from vehicle_autonomy.app.bootstrap.action_driver import VehicleActionDriver
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected
from vehicle_autonomy.contracts.core.primitives import SchemaVersion
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect,EffectEnvelope,ModeEffect
from tests import test_simulation_runtime as simulation_tests
from tests.mavlink_fixture import pack


class Proof:
    def assert_alive(self):pass


class DriverTests(unittest.TestCase):
    def test_string_false_cannot_enable_deployment_send_or_open_transport(self):
        with self.assertRaises(TypeError):VehicleActionDriver('bad',None,None,None,allow_send='false')
    def setUp(self):
        self.fixture=simulation_tests.SimulationRuntimeTests();self.fixture.setUp()
        self.r=self.fixture.runtime;self.r.connect();self.fixture.cycle(self.fixture.heartbeat(mode=4)+self.fixture.state_messages())
        d=self.d=VehicleActionDriver.__new__(VehicleActionDriver)
        d.target='copter';d.profile=self.r.profile;d.ownership=Proof();d.allow_send=True;d._runtime=self.r;d.clock=self.fixture.clock
        d._lock=RLock();d._scope=None;d._effects={};d._results={};d._effect_sessions={};d._requested_scopes=set();d._cancelled=set();d._guards={};d._fault=None;d._world=None
        def task(function):
            f=Future()
            try:f.set_result(function())
            except Exception as exc:f.set_exception(exc)
            return f
        d._task=task;d._publish()
    def tearDown(self):self.r.shutdown()
    def deadline(self,ns=5_000_000_000):
        from dataclasses import replace
        return replace(self.d.clock(),monotonic_ns=self.d.clock().monotonic_ns+ns)
    def open(self,identifier='a',**kw):return self.d.open_scope(identifier,allow_send=kw.get('allow_send',True),continuation_of=None,deadline=kw.get('deadline',self.deadline()))
    def test_default_gate_deadline_and_cancelled_admission_have_zero_writes(self):
        for kw in ({'allow_send':False},{'deadline':self.deadline(-1)}):
            with self.assertRaises(ActionAdmissionRejected):self.open(**kw).result()
        self.d.begin_exit('cancelled')
        with self.assertRaises(ActionAdmissionRejected):self.open('cancelled').result()
        self.assertEqual(self.fixture.transports[0].writes,[])
        self.open('valid').result();self.assertTrue(self.r.authority.system_send)
    def test_read_query_exit_cannot_revoke_motion_authority(self):
        self.open().result();lease=self.r.authority.lease
        self.d._task=lambda _:(_ for _ in ()).throw(AssertionError('Query occupied vehicle queue'))
        self.d.begin_exit('query')
        self.assertTrue(self.d.finish_scope('query',succeeded=True).result().release_safe)
        self.assertEqual(self.r.authority.lease,lease);self.assertTrue(self.r.authority.system_send)
        self.assertEqual(self.fixture.transports[0].writes,[])
    def test_dispatch_publishes_post_writer_cut_and_preserves_unknown_arm(self):
        self.open().result();now=self.d.clock()
        e=EffectEnvelope(SchemaVersion(1,0),'arm','a','a',now,self.deadline(),ArmEffect())
        self.d.emit('a',e,cleanup=False).result()
        self.assertEqual(self.d.effect_results('a'),());self.assertEqual(self.fixture.transports[0].writes,[])
        self.fixture.cycle(self.fixture.heartbeat(mode=4)+self.fixture.state_messages());self.d._publish()
        self.assertEqual(len(self.fixture.transports[0].writes),1)
        self.assertEqual(self.d.effect_results('a')[0].phase.value,'TRANSMITTED')
        self.d.begin_exit('a');safety=self.d.finish_scope('a',succeeded=False).result()
        self.assertFalse(safety.release_safe);self.assertFalse(self.r.authority.system_send)
        self.assertEqual(len(self.fixture.transports[0].writes),1)
    def test_normal_signed_mode_scope_releases_after_completed_evidence(self):
        self.open().result();now=self.d.clock()
        self.d.emit('a',EffectEnvelope(SchemaVersion(1,0),'mode','a','a',now,self.deadline(),ModeEffect('GUIDED')),cleanup=False).result()
        self.fixture.cycle(self.fixture.heartbeat(mode=4)+self.fixture.state_messages())
        self.fixture.cycle(pack(self.fixture.sender.command_ack_encode(176,0),self.fixture.sender))
        self.fixture.cycle(self.fixture.heartbeat(mode=4));self.d._publish()
        self.assertEqual(self.d.effect_results('a')[0].phase.value,'COMPLETED')
        self.d.begin_exit('a');self.assertTrue(self.d.finish_scope('a',succeeded=True).result().release_safe)
        self.assertEqual(len(self.fixture.transports[0].writes),1)
    def test_cleanup_cannot_reissue_arm_or_motion_after_action_cancellation(self):
        self.open().result();self.d.begin_exit('a');now=self.d.clock()
        with self.assertRaises(RuntimeError):
            self.d.emit('a',EffectEnvelope(SchemaVersion(1,0),'late-arm','a','a',now,self.deadline(),ArmEffect()),cleanup=True).result()
        self.assertEqual(self.fixture.transports[0].writes,[])
    def test_historical_effect_keeps_original_session_across_link_loss_and_reconnect(self):
        self.open().result();now=self.d.clock();original=self.r.session_id
        self.d.emit('a',EffectEnvelope(SchemaVersion(1,0),'arm','a','a',now,self.deadline(),ArmEffect()),cleanup=False).result()
        self.fixture.cycle(self.fixture.heartbeat(mode=4)+self.fixture.state_messages());self.d._publish()
        self.fixture.transports[-1].disconnected=True;self.fixture.cycle();self.d._publish()
        self.assertEqual(self.d.effect_results('a')[0].link_session_id,original)
        self.assertEqual(self.d.effect_results('a')[0].phase.value,'UNKNOWN')
        self.r.connect();self.fixture.cycle(self.fixture.heartbeat(mode=4)+self.fixture.state_messages());self.d._publish()
        self.assertNotEqual(self.r.session_id,original)
        self.assertEqual(self.d.effect_results('a')[0].link_session_id,original)
        self.assertEqual(self.d.effect_results('a')[0].phase.value,'UNKNOWN')
        self.assertEqual(sum(len(t.writes) for t in self.fixture.transports),1)


if __name__=='__main__':unittest.main()

"""Payload queue, final authorization fence, observed completion and irreversibility."""
from dataclasses import replace
import unittest
from contracts.core.geometry import Vector3
from contracts.core.primitives import SchemaVersion
from contracts.core.quality import QualityState
from contracts.core.stamped import Stamped
from contracts.effects.payload import ReleasePayloadEffect,PayloadEffectEnvelope
from core.control_authority import ControlAuthority,ControlLease
from core.payload_execution import PayloadExecution,PayloadSafetyPolicy
from infrastructure.simulation.payload import SimPayloadPort
from world_model.models import WorldObject
from tests import test_basic_actions as helpers
from tests.test_payload_contracts import Reader

class PayloadExecutionTests(unittest.TestCase):
    def setUp(self):
        self.h=helpers.BasicActionTests();self.h.setUp();self.world=self.h.sample(.1,Vector3(2,1,1.5));self.now=self.world.published_at
        obj=WorldObject('sim.objects:test:target_1','bucket_1',Stamped('odom',self.now,Vector3(2,1,.05)),1.,QualityState.VALID,'obs','sim.objects:test')
        self.world=replace(self.world,objects=(obj,));self.reader=Reader(self.world)
        self.authority=ControlAuthority();self.authority.set_link_session('link');self.authority.set_system_send(True)
        self.authority.grant(ControlLease('lease','run','action',replace(self.now,monotonic_ns=self.now.monotonic_ns+10_000_000_000)),self.now);self.authority.set_action_send(True)
        self.port=SimPayloadPort();self.execution=PayloadExecution(self.authority,self.port,PayloadSafetyPolicy(('sim.objects:',)),self.reader)
        effect=ReleasePayloadEffect('sim_payload_1',obj.object_id,str(obj.producer_id),'obs',obj.position.value,self.now,self.world.environment)
        self.envelope=PayloadEffectEnvelope(SchemaVersion(1,0),'effect','run','action',self.now,replace(self.now,monotonic_ns=self.now.monotonic_ns+2_000_000_000),effect)
    def tearDown(self):self.h.tearDown()
    def later(self):return replace(self.now,monotonic_ns=self.now.monotonic_ns+100_000_000)
    def test_ack_waits_for_independent_world_observation_and_duplicate_inventory(self):
        self.assertEqual(self.execution.dispatch(self.envelope,self.now)['phase'],'ACCEPTED')
        self.execution.tick(self.now);self.assertEqual(self.execution.status('effect')['phase'],'ACKNOWLEDGED')
        self.assertEqual(len(self.port.commands),1)
        self.execution.dispatch(self.envelope,self.now);self.execution.tick(self.now);self.assertEqual(len(self.port.commands),1)
        observation=self.port.poll(self.later())[0]
        marker=WorldObject(self.port.producer+':'+str(observation.data.object_id),observation.data.label,Stamped('odom',observation.captured_at,observation.data.position),1.,QualityState.VALID,observation.observation_id,observation.producer_id)
        self.reader.value=replace(self.world,published_at=self.later(),objects=self.world.objects+(marker,))
        self.execution.tick(self.later());self.assertEqual(self.execution.status('effect')['phase'],'COMPLETED')
        other=replace(self.envelope,effect_id='second');self.execution.dispatch(other,self.now);self.execution.tick(self.now)
        self.assertEqual(self.execution.status('second')['phase'],'REJECTED');self.assertEqual(len(self.port.released),1)
    def test_final_fence_cancel_and_unsafe_target(self):
        for change in ('send','lease','session','target','cancel'):
            with self.subTest(change=change):
                self.setUp()
                self.execution.dispatch(self.envelope,self.now)
                if change=='send':self.authority.set_action_send(False)
                elif change=='lease':self.authority.revoke()
                elif change=='session':self.authority.set_link_session('new')
                elif change=='target':self.reader.value=replace(self.world,objects=())
                else:self.execution.cancel('run')
                self.execution.tick(self.later());self.assertFalse(self.port.released)
                self.assertIn(self.execution.status('effect')['phase'],('REJECTED','CANCELLED'))
                self.h.tearDown()
    def test_rejection_staleness_alignment_and_untrusted_sources(self):
        cases=[replace(self.world,objects=()),self.h.sample(.1,Vector3(0,0,1.5)),replace(self.world,environment=None),replace(self.world,objects=(replace(self.world.objects[0],position=Stamped('map',self.now,Vector3(2,1,.05))),))]
        for world in cases:
            self.reader.value=world
            self.assertEqual(self.execution.dispatch(replace(self.envelope,effect_id='effect'+str(id(world))),self.now)['phase'],'REJECTED')
        self.reader.value=self.world;self.port.reject_release=True
        self.execution.dispatch(self.envelope,self.now);self.execution.tick(self.now);self.assertEqual(self.execution.status('effect')['reason'],'simulated_payload_rejection')
        self.assertFalse(self.port.released)
        with self.assertRaises(TypeError):PayloadExecution(self.authority,self.port,None,self.reader)

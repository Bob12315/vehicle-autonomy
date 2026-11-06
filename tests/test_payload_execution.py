"""Payload queue, final authorization fence, observed completion and irreversibility."""
from dataclasses import replace
import unittest
from vehicle_autonomy.contracts.core.geometry import Vector3
from vehicle_autonomy.contracts.core.primitives import SchemaVersion
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.core.stamped import Stamped
from vehicle_autonomy.contracts.effects.payload import ReleasePayloadEffect,PayloadEffectEnvelope
from vehicle_autonomy.engine.control.control_authority import ControlAuthority,ControlLease
from vehicle_autonomy.engine.control.payload_execution import PayloadExecution,PayloadSafetyPolicy,PayloadMutationUnconfirmed
from vehicle_autonomy.actions.devices.simulation_payload import SimPayloadPort
from vehicle_autonomy.world.model.models import WorldObject
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
    def test_uncertain_device_publication_remains_unknown_without_replay(self):
        def uncertain(*_):raise PayloadMutationUnconfirmed('publication uncertain')
        self.port.release=uncertain
        self.execution.dispatch(self.envelope,self.now);self.execution.tick(self.now)
        self.assertEqual(self.execution.status('effect')['phase'],'UNKNOWN')
        self.execution.dispatch(self.envelope,self.now);self.execution.tick(self.later())
        self.assertEqual(self.execution.status('effect')['phase'],'UNKNOWN')
    def test_exact_observation_ledger_handles_newer_fact_without_bypassing_latest_state(self):
        original=self.world.objects[0]
        self.reader.value=replace(self.world,objects=(replace(original,source_observation_id='newer'),))
        self.assertEqual(self.execution.dispatch(self.envelope,self.now)['reason'],'payload_observation_identity_mismatch')
        execution=PayloadExecution(self.authority,self.port,PayloadSafetyPolicy(('sim.objects:',)),self.reader,
            observation_validator=lambda effect,now:effect==self.envelope.effect and now==self.now)
        self.assertEqual(execution.dispatch(self.envelope,self.now)['phase'],'ACCEPTED')
        # Proving the old original identity must not substitute for a current
        # target or restore permission revoked after queue admission.
        self.reader.value=replace(self.world,objects=())
        execution.tick(self.now)
        self.assertEqual(execution.status('effect')['phase'],'REJECTED');self.assertFalse(self.port.commands)
        self.reader.value=replace(self.world,objects=(replace(original,source_observation_id='newer'),))
        second=replace(self.envelope,effect_id='second')
        self.assertEqual(execution.dispatch(second,self.now)['phase'],'ACCEPTED')
        self.authority.set_action_send(False);execution.tick(self.now)
        self.assertEqual(execution.status('second')['phase'],'REJECTED');self.assertFalse(self.port.commands)
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
    def test_explicit_bounded_aim_offset_keeps_real_target_and_final_alignment_fence(self):
        effect=replace(self.envelope.effect,aim_offset=Vector3(0,.45,0))
        envelope=replace(self.envelope,effect=effect)
        self.assertEqual(self.execution.dispatch(envelope,self.now)['reason'],'payload_aim_offset_not_allowed')
        policy=PayloadSafetyPolicy(('sim.objects:',),max_aim_offset_m=.6)
        execution=PayloadExecution(self.authority,self.port,policy,self.reader)
        loc=self.world.localization
        def at(y):
            return replace(self.world,localization=replace(loc,pose=replace(loc.pose,
                value=replace(loc.pose.value,position=Vector3(2,y,1.5)))))
        self.reader.value=at(1.45)
        self.assertEqual(execution.dispatch(envelope,self.now)['phase'],'ACCEPTED')
        self.assertEqual(envelope.effect.target_position,self.world.objects[0].position.value)
        forged=replace(envelope,effect=replace(effect,target_position=Vector3(2,1.45,.05)))
        self.assertEqual(policy.reason(forged,self.reader.value,self.now),'payload_target_moved')
        for offset in (Vector3(0,.61,0),Vector3(0,0,.1)):
            self.assertEqual(policy.reason(replace(envelope,effect=replace(effect,aim_offset=offset)),self.reader.value,self.now),'payload_aim_offset_not_allowed')
        self.reader.value=at(2.)
        execution.tick(self.now)
        self.assertEqual(execution.status('effect')['reason'],'payload_not_aligned')
        self.assertFalse(self.port.commands)
    def test_rejection_staleness_alignment_and_untrusted_sources(self):
        cases=[replace(self.world,objects=()),self.h.sample(.1,Vector3(0,0,1.5)),replace(self.world,environment=None),replace(self.world,objects=(replace(self.world.objects[0],position=Stamped('map',self.now,Vector3(2,1,.05))),))]
        for world in cases:
            self.reader.value=world
            self.assertEqual(self.execution.dispatch(replace(self.envelope,effect_id='effect'+str(id(world))),self.now)['phase'],'REJECTED')
        self.reader.value=self.world;self.port.reject_release=True
        self.execution.dispatch(self.envelope,self.now);self.execution.tick(self.now);self.assertEqual(self.execution.status('effect')['reason'],'simulated_payload_rejection')
        self.assertFalse(self.port.released)
        with self.assertRaises(TypeError):PayloadExecution(self.authority,self.port,None,self.reader)

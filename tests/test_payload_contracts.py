from dataclasses import dataclass,replace
import unittest
from contracts.core.geometry import Vector3
from contracts.core.primitives import SchemaVersion
from contracts.decision import ActionDecision,ActionOutcome,ActionSpec,MissionPlan,MissionStep,ExitDecision
from contracts.effects.vehicle import EffectEnvelope
from contracts.effects.payload import ReleasePayloadEffect,PayloadEffectEnvelope
from contracts.vehicle.ports import VehicleCapabilities
from core.action_registry import ActionRegistry
from core.mission import MissionValidator
from core.mission_runtime import MissionRuntime
from tests import test_basic_actions as helpers

@dataclass(frozen=True,slots=True)
class Parameters: payload:str='p'
class Factory:
    def __init__(self,effect):self.effect=effect
    def start(self,p,w):return self
    def tick(self,w):return ActionDecision(ActionOutcome.RUNNING,(self.effect,))
    def exit(self,w,r):return ExitDecision(True)
class Reader:
    def __init__(self,w):self.value=w
    def snapshot(self):return self.value

class PayloadContractTests(unittest.TestCase):
    def setUp(self):
        self.h=helpers.BasicActionTests();self.h.setUp();self.world=self.h.world;self.now=self.world.published_at
        self.effect=ReleasePayloadEffect('p','target','producer','observation',Vector3(0,0,0),self.now,self.world.environment)
    def tearDown(self):self.h.tearDown()
    def test_vehicle_rejects_payload_and_payload_validation(self):
        args=(SchemaVersion(1,0),'e','r','a',self.now,replace(self.now,monotonic_ns=self.now.monotonic_ns+10))
        with self.assertRaises(TypeError):EffectEnvelope(*args,self.effect)
        with self.assertRaises(TypeError):PayloadEffectEnvelope(*args,object())
        with self.assertRaises(ValueError):PayloadEffectEnvelope(*args[:5],self.now,self.effect)
        with self.assertRaises(ValueError):replace(self.effect,payload_id='')
        with self.assertRaises(TypeError):ActionSpec('x',Parameters,effect_types=(object,))
    def test_mission_preserves_non_vehicle_scope_deadline_allowlist(self):
        registry=ActionRegistry();registry.register_typed(ActionSpec('payload',Parameters,effect_types=(ReleasePayloadEffect,),effect_ttl_ns=123),Factory(self.effect))
        plan=MissionValidator(registry).compile(MissionPlan('release',(MissionStep('s','payload',Parameters()),)),VehicleCapabilities(frozenset()))
        runtime=MissionRuntime(plan,Reader(self.world),'run',max_snapshot_age_ns=100)
        envelope=runtime.tick(self.now).effects[0]
        self.assertIsInstance(envelope,PayloadEffectEnvelope);self.assertEqual(envelope.run_id,'run');self.assertEqual(envelope.action_instance_id,'run:s:1');self.assertEqual(envelope.deadline.elapsed_ns_since(self.now),123)
        self.assertEqual(envelope.effect,self.effect)
        with self.assertRaises(TypeError):self.h.harness.runtime._execution.dispatch(envelope,self.world,self.now)

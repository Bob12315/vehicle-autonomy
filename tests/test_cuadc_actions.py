from dataclasses import replace
import unittest
from contracts.core.geometry import Vector3
from contracts.core.quality import QualityState
from contracts.core.stamped import Stamped
from contracts.decision import ActionOutcome,EffectPhase,EffectResult,ExitReason
from applications.cuadc.actions import TargetParameters,TargetAction,candidates,register_targets
from applications.cuadc.catalog import build
from applications.basic_catalog import capabilities
from contracts.vehicle.ports import VehicleCapabilities
from core.action_registry import ActionRegistry
from core.mission import MissionValidator
from core.sitl_mode_action import SITL_MODE_SPEC,SitlModeAction
from actions.basic import register_basic
from world_model.models import WorldObject
from tests import test_basic_actions as helpers

class CuadcActionTests(unittest.TestCase):
    def setUp(self):
        self.h=helpers.BasicActionTests();self.h.setUp();self.world=self.h.sample(.1,Vector3(2,1,1.5));env=self.h.environment
        region=next(r for r in env.regions if r.name=='search')
        self.params=TargetParameters('copter',env.reference,region,env.resolve('HOME_AIR').position.z,'sim_payload_1')
        self.obj=WorldObject('sim.objects:test:target_1','bucket_1',Stamped('odom',self.world.published_at,Vector3(2,1,.05)),1.,QualityState.VALID,'obs','sim.objects:test')
        self.world=replace(self.world,objects=(self.obj,))
    def tearDown(self):self.h.tearDown()
    def sample(self,seconds,objects=None):
        w=self.h.sample(.1+seconds,Vector3(2,1,1.5))
        return replace(w,objects=tuple(replace(o,position=replace(o.position,captured_at=w.published_at)) for o in (self.world.objects if objects is None else objects)))
    def test_selection_is_observation_driven_rejects_wrong_duplicate_stale_sources(self):
        duplicate=replace(self.obj,object_id='duplicate',label='bucket_2')
        other=replace(self.obj,object_id='other',label='bucket_3',position=replace(self.obj.position,value=Vector3(1,1,.05)))
        self.assertEqual([o.object_id for o in candidates(replace(self.world,objects=(other,duplicate,self.obj)),self.params)],[self.obj.object_id,other.object_id])
        for obj in (replace(self.obj,label='unknown'),replace(self.obj,producer_id='oracle'),replace(self.obj,confidence=.1),replace(self.obj,quality=QualityState.DEGRADED),replace(self.obj,position=replace(self.obj.position,frame_id='map'))):
            self.assertFalse(candidates(replace(self.world,objects=(obj,)),self.params))
        old=replace(self.world,published_at=replace(self.world.published_at,monotonic_ns=self.world.published_at.monotonic_ns+1_000_000_001))
        self.assertFalse(candidates(old,self.params))
    def test_no_target_lost_moved_timeout_and_safe_exit(self):
        action=TargetAction().start(self.params,self.world);action.tick(self.world)
        self.assertEqual(action.tick(replace(self.world,objects=())).error,'target_lost_or_expired')
        changed=replace(self.obj,position=replace(self.obj.position,value=Vector3(2.3,1,.05)))
        self.assertEqual(action.tick(replace(self.world,objects=(changed,))).error,'locked_target_moved')
        self.assertFalse(action.exit(self.world,ExitReason.CANCELLED).complete)
        absent=TargetAction().start(self.params,replace(self.world,objects=()))
        self.assertEqual(absent.tick(self.sample(6,())).error,'target_acquisition_deadline')
        self.assertTrue(absent.exit(self.sample(6,()),ExitReason.FAILED).complete)
        self.assertEqual(action.tick(self.sample(61)).error,'target_approach_deadline')
    def test_ack_is_not_payload_success_rejection_and_world_marker(self):
        action=TargetAction().start(self.params,self.world);action.tick(self.world)
        tx=(EffectResult('nav','action',EffectPhase.TRANSMITTED),)
        action.tick_with_results(self.sample(.2),tx);action.tick_with_results(self.sample(1.3),tx)
        stop=action.tick_with_results(self.sample(1.4),tx);self.assertEqual(type(stop.effects[0]).__name__,'StopMotionEffect')
        completed=tx+(EffectResult('stop','action',EffectPhase.COMPLETED),)
        action.tick_with_results(self.sample(1.5),completed)
        release=action.tick_with_results(self.sample(3.6),completed);self.assertEqual(type(release.effects[0]).__name__,'ReleasePayloadEffect')
        ack=completed+(EffectResult('payload','action',EffectPhase.ACKNOWLEDGED),)
        self.assertEqual(action.tick_with_results(self.sample(3.7),ack).outcome,ActionOutcome.RUNNING)
        rejected=completed+(EffectResult('payload','action',EffectPhase.REJECTED,reason='denied'),)
        self.assertEqual(action.tick_with_results(self.sample(3.8),rejected).error,'denied')
    def test_compilation_and_rover_payload_capability(self):
        registry=ActionRegistry();register_basic(registry);register_targets(registry);registry.register_typed(SITL_MODE_SPEC,SitlModeAction())
        plan=build('cuadc_demo','copter',self.h.environment,4,True)
        compiled=MissionValidator(registry).compile(plan,VehicleCapabilities(capabilities('copter')|{'payload_release'}))
        self.assertEqual([s.step.step_id for s in compiled.steps],['mode','arm','takeoff','search','approach_release','home','land','disarm'])
        with self.assertRaises(ValueError):MissionValidator(registry).compile(plan,VehicleCapabilities(capabilities('rover')))
        with self.assertRaises(ValueError):build('cuadc_demo','rover',self.h.environment,15,True)
        with self.assertRaises(ValueError):build('cuadc_demo','copter',self.h.environment,4,False)

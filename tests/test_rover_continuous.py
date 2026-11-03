"""Rover neutral observation and the unchanged finite HOLD exit contract."""
from dataclasses import replace
import unittest
from vehicle_autonomy.actions.rover.standard import RoverStream, DriveParameters
from vehicle_autonomy.contracts.action import ActionContext
from vehicle_autonomy.contracts.core.geometry import Twist3, Vector3
from vehicle_autonomy.contracts.core.stamped import Stamped
from vehicle_autonomy.contracts.decision import ActionOutcome, EffectResult, EffectPhase, ExitReason
from vehicle_autonomy.contracts.effects.vehicle import TwistTargetEffect, StopMotionEffect, ModeEffect
from tests import test_basic_actions as basic


class RoverContinuousTests(unittest.TestCase):
    def setUp(self):
        self.h=basic.BasicActionTests();self.h.setUp();self.addCleanup(self.h.tearDown)
        self.ctx=ActionContext('rover','rover',frozenset(),True)

    def world(self,seconds,speed=0,rate=0):
        w=self.h.sample(seconds);stamp=w.published_at
        twist=Stamped('odom',stamp,Twist3(Vector3(speed,0,0),Vector3(0,0,rate)))
        vehicle=replace(w.vehicle,reported_twist=twist,operation=replace(w.vehicle.operation,native_mode='ARDUPILOT_CUSTOM_15'))
        return replace(w,vehicle=vehicle,localization=replace(w.localization,twist=twist))

    def stream(self,p=None):
        action=RoverStream('Drive',p or DriveParameters(0.,0.),self.world(0),self.ctx)
        action.fixture_emissions=[];tick=action.tick_with_results
        def observed(world,results):
            decision=tick(world,results);action.fixture_emissions.extend(decision.effects);return decision
        action.tick_with_results=observed
        return action

    def published(self,action):
        return tuple(EffectResult('stream-'+str(i),'action',EffectPhase.TRANSMITTED) for i,_ in enumerate(action.fixture_emissions))

    def test_neutral_stays_guided_in_same_stream_with_physical_observation(self):
        action=self.stream();stream=action.stream
        for seconds in (0,.1,.5,1,2.2,3):
            decision=action.tick_with_results(self.world(seconds),())
            self.assertEqual(decision.outcome,ActionOutcome.RUNNING)
            self.assertTrue(all(isinstance(e,TwistTargetEffect) for e in decision.effects))
        self.assertTrue(decision.feedback['physical_stop_observed'])
        action.update_input(DriveParameters(.3,.25));d=action.tick_with_results(self.world(3.1),())
        self.assertEqual(d.feedback['stage'],'driving');self.assertEqual(d.effects[0].stream_id,stream)
        action.update_input(DriveParameters(-.3,-.25));d=action.tick_with_results(self.world(3.2),())
        self.assertEqual(d.effects[0].target_twist.linear.x,-.3);self.assertEqual(d.effects[0].target_twist.angular.z,-.25)
        action.update_input(DriveParameters(0.,0.));d=action.tick_with_results(self.world(3.3,.2),())
        self.assertEqual(d.feedback['stage'],'zero velocity stopping')

    def test_zero_coasting_or_later_drift_fails_into_original_HOLD_exit(self):
        for drift in (False,True):
            with self.subTest(drift=drift):
                action=self.stream();action.tick_with_results(self.world(0),())
                if drift:
                    for t in (.1,1,2.2):action.tick_with_results(self.world(t),())
                    start=2.3
                else:start=.1
                action.tick_with_results(self.world(start,.2),())
                d=action.tick_with_results(self.world(start+8.1,.2),())
                self.assertEqual(d.outcome,ActionOutcome.FAILED);self.assertIn('HOLD',d.error)
                exit=action.exit_with_results(self.world(start+8.2,.2),ExitReason.FAILED,self.published(action))
                self.assertEqual([type(e) for e in exit.effects],[StopMotionEffect,ModeEffect])
                self.assertEqual(exit.effects[1].native_mode,'HOLD');self.assertFalse(exit.complete)

    def test_missing_or_stale_observation_cannot_claim_neutral_stop(self):
        action=self.stream()
        d=action.tick_with_results(replace(self.world(0),localization=None),())
        self.assertEqual(d.outcome,ActionOutcome.FAILED)
        action=self.stream();action.tick_with_results(self.world(0),())
        stale=self.world(8.2);stale=replace(stale,localization=replace(stale.localization,twist=self.world(0).localization.twist))
        self.assertEqual(action.tick_with_results(stale,()).outcome,ActionOutcome.FAILED)

    def test_unconfirmed_exit_is_never_released_or_replaced_by_neutral(self):
        action=self.stream();action.tick_with_results(self.world(0),())
        action.exit_with_results(self.world(.1),ExitReason.CANCELLED,self.published(action))
        with self.assertRaisesRegex(RuntimeError,'unconfirmed'):
            action.exit_with_results(self.world(.2),ExitReason.CANCELLED,self.published(action)+(EffectResult('stop','action',EffectPhase.UNKNOWN),))

    def test_HOLD_ack_cannot_replace_StopMotion_completion(self):
        action=self.stream();action.tick_with_results(self.world(0),())
        action.exit_with_results(self.world(.1),ExitReason.CANCELLED,self.published(action))
        prior=self.published(action)
        results=prior+(EffectResult('stop','action',EffectPhase.TRANSMITTED),EffectResult('hold','action',EffectPhase.COMPLETED))
        def held(t):
            w=self.world(t);return replace(w,vehicle=replace(w.vehicle,operation=replace(w.vehicle.operation,native_mode='ARDUPILOT_CUSTOM_4')))
        self.assertFalse(action.exit_with_results(held(.2),ExitReason.CANCELLED,results).complete)
        self.assertFalse(action.exit_with_results(held(2.4),ExitReason.CANCELLED,results).complete)
        completed=prior+(replace(results[-2],phase=EffectPhase.COMPLETED),results[-1])
        self.assertFalse(action.exit_with_results(held(2.5),ExitReason.CANCELLED,completed).complete)
        self.assertTrue(action.exit_with_results(held(4.6),ExitReason.CANCELLED,completed).complete)

    def test_repeated_post_neutral_snapshot_keeps_settle_but_cannot_supply_two_seconds(self):
        action=self.stream();action.tick_with_results(self.world(0),())
        action.tick_with_results(self.world(.1),())
        w=self.world(.5);w=replace(w,localization=replace(w.localization,twist=self.world(.1).localization.twist))
        d=action.tick_with_results(w,())
        self.assertFalse(d.feedback['physical_stop_observed'])
        self.assertTrue(action.tick_with_results(self.world(2.2),()).feedback['physical_stop_observed'])

from dataclasses import replace
import unittest
from tests.action_system.test_runtime import Clock, Driver, Parameters, Instance
from vehicle_autonomy.contracts.action import ActionKind, ActionResource, ActionSafety
from vehicle_autonomy.contracts.decision import ActionSpec
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.action.manager import ActionRuntime


class InputFactory:
    supports_input_updates=True
    def validate_context(self,p,w,c):pass
    def start(self,p,w):
        instance=Instance(p,continuous=True,emit=True)
        instance.update_input=lambda p:setattr(instance,'p',p)
        return instance


class ManualInputTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.driver=Driver();self.factory=InputFactory();self.registry=ActionRegistry()
        self.registry.register_typed(ActionSpec('input',Parameters,kind=ActionKind.CONTINUOUS,effect_types=(ArmEffect,),
            resources=(ActionResource('vehicle.motion'),),external_lifecycle='typed_only'),self.factory)
        self.runtime=ActionRuntime(self.registry,{'v':self.driver},clock=self.clock)
    def start(self):
        v=self.runtime.submit('input','v',allow_send=True,input_timeout_s=.4)
        self.runtime.tick();return self.runtime.view(v['id'])
    def update(self,v,seq=1,**kw):
        return self.runtime.update_input(v['id'],{'count':3},sequence=seq,expected_deadline_ns=v['input_deadline_ns'],**kw)
    def ticks(self,n=6):
        for _ in range(n):self.runtime.tick()
    def test_same_instance_update_and_writer_expiry_shortened(self):
        v=self.start();self.assertEqual(len(self.driver.writes),1)
        self.assertEqual(self.driver.writes[0].deadline.monotonic_ns,v['input_deadline_ns'])
        self.clock.advance(.1);new=self.update(v)
        self.assertEqual(new['id'],v['id']);self.assertEqual(new['parameters']['count'],3)
        self.assertEqual(new['input_sequence'],1);self.assertGreater(new['input_deadline_ns'],v['input_deadline_ns'])
        self.assertEqual(len(self.runtime.views()),1)
    def test_deadman_cancels_and_old_session_cannot_revive(self):
        v=self.start();self.clock.advance(.41);self.ticks()
        end=self.runtime.view(v['id']);self.assertEqual(end['state'],'TIMED_OUT')
        self.assertTrue(end['safety']['release_safe']);self.assertEqual(len(self.driver.writes),1)
        with self.assertRaises(ValueError):self.update(v)
        newer=self.start();self.assertNotEqual(newer['id'],v['id']);self.assertEqual(len(self.driver.writes),2)
    def test_unknown_stop_retains_common_resource_and_no_new_writer(self):
        self.driver.safety=ActionSafety(False,False,'stop UNCONFIRMED')
        v=self.start();self.clock.advance(.41);self.ticks()
        self.assertEqual(self.runtime.view(v['id'])['state'],'UNKNOWN')
        self.assertTrue(self.runtime.resource_view());self.assertEqual(len(self.driver.writes),1)
        v2=self.runtime.submit('input','v',allow_send=True,input_timeout_s=.4)
        self.ticks();self.assertEqual(v2['state'],'REJECTED');self.assertEqual(len(self.driver.writes),1)
    def test_delayed_duplicate_out_of_order_and_ticket_replay(self):
        v=self.start()
        for seq in (0,2,True):
            with self.assertRaises(ValueError):self.update(v,seq)
        self.clock.advance(.1);new=self.update(v)
        with self.assertRaises(ValueError):self.update(v,1)
        with self.assertRaises(ValueError):self.update(v,2)
        self.assertEqual(self.runtime.view(v['id'])['input_sequence'],1)
        self.clock.advance(.41)
        with self.assertRaises(ValueError):self.update(new,2)
    def test_lease_cannot_be_extended_past_action_deadline(self):
        v=self.runtime.submit('input','v',allow_send=True,timeout_s=.3,input_timeout_s=.4)
        self.runtime.tick();v=self.runtime.view(v['id']);self.clock.advance(.1)
        new=self.update(v);self.assertEqual(new['input_deadline_ns'],new['deadline_ns'])
        self.clock.advance(.21);self.ticks();self.assertEqual(self.runtime.view(v['id'])['state'],'TIMED_OUT')
    def test_time_rechecked_after_validation_and_no_parameter_mutation(self):
        v=self.start()
        self.factory.validate_context=lambda *_:self.clock.advance(.5)
        with self.assertRaises(ValueError):self.update(v)
        self.assertEqual(self.runtime.view(v['id'])['parameters']['count'],2)
        self.ticks();self.assertEqual(len(self.driver.writes),1)
    def test_no_send_invalid_values_and_noncontinuous_are_rejected(self):
        v=self.runtime.submit('input','v',input_timeout_s=.4);self.runtime.tick()
        with self.assertRaises(ValueError):self.update(self.runtime.view(v['id']))
        for ttl in (.01,1,True,float('nan')):
            with self.assertRaises(ValueError):self.runtime.submit('input','v',input_timeout_s=ttl)
        self.registry.register_typed(replace(self.registry.resolve_typed('input').spec,name='goal',kind=ActionKind.GOAL),self.factory)
        with self.assertRaises(ValueError):self.runtime.submit('goal','v',input_timeout_s=.4)

    def test_clock_regression_cannot_extend_input_or_mutate_target(self):
        v=self.start();self.clock.advance(.1);v=self.update(v)
        self.clock.advance(-.05)
        with self.assertRaises(ValueError):self.update(v,2)
        current=self.runtime.view(v['id'])
        self.assertEqual(current['input_deadline_ns'],v['input_deadline_ns'])
        self.assertEqual(current['input_sequence'],1)
        self.assertEqual(len(self.driver.writes),1)

if __name__=='__main__':unittest.main()

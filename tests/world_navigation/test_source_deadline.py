"""A fresh callback/queue receipt cannot extend a third-party source deadline."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from tests.action_system import test_runtime as fixtures
from vehicle_autonomy.contracts.decision import ActionDecision,ActionOutcome,ActionSpec,ExitDecision
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.action.runtime import ActionRuntime

class SourceDeadlineTests(unittest.TestCase):
    def setup_case(self,expiry,*,slow=0.,domain='test'):
        clock=fixtures.Clock();driver=fixtures.Driver();registry=ActionRegistry();context=[]
        driver.info=lambda:{'session_id':'verified-session'}
        driver.snapshot=lambda:SimpleNamespace(version=SimpleNamespace(generation_id='world-generation'))
        class Instance:
            def tick(self,w):
                clock.advance(slow)
                return ActionDecision(ActionOutcome.RUNNING,(ArmEffect(),),valid_until=replace(clock(),monotonic_ns=expiry,clock_domain_id=domain))
            def exit(self,w,r):return ExitDecision(True)
        class Factory:
            def start(self,p,w):raise RuntimeError("bound context required")
            def start_with_context(self,p,w,ctx):context.append(ctx);return Instance()
        registry.register_typed(ActionSpec('bounded',fixtures.Parameters,effect_types=(ArmEffect,),external_lifecycle='typed_only'),Factory())
        runtime=ActionRuntime(registry,{'v':driver},clock=clock);view=runtime.submit('bounded','v',allow_send=True)
        return runtime,driver,clock,view,context
    def test_valid_source_deadline_caps_actual_envelope_and_binding(self):
        runtime,driver,clock,view,ctx=self.setup_case(1_100_000_000)
        for _ in range(5):
            runtime.tick()
            if driver.writes:break
        self.assertEqual(len(driver.writes),1)
        self.assertEqual(driver.writes[0].deadline.monotonic_ns,1_100_000_000)
        self.assertEqual((ctx[0].action_id,ctx[0].vehicle_session,ctx[0].world_generation),(view['id'],'verified-session','world-generation'))
    def test_callback_delay_or_wrong_clock_cannot_dispatch(self):
        for expiry,slow,domain in ((1_100_000_000,.2,'test'),(1_100_000_000,0,'foreign')):
            runtime,driver,clock,view,ctx=self.setup_case(expiry,slow=slow,domain=domain)
            for _ in range(5):runtime.tick()
            self.assertEqual(driver.writes,[])
            self.assertIn(runtime.view(view['id'])['state'],('FAILED','UNKNOWN'))

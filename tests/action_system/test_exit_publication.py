"""Exit callbacks see stable issued-request slots, never synthetic completion."""
import unittest
from vehicle_autonomy.contracts.action import ActionKind,ActionSafety
from vehicle_autonomy.contracts.core.geometry import Twist3,Vector3
from vehicle_autonomy.contracts.decision import ActionSpec,ActionDecision,ActionOutcome,ExitDecision,EffectResult,EffectPhase
from vehicle_autonomy.contracts.effects.vehicle import TwistTargetEffect,StopMotionEffect,ModeEffect
from vehicle_autonomy.engine.action.manager import ActionRuntime
from vehicle_autonomy.engine.action.registry import ActionRegistry
from tests.action_system.test_runtime import Driver,Clock,Parameters


class ExitProbe:
    def __init__(self):self.sent=False;self.stopping=False;self.seen=[]
    def tick(self,world):
        if self.sent:return ActionDecision(ActionOutcome.RUNNING)
        self.sent=True
        return ActionDecision(ActionOutcome.RUNNING,(TwistTargetEffect('base_link',Twist3(Vector3(.3,0,0),Vector3(0,0,0)),'s'),))
    def exit(self,world,reason):return self.exit_with_results(world,reason,())
    def exit_with_results(self,world,reason,results):
        self.seen.append(tuple((r.effect_id,r.phase) for r in results))
        if not self.stopping:
            self.stopping=True;return ExitDecision(False,(StopMotionEffect('s'),ModeEffect('HOLD')))
        if results[1].phase is EffectPhase.UNKNOWN:raise RuntimeError('stop UNCONFIRMED')
        return ExitDecision(all(r.phase is EffectPhase.COMPLETED for r in results[1:]))


class ExitPublicationTests(unittest.TestCase):
    def setUp(self):
        self.driver=Driver();self.published=();self.driver.effect_results=lambda _:self.published
        self.probe=ExitProbe();registry=ActionRegistry()
        class Factory:
            def start(_,p,w):return self.probe
        registry.register_typed(ActionSpec('stream',Parameters,kind=ActionKind.CONTINUOUS,
            effect_types=(TwistTargetEffect,StopMotionEffect,ModeEffect),external_lifecycle='typed_only'),Factory())
        self.runtime=ActionRuntime(registry,{'v':self.driver},clock=Clock())
        self.action=self.runtime.submit('stream','v',allow_send=True);self.runtime.tick()
        self.runtime.cancel(self.action['id']);self.runtime.tick()
    def result(self,index,phase):return EffectResult(str(self.driver.writes[index].effect_id),self.action['id'],phase)
    def test_late_cancelled_refresh_does_not_move_stop_or_HOLD_result(self):
        self.assertEqual(len(self.driver.writes),3)
        self.assertEqual(self.probe.seen[0][0][1],EffectPhase.REQUESTED)
        self.published=(self.result(0,EffectPhase.CANCELLED),)
        self.runtime.tick()
        self.assertEqual([p for _,p in self.probe.seen[-1]],[EffectPhase.CANCELLED,EffectPhase.REQUESTED,EffectPhase.REQUESTED])
        self.assertEqual(self.runtime.view(self.action['id'])['state'],'CANCELLING')
        self.published+=(self.result(1,EffectPhase.COMPLETED),self.result(2,EffectPhase.COMPLETED))
        self.runtime.tick();self.runtime.tick()
        self.assertEqual(self.runtime.view(self.action['id'])['state'],'CANCELLED')
        self.assertEqual(len(self.driver.writes),3)
    def test_true_unknown_stop_remains_unknown_and_never_becomes_a_mode_ack(self):
        self.driver.safety=ActionSafety(False,False,'stop UNCONFIRMED')
        self.published=(self.result(0,EffectPhase.CANCELLED),self.result(1,EffectPhase.UNKNOWN),self.result(2,EffectPhase.COMPLETED))
        for _ in range(4):self.runtime.tick()
        final=self.runtime.view(self.action['id'])
        self.assertEqual(final['state'],'UNKNOWN');self.assertFalse(final['safety']['release_safe'])
        self.assertEqual(len(self.driver.writes),3)

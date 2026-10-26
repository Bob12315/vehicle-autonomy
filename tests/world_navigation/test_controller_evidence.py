from dataclasses import replace
import unittest
from tests.world_navigation.test_streams import stamp
from vehicle_autonomy.engine.navigation.source_evidence import ControllerEvidence,ControllerStamp

class ControllerEvidenceTests(unittest.TestCase):
    def sample(self,t,receive=None,v=.1):return ControllerStamp(t+1,stamp(t),stamp(t+1 if receive is None else receive),(v,0.,0.,0.,0.,0.))
    def test_final_new_stamp_from_timeout_is_not_new_controller_evidence(self):
        cache=ControllerEvidence(stamp(0));sample=self.sample(1);cache.record(sample,stamp(3))
        self.assertIs(cache.original(2,stamp(100)),sample)
        with self.assertRaises(ValueError):cache.original(150_000_001,stamp(150_000_002))
        with self.assertRaises(ValueError):cache.original(2,stamp(200_000_001))
    def test_duplicate_receipts_and_conflicting_same_stamp_do_not_renew(self):
        cache=ControllerEvidence(stamp(0));sample=self.sample(1);cache.record(sample,stamp(3))
        cache.record(replace(sample,received_at=stamp(100)),stamp(100))
        self.assertEqual(cache.original(2,stamp(101)).received_at,stamp(2))
        cache.record(replace(sample,twist=(.2,0.,0.,0.,0.,0.)),stamp(102))
        with self.assertRaises(ValueError):cache.original(2,stamp(103))
    def test_normal_many_commands_remain_bounded_and_closed_scope_cannot_resume(self):
        cache=ControllerEvidence(stamp(0),capacity=4)
        for n in range(10000):
            t=n*50_000_000;fact=self.sample(t);cache.record(fact,stamp(t+2));self.assertEqual(cache.original(t+1,stamp(t+3)),fact)
        self.assertEqual(len(cache._samples),4)
        cache.close()
        with self.assertRaises(ValueError):cache.record(self.sample(t+50_000_000),stamp(t+50_000_003))
    def test_future_wrong_clock_and_wrong_axes_rejected(self):
        cache=ControllerEvidence(stamp(10))
        with self.assertRaises(ValueError):cache.record(self.sample(1),stamp(20))
        with self.assertRaises(ValueError):cache.record(replace(self.sample(11),captured_at=stamp(11,'wrong')),stamp(20))
        with self.assertRaises(ValueError):replace(self.sample(11),twist=(.1,.1,0.,0.,0.,0.))

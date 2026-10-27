import unittest
from tests.world_navigation.test_streams import stamp
from vehicle_autonomy.engine.navigation.preparation_evidence import PreparationChannelEvidence
from vehicle_autonomy.engine.navigation.source_evidence import ControllerEvidence,ControllerStamp


class PreparationEvidenceTests(unittest.TestCase):
    def test_delayed_zero_only_proves_channel_and_cannot_be_controller_evidence(self):
        warm=PreparationChannelEvidence('1'*32,'2'*32)
        zero=(0.,)*6;warm.observe('raw','1'*32,1,zero,1_000_000_000)
        self.assertIsNone(warm.proof())
        warm.observe('final','2'*32,1,zero,2_000_000_000)
        self.assertIs(warm.proof()['control_eligible'],False)
        active=ControllerEvidence(stamp(2_000_000_000))
        old=ControllerStamp(1,stamp(1),stamp(2_000_000_000),zero)
        with self.assertRaises(ValueError):active.record(old,stamp(2_000_000_000))
        with self.assertRaises(ValueError):active.original(1,stamp(2_000_000_000))
        fresh=ControllerStamp(2,stamp(2_000_000_001),stamp(2_000_000_002),zero)
        self.assertTrue(active.record(fresh,stamp(2_000_000_003)))
        self.assertIs(active.original(2,stamp(2_000_000_004)),fresh)

    def test_wrong_publishers_nonzero_axes_and_mismatched_stamp_cannot_qualify(self):
        warm=PreparationChannelEvidence('1'*32,'2'*32)
        for channel,gid,values in (('raw','3'*32,(0.,)*6),('final','2'*32,(0.,0.,0.,0.,0.,.01)),('raw','1'*32,(0.,.01,0.,0.,0.,0.))):
            with self.assertRaises(ValueError):warm.observe(channel,gid,1,values,2)
        warm.observe('raw','1'*32,1,(0.,)*6,2)
        warm.observe('final','2'*32,2,(0.,)*6,3)
        self.assertIsNone(warm.proof())

    def test_bounded_history_and_duplicate_receipt_does_not_refresh_proof(self):
        warm=PreparationChannelEvidence('1'*32,'2'*32)
        for n in range(1000):
            warm.observe('raw','1'*32,n,(0.,)*6,n+1)
            warm.observe('final','2'*32,n,(0.,)*6,n+2)
        self.assertTrue(all(len(v)==16 for v in warm.samples.values()))
        warm.observe('raw','1'*32,999,(0.,)*6,100000)
        self.assertEqual(warm.proof()['raw_received_ns'],1000)

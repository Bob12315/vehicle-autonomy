from dataclasses import replace
from datetime import datetime,timezone
import unittest

from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.contracts.streams import DataKind,SourceKind,FrameDescriptor,DataReference,SampleHeader,StreamObservation
from vehicle_autonomy.world.model.streams import StreamState,StreamProfile


def stamp(ns,domain='host'):return TimePoint(ns,datetime(2026,10,26,tzinfo=timezone.utc),domain)


class StreamsTests(unittest.TestCase):
    def setUp(self):
        self.frame=FrameDescriptor('laser','FLU','owned-map-epoch')
        self.profile=StreamProfile('gazebo','lidar',DataKind.SCAN,'epoch-one',self.frame,'mount-v1',SourceKind.SIMULATION,100)
        self.state=StreamState(capacity=1);self.state.register(self.profile)
    def sample(self,sequence=1,source_ns=10,**kw):
        h=SampleHeader('gazebo','lidar',DataKind.SCAN,'epoch-one',sequence,source_ns,'ros-sim',stamp(20),stamp(10),self.frame,'mount-v1',SourceKind.SIMULATION,QualityState.VALID)
        return StreamObservation(replace(h,**kw),DataReference('ring:lidar/1','a'*64,24,'application/laserscan',(6,)))
    def test_current_reference_expires_without_capture_retimestamp(self):
        self.state.ingest(self.sample());self.assertTrue(self.state.snapshot(stamp(50),navigation=True)[0]['usable'])
        self.assertEqual(self.state.snapshot(stamp(111))[0]['reason'],'expired')
        # Re-receiving the same original frame does not renew its age.
        self.assertFalse(self.state.ingest(self.sample()))
        self.assertFalse(self.state.snapshot(stamp(111),navigation=True)[0]['usable'])
    def test_wrong_epoch_frame_origin_calibration_or_unknown_source_rejected(self):
        for override in ({'generation':'other'},{'frame':replace(self.frame,origin_id='other')},{'calibration_version':'bad'},
                         {'source_kind':SourceKind.REPLAY},{'sensor_id':'other'}):
            with self.subTest(override=override),self.assertRaises(ValueError):self.state.ingest(self.sample(**override))
        self.assertIsNone(self.state.snapshot(stamp(20))[0]['sample'])
    def test_sequence_rollback_timestamp_rollback_and_clock_change_do_not_replace(self):
        original=self.sample();self.state.ingest(original)
        for sample in (self.sample(sequence=0),self.sample(sequence=2),self.sample(sequence=2,source_ns=11,source_clock_domain='bad'),
                       self.sample(sequence=2,source_ns=11,received_at=stamp(19))):
            with self.assertRaises(ValueError):self.state.ingest(sample)
        self.assertEqual(self.state.snapshot(stamp(30))[0]['sample'],original)
        self.state.ingest(self.sample(sequence=2,source_ns=11,received_at=stamp(21),captured_at=stamp(11)))
        self.assertEqual(self.state.snapshot(stamp(30))[0]['sample'].header.sequence,2)
    def test_unqualified_wrong_domain_future_and_bad_quality_are_unusable(self):
        for overrides,now,reason in (({'captured_at':None},stamp(30),'capture_time_unqualified'),
              ({'captured_at':stamp(10,'ros')},stamp(30),'clock_domain_mismatch'),({},stamp(5),'future_timestamp'),
              ({'quality':QualityState.DEGRADED},stamp(30),'insufficient_quality')):
            with self.subTest(reason=reason):
                state=StreamState();state.register(self.profile);state.ingest(self.sample(**overrides))
                self.assertEqual(state.snapshot(now,navigation=True)[0]['reason'],reason)
    def test_replay_and_test_truth_remain_observable_but_never_navigation(self):
        for kind in (SourceKind.REPLAY,SourceKind.TEST_TRUTH):
            state=StreamState();state.register(replace(self.profile,source_kind=kind))
            state.ingest(self.sample(source_kind=kind))
            self.assertTrue(state.snapshot(stamp(30))[0]['usable'])
            self.assertEqual(state.snapshot(stamp(30),navigation=True)[0]['reason'],'not_live_navigation_evidence')
            with self.assertRaises(ValueError):state.require(stamp(30),[(self.profile.source_id,self.profile.sensor_id,self.profile.kind)])
    def test_bounded_sources_and_long_run_current_state(self):
        with self.assertRaises(ValueError):self.state.register(replace(self.profile,sensor_id='other'))
        with self.assertRaises(ValueError):self.state.register(self.profile)
        for i in range(1,10001):self.state.ingest(self.sample(sequence=i,source_ns=i,received_at=stamp(i+1),captured_at=stamp(i)))
        self.assertEqual(len(self.state._latest),1);self.assertEqual(len(self.state._sequences),1)
        self.assertEqual(self.state.snapshot(stamp(10002))[0]['sample'].header.sequence,10000)
    def test_atomic_cut_rejects_all_samples_and_preserves_watermarks(self):
        original=self.sample();self.state.ingest(original)
        newer=self.sample(sequence=2,source_ns=11,received_at=stamp(21),captured_at=stamp(11))
        bad=self.sample(sequence=3,source_ns=12,generation='untrusted')
        with self.assertRaises(ValueError):self.state.ingest_many((newer,bad))
        self.assertEqual(self.state.snapshot(stamp(30))[0]['sample'],original)
        self.state.ingest_many((newer,))
        self.assertEqual(self.state.snapshot(stamp(30))[0]['sample'],newer)

    def test_reference_and_units_contract(self):
        with self.assertRaises(ValueError):DataReference('image','bad',1,'image/jpeg')
        with self.assertRaises(ValueError):DataReference('image','a'*64,65*1024*1024,'image/jpeg')
        with self.assertRaises(ValueError):replace(self.frame,units='degrees_metres')
        with self.assertRaises(ValueError):FrameDescriptor('earth','WGS84','gps-origin')
        with self.assertRaises(ValueError):self.sample(confidence=float('nan'))
        with self.assertRaises(ValueError):self.sample(covariance=(-1.,)*9)
        with self.assertRaises(ValueError):self.sample(captured_at=stamp(21))

    def test_partial_batch_rollback_restores_original_header_time_watermark(self):
        state=StreamState();state.register(self.profile)
        other=replace(self.profile,sensor_id='other');state.register(other)
        original=self.sample();state.ingest(original)
        first=self.sample(sequence=2,source_ns=11,received_at=stamp(22),captured_at=stamp(11))
        bad=replace(first,header=replace(first.header,sensor_id='other',generation='wrong'))
        with self.assertRaises(ValueError):state.ingest_many((first,bad))
        self.assertEqual(state.accepted,1)
        self.assertTrue(state.ingest(first))
        self.assertEqual(state.accepted,2)

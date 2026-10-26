from dataclasses import replace
import unittest
from tests.world_navigation.test_streams import stamp
from vehicle_autonomy.contracts.streams import FrameDescriptor,DataReference,SampleHeader,StreamObservation,DataKind,SourceKind
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.world.model.streams import StreamProfile
from vehicle_autonomy.world.model.stream_events import ObservationEvents

class StreamEventTests(unittest.TestCase):
    def setUp(self):
        self.frame=FrameDescriptor('camera_optical','image_pixels','origin',units='pixels')
        self.profile=StreamProfile('detector','detections',DataKind.DETECTIONS,'epoch',self.frame,'calibration',SourceKind.SIMULATION,2_000_000_000)
        self.events=ObservationEvents(limit=4);self.events.register(self.profile)
    def sample(self,n):
        t=n*1_000_000_000
        return StreamObservation(SampleHeader('detector','detections',DataKind.DETECTIONS,'epoch',n,t,'ros-simulation',stamp(t+1),stamp(t),self.frame,'calibration',SourceKind.SIMULATION,QualityState.VALID),DataReference('slot-0','0'*64,0,'application/test'))
    def value(self,visible=True):return dict(detected=visible,detections=[dict(label='bus')] if visible else [],primary_label='bus' if visible else None)
    def test_actual_source_time_duplicate_and_epoch_fences(self):
        item=self.sample(1);now=stamp(1_000_000_002)
        self.assertTrue(self.events.publish_observation(item,self.value(),now));self.assertFalse(self.events.publish_observation(item,self.value(),now))
        event=self.events.read(0,'object.detected',now)[0]
        self.assertEqual(event.data.observed_at,item.header.captured_at)
        self.assertFalse(self.events.read(0,'object.detected',stamp(3_000_000_000)))
        for change in ({'generation':'other'},{'source_kind':SourceKind.REPLAY},{'quality':QualityState.DEGRADED}):
            with self.assertRaises(ValueError):self.events.publish_observation(replace(self.sample(2),header=replace(self.sample(2).header,**change)),self.value(),stamp(2_000_000_002))
    def test_long_stream_bounded_memory_and_replay_after_eviction(self):
        for n in range(1,10001):self.events.publish_observation(self.sample(n),self.value(),stamp(n*1_000_000_000+2))
        self.assertEqual(self.events.cursor,10000);self.assertEqual(len(self.events._events),4);self.assertEqual(len(self.events._last),1);self.assertEqual(len(self.events._ids),0)
        with self.assertRaises(ValueError):self.events.read(0,'object.detected',stamp(10_000_000_000_001))
        with self.assertRaises(ValueError):self.events.publish_observation(self.sample(1),self.value(),stamp(10_000_000_000_001))
        self.assertEqual(len(self.events.read(9999,'object.detected',stamp(10_000_000_000_002))),1)
    def test_loss_degraded_and_normal_recovery(self):
        self.events.publish_observation(self.sample(1),self.value(),stamp(1_000_000_002))
        self.assertTrue(self.events.publish_observation(self.sample(2),self.value(False),stamp(2_000_000_002)))
        self.assertTrue(self.events.degraded('detector','detections',stamp(2_100_000_000),'input unavailable'))
        self.assertFalse(self.events.degraded('detector','detections',stamp(2_200_000_000),'still unavailable'))
        self.assertTrue(self.events.publish_observation(self.sample(3),self.value(),stamp(3_000_000_002)))
        self.assertTrue(self.events.degraded('detector','detections',stamp(3_100_000_000),'new failure'))

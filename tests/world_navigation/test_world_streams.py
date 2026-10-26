from dataclasses import replace
import unittest

from tests.world_navigation import test_streams as stream_fixtures
from tests.world_navigation.test_streams import stamp
from vehicle_autonomy.world.model.service import WorldModel,FreshnessLimits
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.world.model.stream_input import observation
from vehicle_autonomy.world.sensors.fake import FakeDetectionSensor
from vehicle_autonomy.contracts.core.geometry import Vector3


class WorldStreamTests(unittest.TestCase):
    def test_same_publication_preserves_original_sample_and_reference_without_localization(self):
        case=stream_fixtures.StreamsTests();case.setUp();model=WorldModel('world',FreshnessLimits(100,100,100));model.register_stream(case.profile)
        sample=case.sample();model.ingest_stream(sample);cut=model.publish(stamp(50))
        self.assertEqual(cut.streams,(sample,));self.assertEqual(cut.streams[0].header.captured_at,stamp(10));self.assertIsNone(cut.localization)
        self.assertEqual(observation(to_json_value(sample)),sample)
        later=model.publish(stamp(111));self.assertFalse(later.streams)
        self.assertEqual([x.reason for x in later.freshness if x.component_id.startswith('stream:')],['expired'])
    def test_worker_withdrawal_cannot_reset_the_source_sequence_fence(self):
        case=stream_fixtures.StreamsTests();case.setUp();model=WorldModel('world',FreshnessLimits(100,100,100));model.register_stream(case.profile)
        sample=case.sample();model.ingest_stream(sample);model.stream_state.withdraw('gazebo')
        self.assertFalse(model.publish(stamp(30)).streams)
        with self.assertRaises(ValueError):model.ingest_stream(sample)
        model.ingest_stream(case.sample(sequence=2,source_ns=11,received_at=stamp(21),captured_at=stamp(11)))
        self.assertTrue(model.publish(stamp(31)).streams)
    def test_old_object_payloads_are_pruned_without_losing_producer_watermark(self):
        sensor=FakeDetectionSensor('camera');model=WorldModel('world',FreshnessLimits(100,100,100));model.max_observations=4
        values=[]
        for i in range(4):
            v=sensor.observe(object_id='object'+str(i),label='test',position=Vector3(0,0,0),confidence=1.,frame_id='odom',captured_at=stamp(i+1),received_at=stamp(i+2));values.append(v);model.ingest_observation(v)
        with self.assertRaises(ValueError):model.ingest_observation(sensor.observe(object_id='overflow',label='test',position=Vector3(0,0,0),confidence=1.,frame_id='odom',captured_at=stamp(10),received_at=stamp(11)))
        self.assertFalse(model.publish(stamp(200)).objects);self.assertFalse(model._observations)
        with self.assertRaises(ValueError):model.ingest_observation(values[0])
        self.assertLessEqual(len(model._producer_sequences),model.max_producers)

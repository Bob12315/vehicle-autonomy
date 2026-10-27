"""Freshness is checked after concurrent metadata I/O, never by retiming data."""
import json
from pathlib import Path
import tempfile
import unittest
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.world.model.service import WorldModel,FreshnessLimits
from vehicle_autonomy.world.model.stream_input import WorkerStreamInput
from tests.world_navigation import test_streams as fixtures
from tests.world_navigation.test_streams import stamp


class CollectorClockTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.root.chmod(0o700)
        fixture=fixtures.StreamsTests();fixture.setUp();self.sample=fixture.sample()
        self.model=WorldModel('world',FreshnessLimits(100,100,100))
        self.state=dict(schema=1,source_id='gazebo',source_kind='simulation',origin_id=fixture.frame.origin_id,ap_world_epoch=fixture.frame.origin_id,published_ns=150,error=None,generation=self.sample.header.generation,streams={'lidar':to_json_value(self.sample)})
        self.receiver=WorkerStreamInput(self.model,self.root,source_id='gazebo',origin_id=fixture.frame.origin_id,calibration_version=fixture.profile.calibration_version,frames={'lidar':fixture.frame},max_age_ns=10_000_000_000)
        self.write()
    def write(self):
        (self.root/'state.json').write_text(json.dumps(self.state))
    def test_concurrent_new_publication_is_checked_after_read_without_retiming(self):
        # The producer published at 150 while the reader started at 100.
        self.assertTrue(self.receiver.poll(stamp(100),clock=lambda:stamp(200)),self.receiver.error)
        sample,=self.model.publish(stamp(200)).streams
        self.assertEqual(sample,self.sample)
        self.assertEqual(sample.header.captured_at,stamp(10))
    def test_future_and_expired_worker_are_still_withdrawn(self):
        self.assertTrue(self.receiver.poll(stamp(100),clock=lambda:stamp(200)))
        self.state['published_ns']=201;self.write()
        self.assertFalse(self.receiver.poll(stamp(100),clock=lambda:stamp(200)))
        self.assertFalse(self.model.publish(stamp(200)).streams)
        self.state['published_ns']=150;self.write()
        self.assertFalse(self.receiver.poll(stamp(100),clock=lambda:stamp(500_000_151)))
    def test_reader_clock_regression_cannot_admit_data(self):
        self.assertFalse(self.receiver.poll(stamp(100),clock=lambda:stamp(99)))
        self.assertFalse(self.model.publish(stamp(200)).streams)

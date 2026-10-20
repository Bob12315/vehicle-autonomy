from datetime import datetime, timezone
import math
import unittest
from dataclasses import replace

from contracts.core.primitives import SchemaVersion
from contracts.core.time import TimePoint
from contracts.core.quality import QualityState
from contracts.sensor import Observation
from sensors.lidar.scan import ScanConfig, ScanProcessor, PlanarScan
from perception.obstacles import CollisionMonitor


def stamp(value, domain='test'):
    return TimePoint(value, datetime.now(timezone.utc), domain)


class LidarTests(unittest.TestCase):
    def test_scan_filter_nearest_unknown_and_provenance(self):
        processor = ScanProcessor(ScanConfig('lidar', self_box=(-.3,.3,-.3,.3,-.3,.3), ground_z=-.1, ground_tolerance=.03), 'test.lidar', 'e1')
        observation = processor.convert([(1.,0.,0.), (2.,0.,0.), (.25,0.,0.), (1.,0.,-.1), (1.,0.,10.), (math.nan,0.,0.)],
            frame='lidar', sequence=1, captured_at=stamp(100), received_at=stamp(200), epoch='e1')
        self.assertEqual(observation.data.ranges[360], 1.)
        self.assertIsNone(observation.data.ranges[0])
        self.assertEqual(observation.captured_at.monotonic_ns, 100)
        self.assertTrue(processor.health(stamp(300))['online'])
        self.assertEqual(processor.invalid_points, 1)

    def test_timestamp_frame_epoch_duplicate_loss_and_outage(self):
        processor = ScanProcessor(ScanConfig('lidar'), 'test.lidar', 'e1')
        kwargs = dict(frame='lidar', sequence=1, captured_at=stamp(100), received_at=stamp(200), epoch='e1')
        processor.convert([(1.,0.,0.)], **kwargs)
        for changes in ({}, {'sequence':0}, {'frame':'wrong'}, {'epoch':'old'},
                        {'captured_at':stamp(300)}, {'captured_at':stamp(100,'other')},
                        {'received_at':stamp(600_000_001)}):
            with self.assertRaises(ValueError):
                processor.convert([(1.,0.,0.)], **{**kwargs, **changes})
            self.assertFalse(processor.health(stamp(300))['online'])
        processor.convert([(1.,0.,0.)], **{**kwargs, 'sequence':4, 'captured_at':stamp(400), 'received_at':stamp(500)})
        self.assertEqual(processor.dropped, 2)
        self.assertFalse(processor.health(stamp(600_000_001))['online'])
        for points in ([], [(math.nan,0.,0.)], [(0.,0.,0.)]):
            with self.assertRaises(ValueError):
                processor.convert(points, **{**kwargs, 'sequence':5, 'captured_at':stamp(600), 'received_at':stamp(700)})

    def test_collision_fault_matrix_coverage_localization_and_time(self):
        monitor = CollisionMonitor()
        ranges = (3.,) * 720
        scan = PlanarScan(-math.pi, 2*math.pi/720, .2, 30., ranges)
        observation = Observation('s1',SchemaVersion(1,0),'test.lidar',1,stamp(100),stamp(100),QualityState.VALID,scan,'base_link')
        self.assertTrue(monitor.evaluate(observation,stamp(200),localization_valid=True)['motion_allowed'])
        for distance, allowed in ((.5,False),(.8,True),(None,False)):
            altered = list(ranges);altered[360]=distance
            result=monitor.evaluate(replace(observation,data=replace(scan,ranges=tuple(altered))),stamp(200),localization_valid=True)
            self.assertEqual(result['motion_allowed'],allowed)
            self.assertLess(result['speed_scale'],1)
            self.assertEqual(result['physical_stop'],'UNCONFIRMED')
        invalid = list(ranges);invalid[360]=math.nan
        with self.assertRaises(TypeError):
            replace(observation,data=replace(scan,ranges=tuple(invalid)))
        for source, now, localization in ((None,stamp(200),True),(observation,stamp(400_000_001),True),
                                         (observation,stamp(200,'other'),True),(observation,stamp(200),False),
                                         (replace(observation,frame_id='lidar'),stamp(200),True)):
            self.assertFalse(monitor.evaluate(source,now,localization_valid=localization)['motion_allowed'])

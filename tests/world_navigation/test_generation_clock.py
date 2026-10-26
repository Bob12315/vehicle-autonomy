from datetime import datetime,timezone
import unittest
from vehicle_autonomy.world.sensors.simulation_time import SimulationGenerationClock
from vehicle_autonomy.contracts.core.time import TimePoint

class GenerationClockTests(unittest.TestCase):
    def test_producer_time_not_late_receipt_and_original_clock_epoch(self):
        c=SimulationGenerationClock('owned',subscribe=False);c.offset=1000;c.margin=2
        c.observe(100,1000,2005,1005);c.observe(10_000_100,10_001_000,10_002_005,10_001_005)
        now=TimePoint(10_002_010,datetime(2026,1,1,tzinfo=timezone.utc),'test')
        self.assertEqual(c.lower_bound(100,now).monotonic_ns,1998)
        self.assertEqual(c.lower_bound(10_000_100,now,strict_previous=True).monotonic_ns,1998)
        c.observe(0,10_002_000,10_003_005,10_002_005)
        with self.assertRaises(ValueError):c.lower_bound(10_000_100,now)
    def test_clock_delay_or_host_clock_jump_fences_source(self):
        for lag,offset_jump in ((200_000_000,0),(0,10_000_000)):
            c=SimulationGenerationClock('owned',subscribe=False);c.offset=1000;c.margin=100
            c.observe(100,1000,2000+lag,1000+lag-offset_jump)
            if lag:
                self.assertFalse(c.samples);self.assertEqual(c.delayed,1)
                with self.assertRaises(ValueError):c.lower_bound(100,TimePoint(200_000_000,datetime.now(timezone.utc),'test'))
                c.observe(200,2000,3000,2000);self.assertEqual(len(c.samples),1)
            else:self.assertIsNotNone(c.fault)

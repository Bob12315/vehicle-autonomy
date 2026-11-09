import os,time,unittest
from unittest.mock import patch
from tests.simulation.process_resources import sample_cpu


class ProcessResourcesTests(unittest.TestCase):
    def test_kernel_clock_targets_the_requested_process(self):
        before=time.process_time_ns()
        sample=sample_cpu(os.getpid(),'current',{})
        after=time.process_time_ns()
        self.assertLessEqual(before,sample['cpu_time_ns'])
        self.assertLessEqual(sample['cpu_time_ns'],after)

    def test_interrupted_read_preserves_work_and_does_not_clip_high_usage(self):
        previous={'owned':(1_000_000,2_000_000)}
        with patch('tests.simulation.process_resources.time.monotonic_ns',side_effect=[2_000_000,4_000_001,5_000_000,5_000_002]),patch(
                'tests.simulation.process_resources.time.clock_gettime_ns',side_effect=[8_000_000,18_000_004]):
            interrupted=sample_cpu(os.getpid(),'owned',previous)
            self.assertIsNone(interrupted['cpu_percent'])
            self.assertEqual(previous['owned'],(1_000_000,2_000_000))
            later=sample_cpu(os.getpid(),'owned',previous)
        self.assertGreater(later['cpu_percent'],300.)
        self.assertEqual(later['cpu_time_ns'],18_000_004)


if __name__=='__main__':unittest.main()

"""A process or latest IMU receipt never substitutes for capture-time coverage."""
import unittest
from vehicle_autonomy.world.mapping.lio_timing import scan_coverage,capture_trace


class LioTiming(unittest.TestCase):
    def test_requires_brackets_for_all_five_capture_slices(self):
        times=list(range(0,201_000_000,5_000_000));slices=[10_000_000+i*20_000_000 for i in range(5)]
        result=scan_coverage(times,slices)
        self.assertEqual(result['imu_bracket_max_gap_ns'],5_000_000)
        self.assertEqual(result['point_imu_max_skew_ns'],0)
        self.assertGreater(result['imu_samples'],16)
        # The scan end has a perfect sample, but a gap inside it is unsafe.
        with self.assertRaises(ValueError):scan_coverage([t for t in times if not 20_000_000<t<60_000_000],slices)

    def test_initial_output_before_observed_imu_history_is_not_admitted(self):
        slices=[100_000_000+i*20_000_000 for i in range(5)]
        with self.assertRaises(TimeoutError):scan_coverage(list(range(200_000_000,400_000_000,5_000_000)),slices)
        with self.assertRaises(LookupError):scan_coverage(list(range(0,170_000_000,5_000_000)),slices)
        with self.assertRaises(ValueError):scan_coverage([0,5,5,10],slices)

    def test_empty_return_slice_requires_real_acquisition_evidence_not_fake_points(self):
        times=[20_000_000*i for i in range(5)]
        observed=capture_trace(dict(timebase_ns=0,capture_times_ns=times,return_counts=[0,10,20,30,0],points=60))
        result=scan_coverage(list(range(0,101_000_000,5_000_000)),observed['capture_times_ns'],
            return_times=times[1:4],pose_time_ns=60_000_000)
        self.assertEqual(result['actual_acquisition_count'],5)
        self.assertEqual(result['retained_point_capture_count'],3)
        self.assertEqual(result['imu_bracket_max_gap_ns'],5_000_000)
        with self.assertRaises(ValueError):capture_trace(dict(observed,capture_times_ns=times[1:]))
        with self.assertRaises(ValueError):capture_trace(dict(observed,return_counts=[1,10,20,30,0]))
        with self.assertRaises(ValueError):scan_coverage([0,5_000_000],times,return_times=[1])


if __name__=='__main__':unittest.main()

import unittest
from vehicle_autonomy.app.simulation.results import compare_reports


class SimulationResultTests(unittest.TestCase):
    def test_missing_and_null_metrics_remain_unknown(self):
        value = compare_reports({}, {})
        self.assertTrue(all(item['status'] == 'NOT_TESTED' and item['regression'] is None for item in value['metrics']))
        self.assertFalse(value['has_regression'])
        self.assertTrue(all(item['candidate'] == 'NOT_TESTED' for item in value['levels']))

    def test_level_and_measured_resource_regression(self):
        left = dict(scene_id='R01', vehicle='none', seed=1, levels={'L2': 'PASS'}, metrics={'rtf': 1., 'rss_mib': 100})
        right = dict(left, levels={'L2': 'FAIL'}, metrics={'rtf': .5, 'rss_mib': 150})
        value = compare_reports(left, right)
        self.assertTrue(value['has_regression'])
        self.assertTrue(value['levels'][1]['regression'])
        self.assertEqual(sum(item['regression'] is True for item in value['metrics']), 2)

    def test_different_seed_or_vehicle_cannot_be_compared_as_replay(self):
        with self.assertRaises(ValueError): compare_reports({'seed': 1}, {'seed': 2})
        with self.assertRaises(ValueError): compare_reports({'vehicle': 'plane'}, {'vehicle': 'copter'})
        with self.assertRaises(ValueError): compare_reports({}, {}, relative_tolerance=float('nan'))

import unittest
from vehicle_autonomy.app.bootstrap.navigation_security import profiles
from vehicle_autonomy.app.bootstrap.ros2_security import policy

class NavigationPermissionsTests(unittest.TestCase):
    def test_final_velocity_is_exclusive_and_viewer_has_no_goal_or_motion_right(self):
        p=profiles('/nav2_test');self.assertEqual(len(p),12)
        self.assertEqual([r for r,v in p.items() if '/nav2_test/cmd_vel_final' in v['topics']['publish']],['collision'])
        self.assertEqual(p['viewer']['topics']['publish'],[]);self.assertEqual(p['viewer']['actions']['call'],[])
        self.assertEqual(p['manager']['topics']['publish'],[])
        self.assertEqual(p['collision']['actions']['call'],[])
        self.assertIn(b'/parameter_events',policy(p))
    def test_reserved_or_ambiguous_namespace_cannot_expand_source_role_into_control_domain(self):
        for value in ('/slam_toolbox','/phase5','/nav2_x/y','/nav2_../x','/nav2_'):
            with self.assertRaises(ValueError):profiles(value)

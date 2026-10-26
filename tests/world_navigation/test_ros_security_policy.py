import unittest
import xml.etree.ElementTree as ET
from vehicle_autonomy.app.bootstrap.ros2_security import policy

class SecurityPolicyTests(unittest.TestCase):
    def test_readonly_profile_does_not_implicitly_grant_goal_or_final_velocity(self):
        p=ET.fromstring(policy({'viewer':{'topics':{'subscribe':['/map','/tf']}}}))
        self.assertFalse(p.findall('.//actions'))
        published=[x.text for x in p.findall('.//topics[@publish="ALLOW"]/topic')]
        self.assertEqual(published,['/parameter_events','/rosout'])
        self.assertFalse(p.findall('.//services[@request="ALLOW"]'))
    def test_typo_and_unknown_permission_rejected_before_provisioning(self):
        for value in ({'action':{}},{'actions':{'calls':['/navigate']}},{'topics':{'publish':'/*'}},{'topics':{'publish':['relative']}},):
            with self.assertRaises(ValueError):policy({'viewer':value})

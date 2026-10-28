from copy import deepcopy
from datetime import datetime, timezone
import unittest

from vehicle_autonomy.app.web.dashboard import dashboard
from vehicle_autonomy.contracts.core.time import TimePoint


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.now=TimePoint(20_000_000_000,datetime.now(timezone.utc),'host-monotonic-simulation')
        self.stamp=dict(monotonic_ns=19_000_000_000,clock_domain_id='host-monotonic-simulation')
        pose=dict(captured_at=self.stamp,value=dict(position=dict(x=1,y=2,z=3),orientation=dict(w=1,x=0,y=0,z=0)))
        self.state=dict(published_at=self.stamp,health=dict(quality='VALID',faults=[]),reported_pose=pose,
            reported_twist=dict(captured_at=self.stamp,value=dict(linear=dict(x=1,y=0,z=0))),operation=dict(armed=False,failsafe=False),
            battery=dict(voltage_v=99),telemetry=dict(fields=[dict(message_type='SYS_STATUS',received_at=self.stamp,
                availability='UNKNOWN_CAPTURE_TIME',value=dict(voltage_v=12),receive_fresh=True)]))
        self.snapshot=dict(vehicles=[dict(target='rover',kind='rover',connected=True,owned_simulation=True,
            world=dict(vehicle=self.state),display=dict(mode_name='HOLD'))],actions=[],missions=[])

    def value(self):return dashboard(self.snapshot,self.now)['vehicles'][0]

    def test_freshness_is_per_measurement_and_battery_uses_field_provenance(self):
        self.assertEqual(self.value()['position']['x'],1);self.assertEqual(self.value()['battery']['voltage_v'],12)
        self.state['reported_pose']=deepcopy(self.state['reported_pose'])
        self.state['reported_pose']['captured_at']['monotonic_ns']=1
        self.assertTrue(self.value()['fresh']);self.assertIsNone(self.value()['position']);self.assertIsNone(self.value()['heading_deg'])
        self.state['telemetry']['fields'][0]['received_at']=dict(self.stamp,monotonic_ns=1)
        self.assertIsNone(self.value()['battery'])

    def test_disconnect_stale_future_or_foreign_clock_clears_normal_values(self):
        for change in ({'monotonic_ns':1},{'monotonic_ns':30_000_000_000},{'clock_domain_id':'wrong'}):
            self.state['published_at']=dict(self.stamp,**change)
            v=self.value();self.assertFalse(v['fresh'])
            for field in ('position','velocity','attitude','mode','armed','failsafe','battery'):self.assertIsNone(v[field],field)
        self.state['published_at']=self.stamp;self.snapshot['vehicles'][0]['connected']=False
        self.assertIsNone(self.value()['position'])

    def test_three_vehicle_types_and_no_invented_airspeed(self):
        for kind in ('rover','copter','plane'):
            self.snapshot['vehicles'][0].update(kind=kind,target=kind)
            self.assertEqual(self.value()['type'],kind);self.assertIsNone(self.value()['airspeed_mps'])

from copy import deepcopy
import math
import unittest

from vehicle_autonomy.app.visualization.projection import Projection
from vehicle_autonomy.app.visualization.state import snapshot
from .helpers import sample,gps
from tests.web_ui.helpers import Harness


class ProjectionTests(unittest.TestCase):
    def accept(self,p,s,**kw):return p.accept(s,received_ns=2_000_000_000,roundtrip_s=.01,now_ns=kw.get('now_ns',2_000_000_000),stamp_for=kw.get('stamp_for',lambda t:t+10_000_000_000))
    def test_normalized_enu_is_not_swapped_again_and_full_3d_twist_is_body_flu(self):
        p=Projection('copter','copter');s=sample('copter');s['pose']['orientation']=dict(x=0.,y=math.sqrt(.5),z=0.,w=math.sqrt(.5));s['twist']['linear']=dict(x=0.,y=0.,z=-2.)
        v=self.accept(p,s);self.assertEqual(v['position'],[1,2,3]);self.assertAlmostEqual(v['body_linear'].x,2.);self.assertAlmostEqual(v['body_linear'].z,0.)
        self.assertEqual(v['world_linear'].z,-2.)
    def test_no_retimestamped_duplicate_or_stale_pose_and_path_is_cleared(self):
        p=Projection('rover','rover');s=sample();self.assertIsNotNone(self.accept(p,s));self.assertIsNone(self.accept(p,s));self.assertEqual(len(p.path),1)
        with self.assertRaises(ValueError):self.accept(p,s,now_ns=6_000_000_000)
        self.assertFalse(p.path)
    def test_invalid_identity_frame_gps_ekf_and_clock_never_publish(self):
        for key,value in [('target','plane'),('valid',False),('age_s',float('nan'))]:
            p=Projection('rover','rover');s=sample();s[key]=value
            with self.assertRaises(ValueError):self.accept(p,s)
            self.assertFalse(p.path)
        s=sample();s['origin']['axes']='NED'
        with self.assertRaises(ValueError):self.accept(Projection('rover','rover'),s)
        with self.assertRaises(ValueError):self.accept(Projection('rover','rover'),sample(),stamp_for=lambda _:0)
    def test_reset_epoch_clears_trajectory_and_jump_is_latched_until_readmission(self):
        p=Projection('rover','rover');s=sample();self.accept(p,s)
        s=deepcopy(s);s['sample_ns']='1100000000';s['pose']['position']['x']=100.
        with self.assertRaisesRegex(ValueError,'discontinuity'):self.accept(p,s)
        s['sample_ns']='1200000000'
        with self.assertRaisesRegex(ValueError,'readmission'):self.accept(p,s)
        s['epoch']='new';s['origin']['id']='new';self.assertIsNotNone(self.accept(p,s));self.assertEqual(len(p.path),1)
    def test_regressing_sample_and_ros_time_are_rejected(self):
        p=Projection('rover','rover');s=sample();self.accept(p,s);s['sample_ns']='999999999'
        with self.assertRaisesRegex(ValueError,'regressed'):self.accept(p,s)
        p=Projection('rover','rover');s=sample();self.accept(p,s);s['sample_ns']='1100000000'
        with self.assertRaisesRegex(ValueError,'ROS timestamp'):self.accept(p,s,stamp_for=lambda _:1)
    def test_path_budget_and_body_frame_data_remain_bounded(self):
        p=Projection('rover','rover',limit=3);s=sample();s['twist_frame']='base_link'
        for i in range(10):
            s['sample_ns']=str(1_000_000_000+i);self.accept(p,s,stamp_for=lambda _,i=i:100+i)
        self.assertEqual(len(p.path),3);self.assertEqual(p.path[-1]['stamp_ns'],109)


class StateTests(unittest.TestCase):
    def setUp(self):self.h=Harness(kinds=('rover','copter','plane'));self.addCleanup(self.h.close)
    def test_only_existing_fresh_vehicle_state_is_projected(self):
        self.assertFalse(snapshot(self.h.lab,'rover')['valid']);gps(self.h)
        for kind in ('rover','copter','plane'):
            value=snapshot(self.h.lab,kind);self.assertTrue(value['valid'],value);self.assertEqual(value['origin']['axes'],'ENU')
        self.h.drivers['rover'].fresh=False
        value=snapshot(self.h.lab,'rover');self.assertFalse(value['valid']);self.assertIsNone(value['pose'])
        self.assertFalse(self.h.drivers['rover'].writes)
    def test_unhealthy_ekf_overrides_heartbeat_and_invalid_gps_is_not_qualified(self):
        from dataclasses import replace
        from vehicle_autonomy.contracts.vehicle.telemetry import VehicleTelemetrySnapshot,TelemetryField,TelemetryAvailability,EkfTelemetry
        from vehicle_autonomy.contracts.core.quality import QualityState
        gps(self.h);driver=self.h.drivers['rover'];original=driver.snapshot
        def bad():
            world=original();v=world.vehicle;t=v.published_at
            field=TelemetryField('EKF_STATUS_REPORT',TelemetryAvailability.UNKNOWN_CAPTURE_TIME,QualityState.DEGRADED,EkfTelemetry(0,1.,1.,1.,1.,1.),None,None,t,True)
            return replace(world,vehicle=replace(v,telemetry=VehicleTelemetrySnapshot('session',1,1,t,(field,))))
        driver.snapshot=bad;self.assertFalse(snapshot(self.h.lab,'rover')['valid'])
    def test_stale_healthy_ekf_is_unknown_not_reported_healthy(self):
        from dataclasses import replace
        from vehicle_autonomy.contracts.vehicle.telemetry import VehicleTelemetrySnapshot,TelemetryField,TelemetryAvailability,EkfTelemetry
        from vehicle_autonomy.contracts.core.quality import QualityState
        gps(self.h);driver=self.h.drivers['copter'];original=driver.snapshot
        def stale():
            world=original();v=world.vehicle;t=v.published_at;old=replace(t,monotonic_ns=t.monotonic_ns-4_000_000_000)
            field=TelemetryField('EKF_STATUS_REPORT',TelemetryAvailability.UNKNOWN_CAPTURE_TIME,QualityState.DEGRADED,EkfTelemetry(11,1.,1.,1.,1.,1.),None,None,old,True)
            return replace(world,vehicle=replace(v,telemetry=VehicleTelemetrySnapshot('session',1,1,t,(field,))))
        driver.snapshot=stale;value=snapshot(self.h.lab,'copter');self.assertTrue(value['valid'],value);self.assertEqual(value['ekf_health'],'UNKNOWN')
    def test_only_actual_global_origin_is_exported_without_inventing_copter_reference(self):
        from tests.test_mavlink_state_adapter import Message,at
        from vehicle_autonomy.vehicles.rover.mavlink_state import RoverTelemetryState
        from vehicle_autonomy.vehicles.plane.mavlink_state import PlaneTelemetryState
        from vehicle_autonomy.vehicles.ardupilot.telemetry_state import ArduPilotTelemetryState
        for cls in (RoverTelemetryState,PlaneTelemetryState,ArduPilotTelemetryState):
            receiver=cls(vehicle_id='test',generation_id='world',link_session_id='link',source_system=1,source_component=1,max_sample_skew_ns=10,max_field_age_ns=100,link_timeout_ns=100)
            self.assertIsNone(receiver.local_reference())
            message=Message('GPS_GLOBAL_ORIGIN',latitude=-350000000,longitude=1490000000,altitude=584000,_vaf_signature_timestamp=1)
            receiver.ingest(message,captured_at=at(1),received_at=at(2))
            expected=None if cls is ArduPilotTelemetryState else (-35.,149.,584.)
            self.assertEqual(receiver.local_reference(),expected)

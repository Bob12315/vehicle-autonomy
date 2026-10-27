from dataclasses import replace
import unittest
from vehicle_autonomy.contracts.streams import SampleHeader,DataKind,SourceKind,FrameDescriptor,StreamObservation,DataReference
from vehicle_autonomy.contracts.core.geometry import Twist3,Vector3
from vehicle_autonomy.contracts.core.quality import QualityState
from vehicle_autonomy.engine.navigation.inputs import NavigationInput,RoverNavigationInputs
from tests import test_basic_actions as fixtures

class NavigationInputTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.BasicActionTests();self.f.setUp();w=self.f.world
        self.now=w.published_at
        self.world=replace(w,vehicle=replace(w.vehicle,operation=replace(w.vehicle.operation,native_mode='ARDUPILOT_CUSTOM_15')))
        kinds=((DataKind.SCAN,300_000_000),(DataKind.SLAM_POSE,500_000_000),(DataKind.MAP,10_000_000_000),(DataKind.TRANSFORM,500_000_000))
        self.requirements=[];observations=[]
        for kind,age in kinds:
            frame=FrameDescriptor('laser','FLU',str(w.version.generation_id)) if kind is DataKind.SCAN else FrameDescriptor('map','ENU','map-epoch')
            header=SampleHeader('owned-scan' if kind is DataKind.SCAN else 'owned-slam',kind.value,kind,'worker-epoch',1,100,'original-simulation-clock',self.now,self.now,frame,'rig-calibration',SourceKind.SIMULATION,QualityState.VALID)
            self.requirements.append(NavigationInput(header,age));observations.append(StreamObservation(header,DataReference('slot-0','0'*64,0,'application/json')))
        self.world=replace(self.world,streams=tuple(observations))
        self.guard=RoverNavigationInputs(world_generation=str(w.version.generation_id),vehicle_session=str(w.vehicle.telemetry.link_session_id),requirements=tuple(self.requirements))
    def tearDown(self):self.f.tearDown()
    def test_normal_and_earliest_source_expiry_are_explicit(self):
        self.assertEqual(self.guard.validate(self.world,self.now),min(self.world.vehicle.reported_pose.captured_at.monotonic_ns,self.world.vehicle.reported_twist.captured_at.monotonic_ns)+200_000_000)
        scan=self.world.streams[0];h=replace(scan.header,captured_at=replace(self.now,monotonic_ns=self.now.monotonic_ns-250_000_000))
        w=replace(self.world,streams=(replace(scan,header=h),)+self.world.streams[1:])
        self.assertEqual(self.guard.validate(w,self.now),self.now.monotonic_ns+50_000_000)
    def test_source_epoch_replay_quality_or_missing_data_cannot_pass(self):
        first=self.world.streams[0]
        for h in (replace(first.header,generation='other'),replace(first.header,source_kind=SourceKind.REPLAY),replace(first.header,quality=QualityState.UNAVAILABLE)):
            with self.assertRaises(ValueError):self.guard.validate(replace(self.world,streams=(replace(first,header=h),)+self.world.streams[1:]),self.now)
        with self.assertRaises(ValueError):self.guard.validate(replace(self.world,streams=()),self.now)
        with self.assertRaises(ValueError):self.guard.validate(self.world,replace(self.now,monotonic_ns=min(self.world.vehicle.reported_pose.captured_at.monotonic_ns,self.world.vehicle.reported_twist.captured_at.monotonic_ns)+200_000_000))
    def test_observed_motion_bound_and_session_are_required(self):
        v=self.world.vehicle;t=v.reported_twist
        for value in (Twist3(Vector3(.401,0,0),Vector3(0,0,0)),Twist3(Vector3(0,0,0),Vector3(0,0,.451))):
            with self.assertRaises(ValueError):self.guard.validate(replace(self.world,vehicle=replace(v,reported_twist=replace(t,value=value))),self.now)
        with self.assertRaises(ValueError):self.guard.validate(replace(self.world,vehicle=replace(v,telemetry=replace(v.telemetry,link_session_id='another-session'))),self.now)

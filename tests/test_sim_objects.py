import unittest
from datetime import datetime,timezone
from dataclasses import replace
from contracts.core.geometry import Transform3,Quaternion,Vector3
from contracts.core.time import TimePoint
from contracts.core.quality import QualityState
from sensors.simulation.objects import ObjectCalibration,ObjectProjector
from world_model.service import WorldModel,FreshnessLimits

class SimObjectTests(unittest.TestCase):
    def setUp(self):
        self.projector=ObjectProjector(ObjectCalibration('owned',Transform3(Vector3(1,0,0),Quaternion(0,0,0,1)),'measured fixture','sha256'), 'test')
        self.world=WorldModel('session',FreshnessLimits(100,100,100))
    def test_appear_move_disappear_duplicates_and_expiry(self):
        one=self.projector.project(0,100,{'target_1':Vector3(1,2,0)})[0]
        self.world.ingest_observation(one);self.assertEqual(self.world.publish(TimePoint(100,utc=datetime.now(timezone.utc),clock_domain_id='test')).objects[0].position.value,Vector3(2,2,0))
        self.assertEqual(self.projector.project(0,150,{'target_1':Vector3(4,2,0)}),())
        moved=self.projector.project(1,101,{'target_1':Vector3(2,2,0)})[0];self.world.ingest_observation(moved)
        self.assertEqual(self.world.publish(TimePoint(101,utc=datetime.now(timezone.utc),clock_domain_id='test')).objects[0].position.value.x,3)
        self.assertFalse(self.world.publish(TimePoint(250,utc=datetime.now(timezone.utc),clock_domain_id='test')).objects)
        absent=self.projector.project(200,300,{})[0];self.world.ingest_observation(absent)
        self.assertEqual(absent.quality,QualityState.UNAVAILABLE);self.assertFalse(self.world.publish(TimePoint(300,utc=datetime.now(timezone.utc),clock_domain_id='test')).objects)
    def test_clock_regression_invalidates_and_cross_domain_not_adopted(self):
        one=self.projector.project(10,100,{'target_1':Vector3(1,0,0)})[0];self.world.ingest_observation(one)
        tombstone=self.projector.project(9,101,{})[0];self.assertEqual(tombstone.quality,QualityState.UNAVAILABLE)
        self.assertEqual(self.projector.error,'simulation_clock_regressed')
        self.world.ingest_observation(replace(one,observation_id='other:1',producer_id='other',captured_at=TimePoint(100,utc=datetime.now(timezone.utc),clock_domain_id='other')))
        self.assertEqual(len(self.world.publish(TimePoint(100,utc=datetime.now(timezone.utc),clock_domain_id='test')).objects),1)

    def test_sequence_content_conflict_and_delayed_future_frames(self):
        one=self.projector.project(0,100,{'target_1':Vector3(1,0,0)})[0]
        self.world.ingest_observation(one);self.world.ingest_observation(one)
        with self.assertRaises(ValueError):self.world.ingest_observation(replace(one,data=replace(one.data,position=Vector3(9,9,9))))
        with self.assertRaises(ValueError):self.world.ingest_observation(replace(one,sequence=0))
        late=replace(one,sequence=2,observation_id='late',captured_at=TimePoint(50,utc=datetime.now(timezone.utc),clock_domain_id='test'),received_at=TimePoint(300,utc=datetime.now(timezone.utc),clock_domain_id='test'))
        self.world.ingest_observation(late);self.assertFalse(self.world.publish(TimePoint(300,utc=datetime.now(timezone.utc),clock_domain_id='test')).objects)
        future=replace(late,sequence=3,observation_id='future',captured_at=TimePoint(400,utc=datetime.now(timezone.utc),clock_domain_id='test'),received_at=TimePoint(400,utc=datetime.now(timezone.utc),clock_domain_id='test'))
        self.world.ingest_observation(future);self.assertFalse(self.world.publish(TimePoint(301,utc=datetime.now(timezone.utc),clock_domain_id='test')).objects)
        self.projector.project(5_000_000_000,200,{})
        self.assertEqual(self.projector.error,'simulation_clock_skew')

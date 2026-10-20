from dataclasses import replace
import math
import unittest

from contracts.core.primitives import SchemaVersion
from contracts.core.quality import QualityState
from contracts.sensor import Observation
from contracts.effects.vehicle import StopMotionEffect, TwistTargetEffect
from contracts.core.geometry import Twist3, Vector3
from deployment.collision_guard import ScanWriteGuard
from sensors.lidar.scan import PlanarScan
from tests import test_simulation_runtime as helpers


class CollisionWriterTests(unittest.TestCase):
    def test_sudden_obstacle_and_scan_outage_reject_at_existing_final_writer(self):
        h=helpers.SimulationRuntimeTests();h.setUp();self.addCleanup(h.runtime.shutdown)
        h.runtime.connect();h.cycle(h.heartbeat(mode=4,armed=True)+h.state_messages())
        current=[None]
        def scan(distance):
            now=h.clock()
            return Observation('scan',SchemaVersion(1,0),'test.lidar',1,now,now,QualityState.VALID,
                PlanarScan(-math.pi,math.pi/360,.2,30.,(distance,)*720),'base_link')
        current[0]=scan(3.)
        h.runtime.motion_guard=ScanWriteGuard(lambda:current[0])
        h.runtime.begin_run(allow_send=True)
        effect=TwistTargetEffect('base_link',Twist3(Vector3(.1,0,0),Vector3(0,0,0)),'drive')
        self.assertIsNone(h.runtime.submit_effect(effect,effect_id='queued').reason)
        # Fault after Effect admission, before the unique byte writer drains.
        current[0]=scan(.4);before=len(h.transports[-1].writes)
        h.cycle(h.state_messages())
        self.assertEqual(len(h.transports[-1].writes),before)
        self.assertEqual(h.runtime.effect_status('queued')['phase'],'REJECTED')
        current[0]=None
        h.runtime.submit_effect(effect,effect_id='no-scan');h.cycle(h.state_messages())
        self.assertEqual(len(h.transports[-1].writes),before)
        self.assertEqual(h.runtime.effect_status('no-scan')['phase'],'REJECTED')
        # Perception failure cannot prevent the original fenced Stop path.
        h.runtime.submit_effect(StopMotionEffect('drive'),effect_id='stop');h.cycle(h.state_messages())
        self.assertGreater(len(h.transports[-1].writes),before)
        self.assertNotEqual(h.runtime.effect_status('stop')['phase'],'REJECTED')

    def test_slowdown_turning_and_guard_composition(self):
        from types import SimpleNamespace
        from contracts.vehicle.command import TwistTargetCommand
        h=helpers.SimulationRuntimeTests();h.setUp();self.addCleanup(h.runtime.shutdown)
        h.runtime.connect();h.cycle(h.heartbeat(mode=4,armed=True)+h.state_messages())
        state=h.runtime.world_snapshot().vehicle;now=h.clock()
        obs=Observation('scan',SchemaVersion(1,0),'test.lidar',1,now,now,QualityState.VALID,
            PlanarScan(-math.pi,math.pi/360,.2,30.,(.9,)*720),'base_link')
        guard=ScanWriteGuard(lambda:obs)
        command=lambda v,w:SimpleNamespace(command=TwistTargetCommand('base_link',Twist3(Vector3(v,0,0),Vector3(0,0,w)),'s'))
        self.assertEqual(guard(command(.1,0),state,now),'collision_guard_speed_reduction_required')
        self.assertIsNone(guard(command(.03,0),state,now))
        self.assertIn('turning',guard(command(0,.1),state,now))
        composed=ScanWriteGuard(lambda:obs,previous=lambda *_:'map_rejected')
        self.assertEqual(composed(command(.03,0),state,now),'map_rejected')

"""Operator labels and stale diagnostics cannot create control readiness."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from tests import test_basic_actions as basic
from vehicle_autonomy.app.web.vehicle_display import vehicle_display


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.fixture=basic.BasicActionTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.world=self.fixture.world

    def display(self,kind,modes,world=None,now=None):
        world=world or self.world
        return vehicle_display(dict(kind=kind,connected=True),world,SimpleNamespace(mode_ids=modes),now or world.published_at)

    def test_same_native_number_has_vehicle_specific_name(self):
        self.assertEqual(self.display('rover',{'HOLD':4})['mode_name'],'HOLD')
        self.assertEqual(self.display('copter',{'GUIDED':4})['mode_name'],'GUIDED')

    def test_plane_ground_and_airborne_choices_keep_the_execution_policy(self):
        modes={'MANUAL':0,'GUIDED':15,'LOITER':12,'RTL':11}
        ground=self.fixture.sample(1,armed=False)
        view=self.display('plane',modes,ground)
        self.assertEqual(view['mode_choices'],['MANUAL'])
        self.assertIn('地面',view['control_hint'])
        armed_ground=self.fixture.sample(2,armed=True)
        self.assertEqual(self.display('plane',modes,armed_ground)['mode_choices'],[])
        from vehicle_autonomy.contracts.core.geometry import Vector3
        flying=self.fixture.sample(3,Vector3(0,0,50),armed=True)
        self.assertEqual(self.display('plane',modes,flying)['mode_choices'],['GUIDED','LOITER','RTL'])

    def test_stale_state_does_not_offer_modes_or_claim_arm_readiness(self):
        now=replace(self.world.published_at,monotonic_ns=self.world.published_at.monotonic_ns+4_000_000_000)
        view=self.display('copter',{'GUIDED':4},now=now)
        self.assertEqual(view['mode_choices'],[])
        self.assertIn('不代表可以解锁',view['control_hint'])
        self.assertGreaterEqual(view['pose_age_s'],4)
        self.assertIsNone(view['airspeed_mps'])

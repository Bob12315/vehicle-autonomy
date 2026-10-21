import json
import math
from pathlib import Path
import tempfile
import unittest

from actions.rover_maneuver import SPEC,ManeuverAction
from application.scenario_planning import StaticScene,catalog,resolve,build
from core.action_registry import ActionRegistry
from core.mission import MissionValidator
from actions.basic import register_basic
from core.sitl_mode_action import SITL_MODE_SPEC,SitlModeAction
from contracts.vehicle.ports import VehicleCapabilities
from environments.resources import Environment
from intelligence.designs import MissionDesign
from planning.models import Pose2D
from runtime.simulation_profile import SimulationProfile


def design(*steps):
    return {'schema':2,'decision':'propose','title':'Scenario','reason':'Explicit finite task',
            'steps':[{'mission':m,'parameters':p} for m,p in steps]}


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.environment=Environment.load('simulation/environments/yard.toml').bind('test-epoch')
        self.scene=StaticScene('simulation/scenes/yard.json',self.environment)
        self.catalog=catalog(self.environment)

    def parse(self,*steps):return MissionDesign.parse(json.dumps(design(*steps)),self.catalog)

    def test_strict_typed_parameters_and_finite_budgets(self):
        for mission,params in [('motion:drive',{'distance_m':True,'speed_mps':.15}),
            ('motion:drive',{'distance_m':11,'speed_mps':.15}),
            ('motion:drive',{'distance_m':1,'speed_mps':.15,'python':'run()'}),
            ('motion:turn',{'angle_deg':float('inf')}),
            ('motion:circle',{'radius_m':2,'laps':1.5,'direction':'left','speed_mps':.15}),
            ('motion:visit',{'waypoint':'UNKNOWN','speed_mps':.15})]:
            with self.subTest(mission=mission,params=params),self.assertRaises(ValueError):self.parse((mission,params))
        p=self.parse(('motion:drive',{'distance_m':10,'speed_mps':.15}),('motion:turn',{'angle_deg':720}))
        prepared,preview=resolve(p,self.environment,Pose2D(.25,0),self.scene)
        self.assertEqual(p.document(),design(('motion:drive',{'distance_m':10,'speed_mps':.15}),('motion:turn',{'angle_deg':720})))
        self.assertEqual(prepared[0].end.x,10.25)
        self.assertLess(preview['estimated_deadline_s'],600)
        self.assertAlmostEqual(prepared[1].turn_rad,4*math.pi)

    def test_relative_heading_full_footprint_and_known_obstacle_checks(self):
        p=self.parse(('motion:drive',{'distance_m':2,'speed_mps':.15}),('motion:turn',{'angle_deg':90}),
                     ('motion:drive',{'distance_m':2,'speed_mps':.15}))
        prepared,_=resolve(p,self.environment,Pose2D(.25,0),self.scene)
        self.assertAlmostEqual(prepared[2].end.x,2.25)
        self.assertAlmostEqual(prepared[2].end.y,2)
        with self.assertRaisesRegex(ValueError,'geofence'):
            resolve(self.parse(('motion:drive',{'distance_m':10,'speed_mps':.15})),self.environment,Pose2D(10,0),self.scene)
        with self.assertRaisesRegex(ValueError,'known_obstacle'):
            resolve(self.parse(('motion:drive',{'distance_m':8,'speed_mps':.15})),self.environment,Pose2D(.25,4),self.scene)
        with self.assertRaisesRegex(ValueError,'budget'):
            resolve(self.parse(('motion:circle',{'radius_m':3,'laps':3,'direction':'left','speed_mps':.08})),self.environment,Pose2D(10,5),self.scene)

    def test_circle_geometry_is_dense_and_closed_and_profile_is_explicit(self):
        p=self.parse(('motion:circle',{'radius_m':2,'laps':1,'direction':'left','speed_mps':.15}))
        prepared,_=resolve(p,self.environment,Pose2D(.25,0),self.scene);path=prepared[0].path
        self.assertGreater(len(path),300);self.assertAlmostEqual(path[-1].x,path[0].x)
        self.assertAlmostEqual(path[-1].y,path[0].y)
        self.assertGreater(max(p.y for p in path),3.99)
        profile=SimulationProfile.load('simulation/profiles/rover_yard.toml')
        self.environment.check_safety(profile.safety)
        small=Environment.load('simulation/environments/rover.toml')
        self.assertEqual(small.geofence.max_x,5)
        with self.assertRaises(ValueError):small.check_safety(profile.safety)

    def test_bound_plan_compiles_without_a_new_command_port(self):
        p=self.parse(('motion:drive',{'distance_m':1,'speed_mps':.15}))
        prepared,_=resolve(p,self.environment,Pose2D(.25,0),self.scene)
        registry=ActionRegistry();register_basic(registry);registry.register_typed(SPEC,ManeuverAction())
        registry.register_typed(SITL_MODE_SPEC,SitlModeAction())
        result=MissionValidator(registry).compile(build(prepared[0],15),VehicleCapabilities(frozenset({'arm','disarm','navigation','stop'})))
        self.assertEqual(len(result.steps),5)

    def test_scene_changes_are_latched_and_not_interpreted_as_sensor_updates(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'scene.json';path.write_text(Path('simulation/scenes/yard.json').read_text())
            scene=StaticScene(path,self.environment);path.write_text('{}')
            with self.assertRaisesRegex(ValueError,'static_scene_changed'):scene.check()

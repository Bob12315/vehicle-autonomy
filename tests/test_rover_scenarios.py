import json
import math
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace

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


class ManeuverFaultTests(ScenarioTests):
    def world(self):
        from tests import test_simulation_runtime as helpers
        fx=helpers.SimulationRuntimeTests();fx.setUp();fx.runtime.connect()
        fx.runtime.set_environment(self.environment.reference)
        fx.cycle(fx.heartbeat(mode=4,armed=True)+fx.state_messages())
        world=fx.runtime.world_snapshot()
        world=replace(world,vehicle=replace(world.vehicle,operation=replace(world.vehicle.operation,native_mode='ARDUPILOT_CUSTOM_15')))
        return world

    def sample(self,world,heading,seconds):
        from contracts.core.geometry import Pose3,Vector3,Quaternion
        now=replace(world.published_at,monotonic_ns=world.published_at.monotonic_ns+round(seconds*1e9))
        # Unit-only fixed drive axle at (.25,0); body origin moves during a pivot.
        p=Pose3(Vector3(.25-.25*math.cos(heading),-.25*math.sin(heading),0),Quaternion(0,0,math.sin(heading/2),math.cos(heading/2)))
        loc=replace(world.localization,pose=replace(world.localization.pose,value=p,captured_at=now),
                    twist=replace(world.localization.twist,captured_at=now))
        return replace(world,published_at=now,localization=loc)

    def test_turn_unwrap_requires_actual_two_revolutions_and_stop_feedback(self):
        from contracts.decision import EffectResult,EffectPhase,ActionOutcome
        p=self.parse(('motion:turn',{'angle_deg':720}));prepared,_=resolve(p,self.environment,Pose2D(.25,0),self.scene)
        world=self.world();instance=ManeuverAction().start(prepared[0],world)
        transmitted=(EffectResult('move','action',EffectPhase.TRANSMITTED),)
        instance.tick_with_results(self.sample(world,0,.1),transmitted)
        for i in range(1,8):
            output=instance.tick_with_results(self.sample(world,i*math.pi/2,i*.1+.1),transmitted)
            self.assertEqual(output.outcome,ActionOutcome.RUNNING)
            self.assertIsNone(instance.stop_boundary)
        output=instance.tick_with_results(self.sample(world,4*math.pi,1),transmitted)
        self.assertEqual(type(output.effects[0]).__name__,'StopMotionEffect')
        self.assertEqual(instance.tick_with_results(self.sample(world,4*math.pi,1.1),transmitted).outcome,ActionOutcome.RUNNING)
        done=transmitted+(EffectResult('stop','action',EffectPhase.COMPLETED),)
        instance.tick_with_results(self.sample(world,4*math.pi,1.2),done)
        self.assertEqual(instance.tick_with_results(self.sample(world,4*math.pi,1.8),done).outcome,ActionOutcome.SUCCEEDED)

    def test_waypoint_alignment_waits_for_stop_then_starts_a_fresh_drive_stream(self):
        from contracts.decision import EffectResult,EffectPhase
        from contracts.effects.vehicle import TwistTargetEffect,StopMotionEffect
        p=self.parse(('motion:visit',{'waypoint':'A','speed_mps':.15}))
        prepared,_=resolve(p,self.environment,Pose2D(.25,0),self.scene);world=self.world()
        instance=ManeuverAction().start(prepared[0],world)
        feedback=(EffectResult('align','action',EffectPhase.TRANSMITTED),)
        first=instance.tick_with_results(self.sample(world,math.pi/2,.1),feedback)
        self.assertIsInstance(first.effects[0],TwistTargetEffect)
        self.assertAlmostEqual(first.effects[0].target_twist.linear.x,0.)
        old_stream=instance.stream
        stop=instance.tick_with_results(self.sample(world,0,.3),feedback)
        self.assertIsInstance(stop.effects[0],StopMotionEffect)
        self.assertTrue(instance.initial_alignment)
        pending=feedback+(EffectResult('stop','action',EffectPhase.TRANSMITTED),)
        self.assertFalse(instance.tick_with_results(self.sample(world,0,.6),pending).effects)
        complete=feedback+(EffectResult('stop','action',EffectPhase.COMPLETED),)
        instance.tick_with_results(self.sample(world,0,.7),complete)
        instance.tick_with_results(self.sample(world,0,1.3),complete)
        self.assertFalse(instance.initial_alignment)
        self.assertNotEqual(instance.stream,old_stream)
        move=instance.tick_with_results(self.sample(world,0,1.5),complete)
        self.assertIsInstance(move.effects[0],TwistTargetEffect)
        self.assertGreater(move.effects[0].target_twist.linear.x,0.)

    def test_spinning_in_place_cannot_fake_a_driven_circle(self):
        from contracts.decision import EffectResult,EffectPhase
        p=self.parse(('motion:circle',{'radius_m':1.5,'laps':1,'direction':'left','speed_mps':.15}))
        prepared,_=resolve(p,self.environment,Pose2D(.25,0),self.scene);world=self.world()
        instance=ManeuverAction().start(prepared[0],world)
        feedback=(EffectResult('move','action',EffectPhase.TRANSMITTED),)
        for i in range(10):instance.tick_with_results(self.sample(world,i*math.pi/2,(i+1)*.1),feedback)
        self.assertAlmostEqual(instance.orbit,0.)
        self.assertIsNone(instance.stop_boundary)

    def test_stale_localization_cannot_complete_wait_or_motion(self):
        from contracts.decision import ActionOutcome
        world=self.world();p=self.parse(('motion:wait',{'duration_s':1}));prepared,_=resolve(p,self.environment,Pose2D(.25,0),self.scene)
        instance=ManeuverAction().start(prepared[0],world)
        stale=replace(world,published_at=replace(world.published_at,monotonic_ns=world.published_at.monotonic_ns+600_000_000))
        output=instance.tick(stale)
        self.assertEqual(output.outcome,ActionOutcome.FAILED);self.assertIn('stale',output.error)

    def test_long_corridor_corrects_lateral_error_using_local_preview(self):
        from contracts.core.geometry import Pose3,Vector3
        from contracts.decision import EffectResult,EffectPhase
        p=self.parse(('motion:visit',{'waypoint':'HOME','speed_mps':.15}))
        prepared,_=resolve(p,self.environment,Pose2D(10.25,0,math.pi),self.scene)
        world=self.sample(self.world(),math.pi,.1)
        pose=world.localization.pose.value
        loc=replace(world.localization,pose=replace(world.localization.pose,
            value=Pose3(Vector3(9.25,.1,0),pose.orientation)))
        world=replace(world,localization=loc)
        instance=ManeuverAction().start(prepared[0],world);instance.initial_alignment=False
        decision=instance.tick_with_results(world,(EffectResult('drive','action',EffectPhase.TRANSMITTED),))
        twist=decision.effects[0].target_twist
        self.assertGreater(twist.angular.z,.18)
        self.assertGreater(twist.linear.x,0)
        self.assertLessEqual(twist.linear.x,.15)

    def test_scene_change_after_queue_is_rejected_by_original_writer_but_stop_remains_allowed(self):
        from tests import test_simulation_runtime as helpers
        from deployment.scenario_guard import ScenarioGuard
        from contracts.core.geometry import Twist3,Vector3
        from contracts.effects.vehicle import TwistTargetEffect,StopMotionEffect
        fx=helpers.SimulationRuntimeTests();fx.setUp();fx.runtime.connect()
        fx.cycle(fx.heartbeat(mode=4,armed=True)+fx.state_messages());fx.runtime.begin_run(allow_send=True)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'scene.json';path.write_text(Path('simulation/scenes/yard.json').read_text())
            guard=ScenarioGuard(StaticScene(path,self.environment),self.environment)
            p=self.parse(('motion:drive',{'distance_m':1,'speed_mps':.15}))
            from actions.basic import yaw
            from guidance.path_following import drive_reference
            raw=fx.runtime.world_snapshot().localization.pose.value
            start=drive_reference(Pose2D(raw.position.x,raw.position.y,yaw(raw)))
            guard.parameters=resolve(p,self.environment,start,self.scene)[0][0]
            fx.runtime.motion_guard=guard
            motion=TwistTargetEffect('base_link',Twist3(Vector3(.15,0,0),Vector3(0,0,0)),'scenario')
            fx.runtime.submit_effect(motion,effect_id='initial');fx.cycle(fx.state_messages())
            self.assertEqual(len(fx.transports[0].writes),1)
            fx.runtime.submit_effect(motion,effect_id='queued');path.write_text('{}')
            fx.cycle(fx.state_messages())
            self.assertEqual(len(fx.transports[0].writes),1)
            self.assertIn('static_scene_changed',fx.runtime.effect_status('queued')['reason'])
            fx.runtime.submit_effect(StopMotionEffect('scenario'),effect_id='stop')
            fx.cycle(fx.state_messages());self.assertEqual(len(fx.transports[0].writes),2)


class ParameterAdmissionTests(unittest.TestCase):
    def test_approval_requires_fresh_matching_preview_anchor_and_private_child_scope(self):
        from tests import test_simulation_runtime as helpers
        from deployment.application_runtime import ApplicationRuntime
        from deployment.simulation_runtime import SimulationRuntime
        from vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
        from protocols.mavlink.constants import TYPE_GROUND_ROVER
        fx=helpers.SimulationRuntimeTests();fx.setUp()
        profile=SimulationProfile.load('simulation/profiles/rover_yard.toml')
        runtime=SimulationRuntime(profile,translator=ArduRoverCommandTranslator(mode_ids=profile.mode_ids),
            transport_factory=fx.make_transport,clock=fx.clock)
        app=ApplicationRuntime(profile,profile_name='rover_sim',allow_send=True,runtime=runtime,
            environment_config='simulation/environments/yard.toml',scenario_scene='simulation/scenes/yard.json')
        runtime.connect();fx.clock.advance();boot=fx.clock.ns//1_000_000
        hb=fx.sender.heartbeat_encode(TYPE_GROUND_ROVER,3,0,4,4).pack(fx.sender)
        global_position=fx.sender.global_position_int_encode(boot,-353632620,1491652370,584000,0,0,0,0,9000).pack(fx.sender)
        gps=fx.sender.gps_raw_int_encode(boot*1000,3,-353632620,1491652370,584000,100,100,0,9000,12).pack(fx.sender)
        fx.transports[-1].incoming.append(hb+fx.state_messages()+global_position+gps);app.cycle()
        app.connected_at_ns=fx.clock.ns-profile.warmup_ns
        catalog_=app.design_catalog();doc=design(('motion:drive',{'distance_m':1,'speed_mps':.15}))
        check=app.design_preflight(doc,catalog_['context']);self.assertTrue(check['eligible'],check)
        with self.assertRaisesRegex(ValueError,'anchor'):
            app.start_design_checked(doc,catalog_['context'],catalog_['session_id'])
        with self.assertRaisesRegex(ValueError,'moved since preview'):
            app.start_design_checked(doc,catalog_['context'],catalog_['session_id'],{**check['anchor'],'x':2})
        task=app.start_design_checked(doc,catalog_['context'],catalog_['session_id'],check['anchor'])
        self.assertEqual(task['status'],'WAITING_BOUNDARY')
        self.assertEqual(fx.transports[-1].writes,[])
        with self.assertRaises(ValueError):app.start_mission('scenario:'+task['configuration_sha256']+':0')
        self.assertFalse(runtime.authority.system_send)


    def test_unqualified_kinematics_are_rejected_before_runtime_construction(self):
        from unittest.mock import patch
        from deployment.application_runtime import ApplicationRuntime
        profile=replace(SimulationProfile.load('simulation/profiles/rover_yard.toml'),vehicle_id='simulation-compact-rover')
        with patch('deployment.application_runtime.SimulationRuntime',side_effect=AssertionError('runtime created')):
            with self.assertRaisesRegex(ValueError,'qualified target_rover'):
                ApplicationRuntime(profile,profile_name='rover_sim',scenario_scene='simulation/scenes/yard.json')

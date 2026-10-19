"""Geometry/config reuse across two actual SDFs and the same admission/Core."""
from dataclasses import replace
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from application.planning import ReadOnlyPlanningService
from actions.path_following import SPEC
from deployment.application_runtime import ApplicationRuntime
from deployment.navigation import NavigationConfig,NavigationSupervisor
from guidance.navigation_model import FRONT_AXLE,COMPACT_AXLE,resolve_model
from guidance.path_following import PolylineTracker,drive_reference
from mapping.grid import pose_to_json
from planning.models import Pose2D
from runtime.simulation_profile import SimulationProfile
from tests.simulation.model_geometry import measure
from tests.test_goal_navigation import Backend
from tests import test_path_following as helpers


class ModelTests(unittest.TestCase):
    def test_low_rate_actuation_preserves_front_geometry_and_baseline_controller(self):
        import xml.etree.ElementTree as ET
        base=Path('simulation/models/target_rover/model.sdf');nav=base.with_name('navigation.sdf')
        a,b=measure(base),measure(nav)
        for key in ('axle_x','track_m','radius_from_axle_m','body_size','body_mass_kg'):
            self.assertEqual(getattr(a,key),getattr(b,key))
        original,variant=ET.parse(base),ET.parse(nav)
        for control in variant.findall(".//plugin[@name='ArduPilotPlugin']/control"):
            control.find('p_gain').text='1';control.find('i_gain').text='0.1'
        self.assertEqual(ET.tostring(original.getroot()),ET.tostring(variant.getroot()))
        for path,expected in ((base,('1','0.1')),(nav,('4','0')),
                              (Path('simulation/models/compact_rover/model.sdf'),('4','0'))):
            for control in ET.parse(path).findall(".//plugin[@name='ArduPilotPlugin']/control"):
                self.assertEqual((control.findtext('p_gain'),control.findtext('i_gain')),expected)
                self.assertEqual(control.findtext('cmd_max'),'8')

    def test_navigation_feedforward_matches_actual_track_wheels_and_servo_mapping(self):
        import xml.etree.ElementTree as ET
        for name,parameter in (('target_rover','rover_navigation'),('compact_rover','compact_rover_navigation')):
            path=Path('simulation/models')/name/'model.sdf'
            tree=ET.parse(path);geometry=measure(path)
            control=tree.find(".//plugin[@name='ArduPilotPlugin']/control")
            joint=tree.find(f".//joint[@name='{control.findtext('jointName')}']")
            wheel=tree.find(f".//link[@name='{joint.findtext('child')}']")
            radius=float(wheel.findtext('collision/geometry/cylinder/radius'))
            offset=float(control.findtext('offset'));self.assertEqual(offset,-.5)
            maximum=float(control.findtext('multiplier'))*(1+offset)
            params=dict(line.split() for line in (Path('simulation/params')/(parameter+'.parm')).read_text().splitlines()
                        if line.strip() and not line.startswith('#'))
            self.assertAlmostEqual(float(params['ATC_STR_RAT_FF']),geometry.track_m/(2*radius*maximum),places=7)
            self.assertLessEqual(float(params['ATC_STR_RAT_I']),.02)
            self.assertLessEqual(float(params['ATC_STR_RAT_IMAX']),.1)
            self.assertAlmostEqual(float(params['CRUISE_SPEED']),radius*maximum)
            self.assertEqual(float(params['CRUISE_THROTTLE']),100)
            self.assertLessEqual(float(params['ATC_SPEED_I']),.05)
            for channel in (1,2):self.assertGreaterEqual(float(params[f'MAV{channel}_POSITION']),10)

    def test_two_sdfs_have_distinct_verified_drive_axles_and_full_caster_envelopes(self):
        pairs=((FRONT_AXLE,'target_rover'),(COMPACT_AXLE,'compact_rover'))
        geometries=[]
        for model,name in pairs:
            geometry=measure(Path('simulation/models')/name/'model.sdf');geometries.append(geometry)
            self.assertAlmostEqual(geometry.axle_x,model.base_to_reference_x_m)
            self.assertLessEqual(geometry.radius_from_axle_m,model.footprint_radius_m)
            self.assertGreaterEqual(model.path_clearance_m,model.footprint_radius_m+model.cross_track_m+.08-1e-9)
        self.assertNotEqual(geometries[0].track_m,geometries[1].track_m)
        self.assertNotEqual(geometries[0].body_size,geometries[1].body_size)
        self.assertNotEqual(geometries[0].body_mass_kg,geometries[1].body_mass_kg)
        self.assertNotEqual(FRONT_AXLE.sha256,COMPACT_AXLE.sha256)

    def test_reference_transform_and_guidance_obey_injected_command_bounds(self):
        p=drive_reference(Pose2D(1,2,math.pi/2),COMPACT_AXLE)
        self.assertAlmostEqual(p.x,1);self.assertAlmostEqual(p.y,2.18)
        model=replace(FRONT_AXLE,max_speed_mps=.1,max_yaw_rate_rps=.15)
        tracker=PolylineTracker((Pose2D(0,0),Pose2D(2,0)),model=model,stop_turn=True)
        straight=tracker.update(Pose2D(0,0))
        turn=tracker.update(Pose2D(0,0,math.pi/2))
        self.assertLessEqual(straight.speed_mps,.1);self.assertLessEqual(abs(turn.yaw_rate_rps),.15)
        for fields in ({'footprint_radius_m':.9},{'max_speed_mps':.2},{'base_to_reference_x_m':float('nan')},
                       {'motion_effects':('PoseTargetEffect',)}):
            with self.assertRaises(ValueError):replace(FRONT_AXLE,**fields)

    def test_compact_reference_plan_uses_same_admission_and_typed_action_contract(self):
        h=helpers.NavigationTests();h.setUp();self.addCleanup(h.doCleanups)
        nav=NavigationSupervisor(replace(h.supervisor.config,model=COMPACT_AXLE),h.harness.runtime.profile.safety)
        nav.update_map(h.mapped,{'odom_in_map':pose_to_json(helpers.IDENTITY)},h.now,h.world.version.generation_id)
        result=ReadOnlyPlanningService(lambda:nav.context,Backend(),lambda:h.now).plan(Pose2D(.18,0),Pose2D(.8,0),clearance_m=.95)
        h.path.write_text(json.dumps({'ok':True,'result':result.document()}))
        params=nav.admit(h.world,h.now);SPEC.validate_parameters(params)
        self.assertEqual(params.model,COMPACT_AXLE);self.assertAlmostEqual(params.poses[0].x,.18)
        # P19 paths carry geometry, not a model authorization. Each model
        # independently checks its own current reference and footprint.
        self.assertEqual(h.supervisor.admit(h.world,h.now).model,FRONT_AXLE)
        self.assertFalse(h.harness.runtime.authority.system_send)

    def test_navigation_writer_rejects_unmodelled_motion_axes(self):
        from contracts.core.geometry import Twist3,Vector3
        from contracts.vehicle.command import TwistTargetCommand
        from types import SimpleNamespace
        h=helpers.NavigationTests();h.setUp();self.addCleanup(h.doCleanups)
        h.admit()
        command=SimpleNamespace(command=TwistTargetCommand('base_link',Twist3(Vector3(.1,.01,0),Vector3(0,0,0)),'stream'))
        self.assertEqual(h.supervisor.write_guard(command,h.world.vehicle,h.now),'navigation_requires_planar_forward_twist')

    def test_deadband_compensation_never_overrides_yaw_braking_feedback(self):
        tracker=PolylineTracker((Pose2D(0,0),Pose2D(2,0)),stop_turn=True)
        out=tracker.update(Pose2D(0,0,-.15),measured_yaw_rate=.3)
        self.assertLess(out.yaw_rate_rps,0)

    def test_explicit_reverse_tracks_a_backwards_bend_without_changing_yaw_convention(self):
        poses=(Pose2D(0,0),Pose2D(-1,0),Pose2D(-1,-1))
        tracker=PolylineTracker(poses,stop_turn=True,allow_reverse=True)
        pose=Pose2D(0,0);rate=0;maximum=0
        for _ in range(800):
            out=tracker.update(pose,rate);maximum=max(maximum,out.cross_track_m)
            self.assertGreaterEqual(out.speed_mps,-.1);self.assertLessEqual(out.speed_mps,0)
            if out.arrived:break
            rate=out.yaw_rate_rps
            pose=Pose2D(pose.x+out.speed_mps*math.cos(pose.yaw)*.1,
                        pose.y+out.speed_mps*math.sin(pose.yaw)*.1,pose.yaw+rate*.1)
        self.assertTrue(out.arrived);self.assertLess(maximum,.15)
        default=PolylineTracker(poses,stop_turn=True).update(Pose2D(0,0))
        self.assertEqual(default.speed_mps,0)

    def test_final_writer_reverse_range_requires_frozen_explicit_permission(self):
        from contracts.core.geometry import Twist3,Vector3
        from contracts.vehicle.command import TwistTargetCommand
        from types import SimpleNamespace
        for allowed,speed,expected in ((False,-.05,'navigation_velocity_bound_exceeded'),(True,-.09,None),
                                       (True,-.11,'navigation_velocity_bound_exceeded')):
            h=helpers.NavigationTests();h.setUp();self.addCleanup(h.doCleanups)
            h.supervisor.config=replace(h.supervisor.config,allow_reverse=allowed)
            parameters=h.admit();self.assertEqual(parameters.allow_reverse,allowed)
            command=SimpleNamespace(command=TwistTargetCommand('base_link',Twist3(Vector3(speed,0,0),Vector3(0,0,0)),'stream'))
            self.assertEqual(h.supervisor.write_guard(command,h.world.vehicle,h.now),expected)

    def test_model_and_explicit_deployment_profile_must_match_before_connect(self):
        with TemporaryDirectory() as d:
            config=Path(d)/'nav.toml';config.write_text(f'schema=1\nmodel="{COMPACT_AXLE.model_id}"\nplan_path="{d}/plan.json"\ntimeout_ns=70000000000\n')
            loaded=NavigationConfig.load(config)
            self.assertEqual(loaded.model,COMPACT_AXLE);self.assertEqual(len(loaded.source_sha256),64)
            profile=SimulationProfile.load('simulation/profiles/rover.toml')
            with self.assertRaisesRegex(ValueError,'deployment'):
                ApplicationRuntime(profile,profile_name='rover_sim',mapping_config='unused',navigation_config=config)
            config.write_text(config.read_text().replace(COMPACT_AXLE.model_id,'unreviewed_rover'))
            with self.assertRaises(ValueError):NavigationConfig.load(config)
        with self.assertRaises(ValueError):resolve_model('arbitrary')

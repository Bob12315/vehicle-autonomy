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

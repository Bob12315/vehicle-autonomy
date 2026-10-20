"""Motion admission, frame binding, live fences and observed stop semantics."""
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from actions.path_following import FollowPathAction
from contracts.core.geometry import Pose3, Quaternion, Twist3, Vector3
from contracts.core.primitives import ResourceVersion
from contracts.decision import ActionOutcome, EffectPhase, EffectResult, ExitReason
from contracts.effects.vehicle import StopMotionEffect, TwistTargetEffect
from contracts.world.models import ResourceReference
from deployment.navigation import NavigationConfig, NavigationSupervisor
from guidance.path_following import PlanarBinding, PolylineTracker
from localization.reported import ReportedPoseLocalization
from mapping.exchange import MapInput
from mapping.grid import OccupancyGrid, pose_to_json
from planning.models import MapContext, PathCandidate, PlanRequest, Pose2D, VerifiedPath
from tests import test_simulation_runtime as helpers

IDENTITY = Pose3(Vector3(0,0,0), Quaternion(0,0,0,1))


class GuidanceTests(unittest.TestCase):
    def test_drive_reference_matches_model_and_pivot_is_not_body_stationary(self):
        import xml.etree.ElementTree as ET
        from guidance.path_following import DRIVE_OFFSET_M, drive_reference
        model=ET.parse("simulation/models/target_rover/model.sdf")
        for wheel in ("front_left_wheel","front_right_wheel"):
            offset=float(model.find(f"model/link[@name='{wheel}']/pose").text.split()[0])
            self.assertEqual(offset,DRIVE_OFFSET_M)
        # Same fixed axle point, body turns ninety degrees around it.
        a=drive_reference(Pose2D(0,0))
        b=drive_reference(Pose2D(.25,-.25,math.pi/2))
        self.assertAlmostEqual(a.x,b.x)
        self.assertAlmostEqual(a.y,b.y)

    def test_explicit_rotated_translated_binding_roundtrip(self):
        binding = PlanarBinding(2,-3,.7)
        p = Pose2D(.3,.4,-1)
        result = binding.to_odom(binding.to_map(p))
        for a,b in zip((p.x,p.y,p.yaw), (result.x,result.y,result.yaw)):
            self.assertAlmostEqual(a,b)
        with self.assertRaises(ValueError):PlanarBinding(float("nan"),0,0)

    def test_turning_and_crossing_do_not_jump_to_goal(self):
        tracker = PolylineTracker((Pose2D(0,0),Pose2D(2,0),Pose2D(2,2),Pose2D(0,0)))
        value = tracker.update(Pose2D(0,0))
        self.assertFalse(value.arrived)
        self.assertEqual(value.progress_m,0)
        turn = tracker.update(Pose2D(0,0,math.pi/2))
        self.assertEqual(turn.speed_mps,0)
        self.assertLess(turn.yaw_rate_rps,0)
        self.assertLessEqual(abs(turn.yaw_rate_rps),.25)

    def test_pure_kinematic_corner_tracking_and_arrival(self):
        tracker = PolylineTracker((Pose2D(0,0),Pose2D(1,0),Pose2D(1,1)))
        p = Pose2D(0,0)
        maximum = 0
        for _ in range(1500):
            value = tracker.update(p)
            maximum = max(maximum,value.cross_track_m)
            if value.arrived:break
            yaw = math.atan2(math.sin(p.yaw+value.yaw_rate_rps*.1),math.cos(p.yaw+value.yaw_rate_rps*.1))
            p = Pose2D(p.x+value.speed_mps*math.cos(yaw)*.1,p.y+value.speed_mps*math.sin(yaw)*.1,yaw)
        self.assertTrue(value.arrived)
        self.assertLess(maximum,.2)

    def test_axle_guidance_with_small_steering_deadzone_stays_inside_guard(self):
        tracker=PolylineTracker((Pose2D(0,0),Pose2D(0,2),Pose2D(.8,2.5)),stop_turn=True)
        p=Pose2D(0,0);maximum=0;rate=0
        for _ in range(700):
            value=tracker.update(p,rate);maximum=max(maximum,value.cross_track_m)
            if value.arrived:break
            rate=value.yaw_rate_rps if abs(value.yaw_rate_rps)>=.15 else 0
            heading=math.atan2(math.sin(p.yaw+rate*.1),math.cos(p.yaw+rate*.1))
            p=Pose2D(p.x+value.speed_mps*math.cos(heading)*.1,p.y+value.speed_mps*math.sin(heading)*.1,heading)
        self.assertTrue(value.arrived);self.assertLess(maximum,.15)


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.harness = helpers.SimulationRuntimeTests()
        self.harness.setUp()
        self.addCleanup(self.harness.runtime.shutdown)
        r = self.harness.runtime
        r.connect()
        self.harness.cycle(self.harness.heartbeat(mode=4,armed=True)+self.harness.state_messages())
        self.world = r.world_snapshot()
        self.now = self.world.published_at
        pose = replace(self.world.vehicle.reported_pose, value=IDENTITY)
        state = replace(self.world.vehicle, reported_pose=pose,
            operation=replace(self.world.vehicle.operation, native_mode="ARDUPILOT_CUSTOM_15"))
        environment = ResourceReference("test.environment",ResourceVersion("environment",1))
        self.world = replace(self.world, vehicle=state, localization=ReportedPoseLocalization().estimate(state), environment=environment)
        self.grid = OccupancyGrid("map",.1,100,100,Pose3(Vector3(-5,-5,0),IDENTITY.orientation),(0,)*10000)
        self.reference = ResourceReference("ros2.slam_toolbox.map",ResourceVersion("slam-A",1))
        self.mapped = self.map_input(self.grid)
        self.world = replace(self.world,map=self.reference)
        self.path = Path(self.directory.name)/"plan.json"
        self.supervisor = NavigationSupervisor(NavigationConfig(self.path,70_000_000_000),r.profile.safety)
        self.update()
        context = self.supervisor.context
        start, goal = Pose2D(.25,0),Pose2D(1.25,0)
        request = PlanRequest("plan-A",context,start,goal,self.now,self.now.monotonic_ns+15_000_000_000,.95)
        candidate = PathCandidate(request.request_id,context.sha256,context.frame_epoch,"map",(start,goal))
        self.document = VerifiedPath(request,candidate,self.now,request.deadline_ns,1.,"nav2.SmacPlanner2D.jazzy").document()
        self.write()

    def map_input(self, grid, revision=1):
        reference = replace(self.reference,version=ResourceVersion("slam-A",revision))
        return MapInput(reference,self.now,grid,hashlib.sha256(grid.encoded()).hexdigest())

    def update(self, mapped=None, transform=IDENTITY, epoch=None):
        self.supervisor.update_map(mapped or self.mapped,{"odom_in_map":pose_to_json(transform)},self.now,
                                   epoch or self.world.version.generation_id)

    def write(self):
        self.path.write_text(json.dumps({"ok":True,"result":self.document}))

    def admit(self):
        return self.supervisor.admit(self.world,self.now)

    def sample(self, seconds, position=None):
        now = replace(self.now,monotonic_ns=self.now.monotonic_ns+int(seconds*1e9))
        state = self.world.vehicle
        state = replace(state,published_at=now,
            reported_pose=replace(state.reported_pose,captured_at=now,value=Pose3(position or Vector3(0,0,0),IDENTITY.orientation)),
            reported_twist=replace(state.reported_twist,captured_at=now))
        return replace(self.world,published_at=now,vehicle=state,localization=ReportedPoseLocalization().estimate(state))

    def test_admission_is_immutable_single_use_and_not_file_authority(self):
        p = self.admit()
        self.assertEqual(p.poses,(Pose2D(.25,0),Pose2D(1.25,0)))
        with self.assertRaises(AttributeError):p.timeout_ns = 100
        self.assertFalse(self.harness.runtime.authority.system_send)
        self.supervisor.consume()
        self.supervisor.finish()
        with self.assertRaisesRegex(ValueError,"consumed"):self.admit()

    def test_recording_expiry_wrong_frames_and_underinflation_rejected(self):
        original = json.loads(json.dumps(self.document))
        changes = ({"frame_epoch":"old"},{"clock_domain_id":"other"},
                   {"valid_until_ns":self.now.monotonic_ns},{"clearance_m":.55},
                   {"executable":True},{"length_m":0},{"poses":[[0,0,0],[float("nan"),0,0]]})
        for change in changes:
            self.document = {**original,**change};self.write()
            with self.subTest(change=change), self.assertRaises(ValueError):self.admit()
        self.document = original
        self.document["map"]["source_kind"] = "recorded_map";self.write()
        with self.assertRaisesRegex(ValueError,"live map"):self.admit()

    def test_start_distance_geofence_and_path_collision_checked(self):
        with self.assertRaisesRegex(ValueError,"too far"):
            self.supervisor.admit(self.sample(0,Vector3(.3,0,0)),self.now)
        cells=list(self.grid.cells);cells[50*100+55]=100
        self.update(self.map_input(replace(self.grid,cells=tuple(cells)),2))
        self.world = replace(self.world,map=self.supervisor.context.reference)
        with self.assertRaisesRegex(ValueError,"intersects"):self.admit()

    def test_changed_safe_map_revalidated_obstacle_and_unknown_latch_failure(self):
        for occupancy in (100,-1):
            self.admit()
            cells=list(self.grid.cells);cells[0]=100
            self.update(self.map_input(replace(self.grid,cells=tuple(cells)),2))
            self.assertIsNone(self.supervisor.view.error)
            self.assertEqual(self.supervisor.revalidations,1)
            cells[50*100+55]=occupancy
            self.update(self.map_input(replace(self.grid,cells=tuple(cells)),3))
            self.assertIn("intersects",self.supervisor.view.error)
            self.update()
            self.assertIsNotNone(self.supervisor.view.error)
            self.supervisor.finish()
            self.update()

    def test_epoch_alignment_and_map_age_are_fail_closed(self):
        for kind in ("epoch","alignment","age","loss"):
            self.admit()
            if kind == "epoch":self.update(epoch="new-world")
            if kind == "alignment":self.update(transform=replace(IDENTITY,position=Vector3(.11,0,0)))
            if kind == "age":
                later=replace(self.now,monotonic_ns=self.now.monotonic_ns+2_500_000_001)
                self.supervisor.update_map(self.mapped,{"odom_in_map":pose_to_json(IDENTITY)},later,self.world.version.generation_id)
            if kind == "loss":self.supervisor.update_map(None,{},self.now,self.world.version.generation_id)
            self.assertIsNotNone(self.supervisor.view.error,kind)
            self.supervisor.finish();self.update()

    def test_plan_regular_file_bound_and_latched_mutation(self):
        self.admit()
        self.path.write_text("{}");self.update()
        self.assertEqual(self.supervisor.view.error,"navigation_plan_file_changed")
        self.write();self.update()
        self.assertIsNotNone(self.supervisor.view.error)
        self.supervisor.finish()
        target=self.path.with_suffix(".target");self.path.rename(target);self.path.symlink_to(target)
        with self.assertRaises(OSError):self.admit()

    def test_action_uses_typed_effects_and_map_loss_keeps_observed_stop_exit(self):
        action = FollowPathAction(self.supervisor.reader).start(self.admit(),self.world)
        decision = action.tick(self.world)
        self.assertIsInstance(decision.effects[0],TwistTargetEffect)
        self.supervisor.update_map(None,{},self.now,self.world.version.generation_id)
        failed = action.tick(self.world)
        self.assertEqual(failed.outcome,ActionOutcome.FAILED)
        stop = action.exit_with_results(self.sample(.1),ExitReason.FAILED,())
        self.assertIsInstance(stop.effects[0],StopMotionEffect)
        result = (EffectResult("stop","action",EffectPhase.COMPLETED),)
        self.assertFalse(action.exit_with_results(self.sample(.2),ExitReason.FAILED,result).complete)
        self.assertTrue(action.exit_with_results(self.sample(2.3),ExitReason.FAILED,result).complete)

    def test_deadline_and_excess_cross_track_require_stop(self):
        p=self.admit()
        for world, reason in ((self.sample(71),"deadline"),(self.sample(.1,Vector3(0,.21,0)),"cross_track")):
            action=FollowPathAction(self.supervisor.reader).start(p,self.world)
            self.assertIn(reason,action.tick(world).error)

    def test_goal_position_alone_cannot_claim_transmitted_completion(self):
        action=FollowPathAction(self.supervisor.reader).start(self.admit(),self.world)
        action.tick(self.world)
        for seconds,x in ((1,.3),(2,.6),(3,1),(5,1)):
            self.assertEqual(action.tick(self.sample(seconds,Vector3(x,0,0))).outcome,ActionOutcome.RUNNING)
        result=(EffectResult("twist","action",EffectPhase.TRANSMITTED),)
        self.assertEqual(action.tick_with_results(self.sample(6,Vector3(1,0,0)),result).outcome,ActionOutcome.RUNNING)
        self.assertEqual(action.tick_with_results(self.sample(7.1,Vector3(1,0,0)),result).outcome,ActionOutcome.SUCCEEDED)

    def test_last_write_guard_rechecks_file_after_poll(self):
        from contracts.vehicle.command import TwistTargetCommand
        from types import SimpleNamespace
        self.admit()
        command=SimpleNamespace(command=TwistTargetCommand("base_link",Twist3(Vector3(.1,0,0),Vector3(0,0,0)),"stream"))
        self.assertIsNone(self.supervisor.write_guard(command,self.world.vehicle,self.now))
        self.path.write_text("{}");  # mutation after update_map, before write
        self.assertEqual(self.supervisor.write_guard(command,self.world.vehicle,self.now),"navigation_plan_file_changed")

    def test_registered_mission_compiles_without_device_ports(self):
        from actions.basic import register_basic
        from actions.path_following import SPEC
        from applications.navigation import build
        from contracts.vehicle.ports import VehicleCapabilities
        from core.action_registry import ActionRegistry
        from core.mission import MissionValidator
        from core.sitl_mode_action import SITL_MODE_SPEC, SitlModeAction
        registry=ActionRegistry();register_basic(registry)
        registry.register_typed(SITL_MODE_SPEC,SitlModeAction())
        registry.register_typed(SPEC,FollowPathAction(self.supervisor.reader))
        plan=build(self.admit(),15)
        compiled=MissionValidator(registry).compile(plan,VehicleCapabilities(frozenset({"arm","disarm","navigation"})))
        self.assertEqual([step.step.step_id for step in compiled.steps],["mode","arm","follow_path","disarm"])
        self.assertFalse(hasattr(self.supervisor.reader,"write_guard"))
        self.assertFalse(hasattr(self.supervisor.reader,"admit"))

    def test_configuration_requires_bounded_explicit_local_simulation(self):
        from deployment.application_runtime import ApplicationRuntime
        path=Path(self.directory.name)/"navigation.toml"
        path.write_text(f'schema=1\nmodel="target_rover_front_axle_v1"\nplan_path="{self.path}"\ntimeout_ns=70000000000\n')
        self.assertEqual(NavigationConfig.load(path).timeout_ns,70_000_000_000)
        path.write_text('schema=1\nmodel="target_rover_front_axle_v1"\nplan_path="relative.json"\ntimeout_ns=70000000000\n')
        with self.assertRaises(ValueError):NavigationConfig.load(path)
        app=ApplicationRuntime(self.harness.runtime.profile,profile_name="copter_sim",runtime=self.harness.runtime)
        with self.assertRaisesRegex(ValueError,"not registered"):app.start_mission("follow_path")
        with self.assertRaisesRegex(ValueError,"Rover"):
            ApplicationRuntime(self.harness.runtime.profile,profile_name="copter_sim",runtime=self.harness.runtime,
                               navigation_config=path,mapping_config="unused")


class SoleWriterTests(unittest.TestCase):
    def test_queued_motion_rejected_by_final_guard_but_stop_can_write(self):
        from pymavlink.dialects.v20 import ardupilotmega as mavlink
        from deployment.simulation_runtime import SimulationRuntime
        from runtime.simulation_profile import SimulationProfile
        from vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
        clock, transport = helpers.Clock(),helpers.Transport()
        fault = [None]
        profile=SimulationProfile.load("simulation/profiles/rover.toml")
        runtime=SimulationRuntime(profile,translator=ArduRoverCommandTranslator(mode_ids=profile.mode_ids),
            transport_factory=lambda *a,**k:transport,clock=clock,motion_guard=lambda *args:fault[0])
        self.addCleanup(runtime.shutdown)
        sender=mavlink.MAVLink(None,srcSystem=1,srcComponent=1)
        data=(sender.heartbeat_encode(mavlink.MAV_TYPE_GROUND_ROVER,3,128,15,4).pack(sender)
              +sender.local_position_ned_encode(0,0,0,0,0,0,0).pack(sender)
              +sender.attitude_encode(0,0,0,0,0,0,0).pack(sender))
        runtime.connect();transport.incoming.append(data);clock.advance();runtime.cycle()
        runtime.begin_run(allow_send=True)
        effect=TwistTargetEffect("base_link",Twist3(Vector3(.1,0,0),Vector3(0,0,0)),"stream")
        self.assertIsNone(runtime.submit_effect(effect).reason)
        clock.advance();runtime.cycle();self.assertEqual(len(transport.writes),1)
        runtime.submit_effect(effect)
        fault[0]="navigation_map_unavailable"
        clock.advance();runtime.cycle()
        self.assertEqual(len(transport.writes),1)
        self.assertIsNone(runtime.submit_effect(StopMotionEffect("stream")).reason)
        clock.advance();runtime.cycle()
        self.assertEqual(len(transport.writes),2)

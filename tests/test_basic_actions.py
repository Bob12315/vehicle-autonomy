"""Finite Action feedback and stop barriers, without a vehicle command port."""
from dataclasses import replace
import unittest
from actions.basic import BasicAction, BasicParameters, register_basic
from applications.basic_catalog import build, capabilities
from contracts.core.geometry import Pose3, Vector3
from contracts.core.primitives import ResourceVersion
from contracts.core.stamped import Stamped
from contracts.decision import ActionOutcome, EffectPhase, EffectResult, ExitReason
from contracts.effects.vehicle import PoseTargetEffect, StopMotionEffect
from contracts.vehicle.ports import VehicleCapabilities
from core.action_registry import ActionRegistry
from core.mission import MissionValidator
from environments.resources import Environment
from localization.reported import ReportedPoseLocalization
from tests import test_simulation_runtime as helpers


class BasicActionTests(unittest.TestCase):
    def setUp(self):
        self.harness=helpers.SimulationRuntimeTests()
        self.harness.setUp()
        r=self.harness.runtime
        r.connect()
        self.harness.cycle(self.harness.heartbeat(mode=4,armed=True)+self.harness.state_messages())
        self.environment=Environment.load('simulation/environments/copter.toml').bind(r.world_epoch)
        r.set_environment(self.environment.reference)
        self.harness.cycle(self.harness.state_messages())
        self.world=r.world_snapshot()
        self.params=BasicParameters('copter',self.environment.reference,self.environment.resolve('A'),timeout_ns=30_000_000_000)

    def tearDown(self):
        self.harness.runtime.shutdown()

    def sample(self, seconds, position=None, armed=None):
        old=self.world
        now=replace(old.published_at,monotonic_ns=old.published_at.monotonic_ns+int(seconds*1e9))
        state=old.vehicle
        pose=state.reported_pose
        pose=replace(pose,captured_at=now,value=Pose3(position or pose.value.position,pose.value.orientation))
        state=replace(state,version=ResourceVersion(state.version.generation_id,state.version.revision+1),
            published_at=now,reported_pose=pose,reported_twist=replace(state.reported_twist,captured_at=now),
            operation=replace(state.operation,armed=state.operation.armed if armed is None else armed))
        return replace(old,published_at=now,vehicle=state,localization=ReportedPoseLocalization().estimate(state))

    def result(self, phase, effect_id='effect'):
        return EffectResult(effect_id,'action',phase)

    def test_ack_is_not_takeoff_success_and_deadline_is_finite(self):
        action=BasicAction('takeoff').start(self.params,self.world)
        self.assertEqual(action.tick(self.world).outcome,ActionOutcome.RUNNING)
        ack=(self.result(EffectPhase.ACKNOWLEDGED),)
        self.assertEqual(action.tick_with_results(self.sample(2),ack).outcome,ActionOutcome.RUNNING)
        self.assertEqual(action.tick_with_results(self.sample(3,Vector3(0,0,1.5)),ack).outcome,ActionOutcome.RUNNING)
        self.assertEqual(action.tick_with_results(self.sample(5.1,Vector3(0,0,1.5)),ack).outcome,ActionOutcome.SUCCEEDED)
        other=BasicAction('takeoff').start(self.params,self.world)
        other.tick(self.world)
        self.assertEqual(other.tick_with_results(self.sample(31),ack).outcome,ActionOutcome.FAILED)

    def test_goto_and_cancel_require_observed_stop_barrier(self):
        action=BasicAction('goto').start(self.params,self.world)
        requested=action.tick(self.world)
        self.assertIsInstance(requested.effects[0],PoseTargetEffect)
        tx=(self.result(EffectPhase.TRANSMITTED),)
        stop=action.exit_with_results(self.sample(.2),ExitReason.CANCELLED,tx)
        self.assertFalse(stop.complete)
        self.assertIsInstance(stop.effects[0],StopMotionEffect)
        self.assertFalse(action.exit_with_results(self.sample(.3),ExitReason.CANCELLED,tx).complete)
        completed=tx+(self.result(EffectPhase.COMPLETED,'stop'),)
        self.assertFalse(action.exit_with_results(self.sample(.4),ExitReason.CANCELLED,completed).complete)
        self.assertTrue(action.exit_with_results(self.sample(2.5),ExitReason.CANCELLED,completed).complete)
        bad=BasicAction('goto').start(self.params,self.world)
        bad.tick(self.world)
        bad.exit_with_results(self.sample(.1),ExitReason.CANCELLED,tx)
        with self.assertRaises(RuntimeError):
            bad.exit_with_results(self.sample(.2),ExitReason.CANCELLED,tx+(self.result(EffectPhase.UNKNOWN,'stop'),))

    def test_land_and_disarm_require_observed_post_request_state(self):
        land=BasicAction('land').start(replace(self.params,target=self.environment.home()),self.world)
        land.tick(self.world)
        ack=(self.result(EffectPhase.ACKNOWLEDGED),)
        self.assertEqual(land.tick_with_results(self.sample(.5,Vector3(0,0,1.5)),ack).outcome,ActionOutcome.RUNNING)
        self.assertEqual(land.tick_with_results(self.sample(1,Vector3(0,0,.19),armed=False),ack).outcome,ActionOutcome.RUNNING)
        self.assertEqual(land.tick_with_results(self.sample(3.1,Vector3(0,0,.19),armed=False),ack).outcome,ActionOutcome.SUCCEEDED)
        disarm=BasicAction('disarm').start(self.params,self.world)
        disarm.tick(self.world)
        self.assertEqual(disarm.tick_with_results(self.sample(.2,armed=False),ack).outcome,ActionOutcome.RUNNING)
        self.assertEqual(disarm.tick_with_results(self.sample(.3,armed=False),
            (self.result(EffectPhase.COMPLETED),)).outcome,ActionOutcome.SUCCEEDED)

    def test_environment_loss_rejection_and_missing_localization(self):
        for name in ('arm','disarm','takeoff','land','goto','hold','return_home','stop'):
            with self.subTest(action=name):
                action=BasicAction(name).start(self.params,self.world)
                self.assertEqual(action.tick(replace(self.world,environment=None)).outcome,ActionOutcome.FAILED)
        action=BasicAction('goto').start(self.params,self.world)
        self.assertEqual(action.tick(replace(self.world,localization=None)).outcome,ActionOutcome.FAILED)
        arm=BasicAction('arm').start(self.params,self.sample(0,armed=False))
        arm.tick(self.sample(0,armed=False))
        self.assertEqual(arm.tick_with_results(self.sample(.1,armed=False),
            (self.result(EffectPhase.REJECTED),)).outcome,ActionOutcome.FAILED)

    def test_rover_navigation_has_bounded_body_feedback_and_stopping_margin(self):
        from contracts.effects.vehicle import TwistTargetEffect
        parameters=replace(self.params,vehicle_kind='rover')
        world=replace(self.world,vehicle=replace(self.world.vehicle,
            operation=replace(self.world.vehicle.operation,native_mode='ARDUPILOT_CUSTOM_15')))
        action=BasicAction('goto').start(parameters,world)
        # Point A is ahead-left: finite heading alignment, never sideways drive.
        decision=action.tick(world)
        self.assertIsInstance(decision.effects[0],TwistTargetEffect)
        twist=decision.effects[0].target_twist
        self.assertEqual((twist.linear.y,twist.linear.z),(0,0))
        self.assertLessEqual(abs(twist.angular.z),.35)
        self.assertFalse(action.exit_with_results(world,ExitReason.CANCELLED,()).complete)

    def test_vehicle_capabilities_and_declared_effect_allowlists(self):
        registry=ActionRegistry()
        register_basic(registry)
        from core.sitl_mode_action import SITL_MODE_SPEC,SitlModeAction
        registry.register_typed(SITL_MODE_SPEC,SitlModeAction())
        plan=build('action_probe','copter',self.environment,4)
        MissionValidator(registry).compile(plan,VehicleCapabilities(capabilities('copter')))
        with self.assertRaises(ValueError):
            MissionValidator(registry).compile(plan,VehicleCapabilities(capabilities('rover')))
        for name in ('takeoff','land'):
            with self.assertRaises(ValueError):
                BasicAction(name).start(replace(self.params,vehicle_kind='rover'),self.world)

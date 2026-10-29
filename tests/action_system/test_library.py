"""Standard Action machine metadata and independent physical predicates."""
from dataclasses import replace
import unittest

from vehicle_autonomy.actions.catalog import register_standard,capabilities
from vehicle_autonomy.actions.common.standard import NativeGoal
from vehicle_autonomy.contracts.action import ActionContext,ActionKind
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.core.geometry import Pose3,Quaternion,Vector3,Twist3
from vehicle_autonomy.contracts.decision import ActionOutcome,EffectPhase,EffectResult,ExitReason
from vehicle_autonomy.contracts.effects.vehicle import ModeEffect,TwistTargetEffect,StopMotionEffect
from vehicle_autonomy.engine.action.registry import ActionRegistry
from tests import test_basic_actions as basic_tests


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=basic_tests.BasicActionTests();self.fixture.setUp();self.world=self.fixture.world
        self.registry=ActionRegistry();register_standard(self.registry)
    def tearDown(self):self.fixture.tearDown()
    def context(self,kind):
        return ActionContext(kind,kind,capabilities(kind),True,Pose3(Vector3(0,0,0),Quaternion(0,0,0,1)),
            {'mode_ids':{'GUIDED':15 if kind=='rover' else 4,'TAKEOFF':13,'AUTOLAND':26,'RTL':11,'LOITER':12}})
    def instance(self,name,kind,parameters=None):
        return self.registry.resolve_typed(name).factory.start_with_context(
            self.registry.parameters(name,parameters or {},vehicle_kind=kind),self.world,self.context(kind))
    def test_complete_catalog_filters_schema_caps_and_plane_constraints(self):
        expected={'rover':{'GetVehicleState','SetMode','Arm','Disarm','Drive','Turn','Goto','Stop','ReturnHome','RTL'},
            'copter':{'GetVehicleState','SetMode','Arm','Disarm','Takeoff','Goto','SetVelocity','SetYaw','Hold','ReturnHome','RTL','Land'},
            'plane':{'GetVehicleState','SetMode','Arm','Disarm','Takeoff','SetGuidedTarget','Loiter','RTL','AutoLand'}}
        for kind,names in expected.items():
            catalog=self.registry.catalog(vehicle_kind=kind,capabilities=capabilities(kind))
            self.assertEqual({s['name'] for s in catalog},names)
            for spec in catalog:self.assertTrue(spec['implementation']);self.assertTrue(spec['success_semantics'])
        self.assertEqual(self.registry.parameters('Takeoff',{},vehicle_kind='plane').height_m,50)
        for kind,p in [('plane',{'height_m':1.5}),('copter',{'height_m':50})]:
            with self.assertRaises(ValueError):self.registry.parameters('Takeoff',p,vehicle_kind=kind)
        self.assertEqual(self.registry.parameters('Goto',{'x_m':1,'y_m':0},vehicle_kind='rover').z_m,0)
        self.assertIn('world',self.registry.metadata('GetVehicleState')['output']['required'])
        self.assertIs(self.registry.metadata('SetMode')['output']['properties']['physical_arrival_claim']['const'],False)
        self.assertEqual(self.registry.metadata('Drive')['output'],{'type':'null'})
    def test_plane_command_adoption_is_not_takeoff_or_landing_success(self):
        goal=NativeGoal('TAKEOFF',13,lambda w:w.vehicle.reported_pose.value.position.z>=45)
        self.assertEqual(goal.tick(self.world).effects,(ModeEffect('TAKEOFF'),))
        completed=(EffectResult('e','a',EffectPhase.COMPLETED),)
        for seconds in (1,2,5):self.assertEqual(goal.tick_with_results(self.fixture.sample(seconds),completed).outcome,ActionOutcome.RUNNING)
        high=self.fixture.sample(6,Vector3(0,0,50));self.assertEqual(goal.tick_with_results(high,completed).outcome,ActionOutcome.RUNNING)
        self.assertEqual(goal.tick_with_results(self.fixture.sample(8.1,Vector3(0,0,50)),completed).outcome,ActionOutcome.SUCCEEDED)
        # Native cancellation emits no zero velocity / hover / forced Disarm.
        self.assertEqual(goal.exit(high,ExitReason.CANCELLED).effects,())
    def test_continuous_rover_reverse_and_turn_are_typed_and_bounded(self):
        world=replace(self.world,vehicle=replace(self.world.vehicle,operation=replace(self.world.vehicle.operation,native_mode='ARDUPILOT_CUSTOM_15')))
        self.world=world
        for name,p,speed in [('Drive',{'speed_mps':-.3},-.3),('Turn',{'yaw_rate_rad_s':.15},0)]:
            instance=self.instance(name,'rover',p);decision=instance.tick(world)
            effect=decision.effects[0];self.assertIsInstance(effect,TwistTargetEffect)
            self.assertEqual(effect.frame_id,'base_link');self.assertEqual(effect.target_twist.linear,Vector3(speed,0,0))
            self.assertEqual(decision.outcome,ActionOutcome.RUNNING)
    def test_copter_velocity_exposes_both_audited_enu_and_flu_frames(self):
        for frame in ('odom','base_link'):
            instance=self.instance('SetVelocity','copter',{'vx_mps':.5,'frame':frame})
            effect=instance.tick(self.world).effects[0]
            self.assertEqual(effect.frame_id,frame);self.assertEqual(effect.target_twist.linear,Vector3(.5,0,0))
        with self.assertRaises(ValueError):self.registry.parameters('SetVelocity',{'frame':'map'},vehicle_kind='copter')
    def test_arm_preconditions_and_plane_airborne_disarm_rejected(self):
        with self.assertRaises(ValueError):self.instance('Arm','copter')
        self.world=self.fixture.sample(1,Vector3(0,0,50))
        with self.assertRaises(ValueError):self.instance('Disarm','plane')
        with self.assertRaises(ValueError):self.instance('SetMode','plane',{'mode':'TAKEOFF'})
        with self.assertRaises(ValueError):self.instance('SetMode','copter',{'mode':'BOGUS'})
    def test_land_waits_for_actual_ground_and_disarm(self):
        instance=self.instance('Land','copter');instance.tick(self.world)
        ack=(EffectResult('land','a',EffectPhase.ACKNOWLEDGED),)
        for seconds in (1,3):self.assertEqual(instance.tick_with_results(self.fixture.sample(seconds,Vector3(0,0,1.5)),ack).outcome,ActionOutcome.RUNNING)
        instance.tick_with_results(self.fixture.sample(5,Vector3(0,0,.1),armed=False),ack)
        self.assertEqual(instance.tick_with_results(self.fixture.sample(7.1,Vector3(0,0,.1),armed=False),ack).outcome,ActionOutcome.SUCCEEDED)

    def test_rover_return_home_leaves_room_for_post_goal_hold_stop(self):
        instance=self.instance('ReturnHome','rover');instance.tick(self.world)
        completed=(EffectResult('rtl','a',EffectPhase.COMPLETED),)
        for second in (1,4):
            self.assertEqual(instance.tick_with_results(self.fixture.sample(second,Vector3(.7,0,0)),completed).outcome,ActionOutcome.RUNNING)
        braking=instance.tick_with_results(self.fixture.sample(5,Vector3(.4,0,0)),completed)
        self.assertEqual(braking.effects,(ModeEffect('HOLD'),))
        held=completed+(EffectResult('hold','a',EffectPhase.COMPLETED),)
        instance.tick_with_results(self.fixture.sample(6,Vector3(.8,0,0)),held)
        self.assertEqual(instance.tick_with_results(self.fixture.sample(9,Vector3(.8,0,0)),held).outcome,ActionOutcome.RUNNING)
        instance.tick_with_results(self.fixture.sample(10,Vector3(.4,0,0)),held)
        self.assertEqual(instance.tick_with_results(self.fixture.sample(12.1,Vector3(.4,0,0)),held).outcome,ActionOutcome.SUCCEEDED)

    def test_plane_ground_navigation_rejected_before_effect_creation(self):
        for mode in ('GUIDED','LOITER','RTL'):
            with self.assertRaisesRegex(ValueError,'地面'):
                self.instance('SetMode','plane',dict(mode=mode))

    def test_stop_in_hold_requests_braking_without_guided_and_waits_for_fresh_stop(self):
        instance=self.instance('Stop','rover')
        self.assertEqual(instance.tick(self.world).effects,(ModeEffect('HOLD'),))
        completed=(EffectResult('hold','a',EffectPhase.COMPLETED),)
        self.assertEqual(instance.tick_with_results(self.world,completed).outcome,ActionOutcome.RUNNING)
        instance.tick_with_results(self.fixture.sample(1),completed)
        decision=instance.tick_with_results(self.fixture.sample(3.1),completed)
        self.assertEqual(decision.outcome,ActionOutcome.SUCCEEDED)
        self.assertEqual(to_json_value(decision.result),{'physical_goal_observed':True})

    def rover_goto_exit(self):
        self.world=replace(self.world,vehicle=replace(self.world.vehicle,
            operation=replace(self.world.vehicle.operation,native_mode='ARDUPILOT_CUSTOM_15')))
        instance=self.instance('Goto','rover',dict(x_m=2,y_m=0,z_m=0))
        for _ in range(3):
            if instance.tick(self.world).effects:break
        tx=(EffectResult('move','a',EffectPhase.TRANSMITTED),)
        decision=instance.exit_with_results(self.fixture.sample(.1),ExitReason.CANCELLED,tx)
        self.assertIsInstance(decision.effects[0],StopMotionEffect)
        self.assertEqual(decision.effects[1],ModeEffect('HOLD'))
        return instance,tx

    def test_rover_goto_hold_confirmation_cannot_replace_the_stop_barrier(self):
        instance,tx=self.rover_goto_exit()
        complete=tx+(EffectResult('stop','a',EffectPhase.COMPLETED),EffectResult('hold','a',EffectPhase.COMPLETED))
        unknown_stop=tx+(EffectResult('stop','a',EffectPhase.UNKNOWN),complete[-1])
        with self.assertRaisesRegex(RuntimeError,'stop_exit_unconfirmed'):
            instance.exit_with_results(self.fixture.sample(.2),ExitReason.CANCELLED,unknown_stop)
        instance,tx=self.rover_goto_exit()
        unknown_hold=tx+(EffectResult('stop','a',EffectPhase.COMPLETED),EffectResult('hold','a',EffectPhase.UNKNOWN))
        with self.assertRaisesRegex(RuntimeError,'hold_unconfirmed'):
            instance.exit_with_results(self.fixture.sample(.2),ExitReason.CANCELLED,unknown_hold)

    def test_rover_goto_still_requires_physical_settling_and_copter_has_no_hold(self):
        instance,tx=self.rover_goto_exit()
        complete=tx+(EffectResult('stop','a',EffectPhase.COMPLETED),EffectResult('hold','a',EffectPhase.COMPLETED))
        sample=self.fixture.sample(1)
        turning=replace(sample,localization=replace(sample.localization,
            twist=replace(sample.localization.twist,value=Twist3(Vector3(0,0,0),Vector3(0,0,.25)))))
        self.assertFalse(instance.exit_with_results(turning,ExitReason.CANCELLED,complete).complete)
        self.assertFalse(instance.exit_with_results(self.fixture.sample(2),ExitReason.CANCELLED,complete[:-1]).complete)
        # A completed mode result alone cannot replace its observed state.
        guided=self.fixture.sample(4.1)
        guided=replace(guided,vehicle=replace(guided.vehicle,
            operation=replace(guided.vehicle.operation,native_mode='ARDUPILOT_CUSTOM_15')))
        self.assertFalse(instance.exit_with_results(guided,ExitReason.CANCELLED,complete).complete)
        held=replace(self.fixture.sample(4.2),vehicle=replace(self.fixture.sample(4.2).vehicle,
            operation=replace(self.world.vehicle.operation,native_mode='ARDUPILOT_CUSTOM_4')))
        self.assertTrue(instance.exit_with_results(held,ExitReason.CANCELLED,complete).complete)
        self.world=replace(self.fixture.world,vehicle=replace(self.fixture.world.vehicle,
            operation=replace(self.fixture.world.vehicle.operation,native_mode='ARDUPILOT_CUSTOM_4')))
        copter=self.instance('Goto','copter',dict(x_m=2,y_m=0,z_m=1.5));copter.tick(self.world)
        effects=copter.exit_with_results(self.fixture.sample(.1),ExitReason.CANCELLED,tx).effects
        self.assertEqual(len(effects),1);self.assertIsInstance(effects[0],StopMotionEffect)


if __name__=='__main__':unittest.main()

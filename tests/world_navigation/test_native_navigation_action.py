from dataclasses import replace
from types import SimpleNamespace
import unittest
from vehicle_autonomy.actions.navigation.native_rover import NativeRoverNavigation,NavigateParameters
from vehicle_autonomy.contracts.action import ActionContext
from vehicle_autonomy.contracts.core.serialization import to_json_value
from vehicle_autonomy.contracts.decision import ActionOutcome
from vehicle_autonomy.engine.navigation.mailbox import NavigationBinding,NavigationCommand
from vehicle_autonomy.engine.navigation.write_fence import NativeNavigationWriteFence
from tests.world_navigation import test_navigation_inputs as inputs_tests

class NativeNavigationActionTests(unittest.TestCase):
    def setUp(self):
        self.f=inputs_tests.NavigationInputTests();self.f.setUp();self.now=self.f.now
        self.ctx=ActionContext('rover','rover',frozenset(),True,action_id='actual-action',vehicle_session=self.f.guard.vehicle_session,world_generation=self.f.guard.world_generation)
        self.value={'state':'RUNNING','feedback':{'phase':'ACTIVE'}}
        self.job=SimpleNamespace(poll=lambda:self.value,cancel=lambda:None,close=lambda:None)
        self.goal=dict(action_id='actual-action',target_id='rover',provider_id='physical-native',provider_epoch='actual-epoch',vehicle_session=self.ctx.vehicle_session,world_generation=self.ctx.world_generation,goal_id='1'*32)
        self.binding=NavigationBinding(**self.goal,producer_gid='a'*32,clock_domain=self.now.clock_domain_id)
        self.fence=NativeNavigationWriteFence();self.fence.admit(self.ctx.action_id,self.f.guard)
        self.instance=NativeRoverNavigation(NavigateParameters(1,0,'map-epoch'),self.f.world,self.ctx,self.job,self.f.guard,self.goal,self.now,lambda:self.now,lambda *_:self.f.world.vehicle.reported_pose.value,self.fence)
    def tearDown(self):self.f.tearDown()
    def sample(self,offset):
        self.now=replace(self.f.now,monotonic_ns=self.f.now.monotonic_ns+offset)
        w=self.f.f.sample(offset/1e9);w=replace(w,vehicle=replace(w.vehicle,operation=replace(w.vehicle.operation,native_mode='ARDUPILOT_CUSTOM_15')))
        return replace(w,streams=tuple(replace(s,header=replace(s.header,captured_at=self.now,received_at=self.now,sequence=s.header.sequence+1)) for s in self.f.world.streams))
    def command(self,sequence,offset,speed):
        t=replace(self.f.now,monotonic_ns=self.f.now.monotonic_ns+offset)
        self.value['feedback']['command']=to_json_value(NavigationCommand(self.binding,sequence,offset,t,t,speed,0.))
    def test_only_new_original_input_emits_and_expiry_never_renews(self):
        w=self.sample(40_000_000);self.command(1,30_000_000,0.)
        d=self.instance.tick(w);self.assertEqual(len(d.effects),1);self.assertEqual(d.valid_until.monotonic_ns,self.f.now.monotonic_ns+230_000_000)
        self.assertEqual(self.instance.tick(w).effects,())
        w=self.sample(120_000_000);self.command(2,100_000_000,.015)
        d=self.instance.tick(w);self.assertEqual(len(d.effects),1);self.assertEqual(d.effects[0].target_twist.linear.x,.015)
        d=self.instance.tick(self.sample(340_000_000));self.assertEqual(d.outcome,ActionOutcome.FAILED);self.assertEqual(d.effects,())
    def test_actual_write_fence_uses_current_vehicle_state_and_closes(self):
        from vehicle_autonomy.contracts.core.geometry import Twist3,Vector3
        command=SimpleNamespace(run_id='actual-action');w=self.sample(50_000_000)
        self.assertIsNone(self.fence.validate(command,w.vehicle,self.now,w))
        v=w.vehicle;bad=replace(v,reported_twist=replace(v.reported_twist,value=Twist3(Vector3(.5,0,0),Vector3(0,0,0))))
        self.assertEqual(self.fence.validate(command,bad,self.now,w),'native_navigation_current_evidence_invalid')
        self.fence.close('actual-action');self.assertEqual(self.fence.validate(command,v,self.now,w),'native_navigation_source_closed')
        self.assertIsNone(self.fence.validate(SimpleNamespace(run_id='other-existing-action'),v,self.now,w))

    def test_initial_data_outage_waits_without_write_but_active_stream_loss_fails(self):
        self.now=replace(self.f.now,monotonic_ns=self.f.now.monotonic_ns+250_000_000)
        before=self.instance.tick(self.f.world)
        self.assertEqual(before.outcome,ActionOutcome.RUNNING);self.assertEqual(before.effects,())
        self.assertFalse(self.instance.stream.touched)
        w=self.sample(40_000_000);self.command(1,30_000_000,0.)
        self.assertEqual(len(self.instance.tick(w).effects),1)
        self.now=replace(self.f.now,monotonic_ns=self.f.now.monotonic_ns+300_000_000)
        after=self.instance.tick(w)
        self.assertEqual(after.outcome,ActionOutcome.FAILED);self.assertEqual(after.effects,())

    def test_pre_dispatch_wait_is_one_action_without_retrying_any_job(self):
        from vehicle_autonomy.actions.navigation.native_rover import NativeNavigationPreparation
        from vehicle_autonomy.engine.navigation.inputs import NavigationEvidenceUnavailable
        calls=[]
        def pending(*args):calls.append('data-check');raise NavigationEvidenceUnavailable('scan not fresh')
        preparation=NativeNavigationPreparation(SimpleNamespace(create_ready=pending),None,None)
        for _ in range(3):
            decision=preparation.tick_with_results(self.f.world,())
            self.assertEqual(decision.effects,());self.assertEqual(decision.outcome,ActionOutcome.RUNNING)
        self.assertEqual(len(calls),3);self.assertIsNone(preparation.delegate)
        self.assertTrue(preparation.exit_with_results(self.f.world,None,()).complete)

    def test_nearly_expired_evidence_produces_no_effect_then_new_cut_works(self):
        w=self.sample(100_000_000);old=replace(self.f.now,monotonic_ns=self.f.now.monotonic_ns-75_000_000)
        w=replace(w,vehicle=replace(w.vehicle,reported_pose=replace(w.vehicle.reported_pose,captured_at=old),reported_twist=replace(w.vehicle.reported_twist,captured_at=old)))
        self.command(1,90_000_000,0.)
        decision=self.instance.tick(w)
        self.assertEqual(decision.outcome,ActionOutcome.RUNNING);self.assertEqual(decision.effects,());self.assertFalse(self.instance.stream.touched)
        w=self.sample(150_000_000);self.command(2,140_000_000,0.)
        decision=self.instance.tick(w)
        self.assertEqual(len(decision.effects),1);self.assertLessEqual(decision.valid_until.monotonic_ns,self.f.now.monotonic_ns+340_000_000)

    def test_expired_preparation_sample_is_discarded_without_a_vehicle_effect(self):
        w=self.sample(250_000_000);self.command(1,30_000_000,0.)
        decision=self.instance.tick(w)
        self.assertEqual(decision.outcome,ActionOutcome.RUNNING);self.assertEqual(decision.effects,());self.assertFalse(self.instance.stream.touched)
        w=self.sample(300_000_000);self.command(2,290_000_000,.01)
        decision=self.instance.tick(w)
        self.assertEqual(decision.outcome,ActionOutcome.RUNNING);self.assertEqual(len(decision.effects),1)

    def test_native_success_without_independent_goal_proof_is_failed(self):
        self.value={'state':'SUCCEEDED','result':{'native_result':{'state':'SUCCEEDED'}}}
        decision=self.instance.tick(self.sample(40_000_000))
        self.assertEqual(decision.outcome,ActionOutcome.FAILED)
        self.assertIn('independent fresh World goal proof',decision.error)
        self.assertEqual(decision.effects,())
    def test_native_and_independent_goal_proof_can_succeed_without_extra_motion(self):
        from vehicle_autonomy.contracts.core.geometry import Pose3,Vector3,Quaternion
        self.value={'state':'SUCCEEDED','result':{'native_result':{'state':'SUCCEEDED'}}}
        self.instance.pose_reader=lambda *_:Pose3(Vector3(1,0,0),Quaternion(0,0,0,1))
        decision=self.instance.tick(self.sample(40_000_000))
        self.assertEqual(decision.outcome,ActionOutcome.SUCCEEDED)
        self.assertEqual(decision.result['distance_m'],0.)
        self.assertEqual(decision.effects,())

    def test_controller_preparation_and_unknown_phase_never_emit_vehicle_effects(self):
        for phase in ('CONTROLLER_PREPARE','UNRECOGNIZED_PHASE'):
            self.value['feedback']['phase']=phase
            offset=40_000_000 if phase=='CONTROLLER_PREPARE' else 80_000_000
            w=self.sample(offset);self.command(offset,offset-10_000_000,0.)
            decision=self.instance.tick(w)
            self.assertEqual(decision.outcome,ActionOutcome.RUNNING if phase=='CONTROLLER_PREPARE' else ActionOutcome.FAILED)
            self.assertEqual(decision.effects,());self.assertFalse(self.instance.stream.touched)

    def test_preparation_cannot_keep_an_already_moving_stream_alive(self):
        w=self.sample(40_000_000);self.command(1,30_000_000,.005)
        self.assertEqual(len(self.instance.tick(w).effects),1)
        self.value['feedback']['phase']='CONTROLLER_PREPARE'
        w=self.sample(80_000_000);self.command(2,70_000_000,.005)
        decision=self.instance.tick(w)
        self.assertEqual(decision.outcome,ActionOutcome.FAILED)
        self.assertEqual(decision.effects,())

    def test_closure_serializes_with_the_existing_writer_authority(self):
        from threading import Thread,Event
        from vehicle_autonomy.engine.control.control_authority import ControlAuthority
        authority=ControlAuthority();fence=NativeNavigationWriteFence();fence.bind_authority(authority)
        with self.assertRaises(ValueError):fence.bind_authority(ControlAuthority())
        fence.admit('actual-action',self.f.guard);entered=Event();closed=Event()
        def close():entered.set();fence.close('actual-action');closed.set()
        with authority.lock:
            worker=Thread(target=close);worker.start();self.assertTrue(entered.wait(1))
            self.assertFalse(closed.wait(.02),'source closure bypassed the Writer critical section')
        self.assertTrue(closed.wait(1));worker.join(1)
        w=self.sample(50_000_000)
        self.assertEqual(fence.validate(SimpleNamespace(run_id='actual-action'),w.vehicle,self.now,w),'native_navigation_source_closed')
        self.assertIsNone(authority.lease);self.assertFalse(authority.system_send);self.assertFalse(authority.action_send)

    def test_closed_native_scope_rejects_actual_transport_writes(self):
        from tests import test_p5_mavlink as wire
        from vehicle_autonomy.contracts.effects.vehicle import TwistTargetEffect
        from vehicle_autonomy.contracts.core.geometry import Twist3,Vector3
        f=wire.P5MavlinkTests();f.setUp();f.connect()
        fence=NativeNavigationWriteFence();fence.bind_authority(f.authority)
        f.port._write_guard=lambda command:fence.validate(command,None,wire.at(f.now_ns),None)
        target=TwistTargetEffect('base_link',Twist3(Vector3(.01,0,0),Vector3(0,0,0)),'native-motion')
        # Existing unbound control still really sends one frame.
        f.now_ns=101
        first=f.execution.dispatch(wire.effect(1,target),wire.world(),wire.at(101)).receipt
        f.write(102);self.assertEqual(len(f.transport.attempts),1)
        fence.admit('run',self.f.guard);fence.close('run')
        f.now_ns=103
        rejected=f.execution.dispatch(wire.effect(2,target),wire.world(),wire.at(103)).receipt
        f.write(104)
        self.assertEqual(f.port.status(rejected.command_id).phase.value,'REJECTED')
        self.assertEqual(f.port.reasons[rejected.command_id],'native_navigation_source_closed')
        self.assertEqual(len(f.transport.attempts),1);self.assertEqual(len(f.transport.writes),1)

    def test_native_registration_preserves_rover_cleanup_and_control_conflict(self):
        from vehicle_autonomy.engine.action.registry import ActionRegistry
        from vehicle_autonomy.engine.action.resources import ActionResources
        from vehicle_autonomy.actions.catalog import register_standard
        from vehicle_autonomy.actions.navigation.native_rover import register_native_navigation
        registry=ActionRegistry();register_standard(registry)
        register_native_navigation(registry,SimpleNamespace(start=lambda *args:None))
        drive=registry.resolve_typed('Drive').spec;native=registry.resolve_typed('NavigateToPose').spec
        self.assertEqual(to_json_value(native.effect_ttl_overrides)['ModeEffect'],to_json_value(drive.effect_ttl_overrides)['ModeEffect'])
        self.assertEqual(native.effect_ttl_ns,drive.effect_ttl_ns)
        resources=ActionResources()
        self.assertTrue(resources.acquire('native','rover',native.resources))
        self.assertFalse(resources.acquire('manual','rover',drive.resources))
        self.assertTrue(resources.acquire('query','rover',registry.resolve_typed('GetVehicleState').spec.resources))
        resources.release('native',no_effects=True)
        self.assertTrue(resources.acquire('manual','rover',drive.resources))
        self.assertFalse(resources.acquire('new-native','rover',native.resources))

    def test_an_initial_zero_does_not_waive_the_first_physical_motion_ramp(self):
        w=self.sample(40_000_000);self.command(1,30_000_000,0.)
        self.assertEqual(len(self.instance.tick(w).effects),1)
        self.assertFalse(self.instance.moving)
        w=self.sample(400_000_000);self.command(2,390_000_000,.09)
        decision=self.instance.tick(w)
        self.assertEqual(decision.outcome,ActionOutcome.FAILED)
        self.assertEqual(decision.effects,())

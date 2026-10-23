"""Fixed-wing contracts use the existing fenced writer and signed evidence."""
from dataclasses import replace
from pathlib import Path
import unittest
from pymavlink.dialects.v20 import ardupilotmega as mav
from vehicle_autonomy.app.bootstrap.simulation_profile import SimulationProfile
from vehicle_autonomy.app.bootstrap.simulation_runtime import SimulationRuntime
from vehicle_autonomy.contracts.core.geometry import GeoPoint, Pose3, Quaternion, Twist3, Vector3
from vehicle_autonomy.contracts.effects.vehicle import (ArmEffect, DisarmEffect, ModeEffect,
    FixedWingTargetEffect, TakeoffEffect, LandEffect, TwistTargetEffect, PoseTargetEffect, StopMotionEffect)
from vehicle_autonomy.contracts.vehicle.command import TakeoffCommand, LandCommand, StopMotionCommand
from vehicle_autonomy.vehicles.plane.ardupilot_commands import ArduPlaneCommandTranslator, PLANE_MODES
from tests.mavlink_fixture import pack, heartbeat_evidence, receive_signing
from tests.test_simulation_runtime import Clock, Transport

ROOT=Path(__file__).resolve().parents[1]


class PlaneControlTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.transport=Transport();self.sender=mav.MAVLink(None,srcSystem=1,srcComponent=1)
        self.profile=SimulationProfile.load(ROOT/'simulation/profiles/plane.toml')
        self.translator=ArduPlaneCommandTranslator(mode_ids=self.profile.mode_ids)
        self.runtime=SimulationRuntime(self.profile,translator=self.translator,clock=self.clock,
            transport_factory=lambda *a,**k:self.transport,receive_signing=receive_signing())
        self.runtime.connect();self.origin_sent=False

    def tearDown(self):
        # Tests observe shutdown separately; never sleep for real 5 s on a fake clock.
        self.runtime._close_link('test_end');self.runtime.shutdown()

    def feed(self,*,mode=0,armed=False,height=0,speed=0,ack=None,prefix=b''):
        self.clock.advance();boot=self.clock.ns//1_000_000
        raw=prefix
        if ack is not None:raw+=pack(self.sender.command_ack_encode(ack,0,target_system=250,target_component=191),self.sender)
        raw+=heartbeat_evidence(self.sender,self.profile.mav_type,mode,armed,boot)
        if not self.origin_sent:
            raw+=pack(self.sender.gps_global_origin_encode(-353632620,1491652370,584000),self.sender)
            self.origin_sent=True
        raw+=pack(self.sender.global_position_int_encode(boot+3,-353632620,1491652370,
            int(584000+height*1000),int(height*1000),int(speed*100),0,0,0),self.sender)
        raw+=pack(self.sender.gps_raw_int_encode((boot+3)*1000,3,-353632620,1491652370,
            int(584000+height*1000),10,10,int(speed*100),0,12),self.sender)
        self.transport.incoming.append(raw)
        result=self.runtime.cycle();self.assertIsNone(result.fault)
        return raw

    def begin(self,**kwargs):
        self.feed(**kwargs);self.runtime.begin_run(allow_send=True)

    def test_plane_profile_is_distinct_and_mode_map_is_pinned(self):
        self.assertEqual(self.profile.mav_type,1)
        self.assertEqual(self.profile.mode_ids,PLANE_MODES)
        with self.assertRaises(ValueError):ArduPlaneCommandTranslator(mode_ids={'GUIDED':4})
        for command in (TakeoffCommand(50),LandCommand(),StopMotionCommand('s')):
            with self.assertRaises(ValueError):self.translator.translate(command)

    def test_default_send_and_action_send_write_nothing(self):
        self.feed();self.runtime.begin_run()
        self.assertEqual(self.runtime.submit_effect(ArmEffect(),effect_id='off').reason,'system_send_disabled')
        self.runtime.end_run();self.runtime.begin_run(allow_send=True);self.runtime.authority.set_action_send(False)
        self.assertEqual(self.runtime.submit_effect(ArmEffect(),effect_id='action-off').reason,'action_send_disabled')
        self.assertEqual(self.transport.writes,[])

    def test_normal_continuous_arm_disarm_has_actual_frames_and_signed_completion(self):
        self.begin()
        for index,armed in enumerate((True,False,True,False)):
            name=f'normal-{index}'
            result=self.runtime.submit_effect(ArmEffect() if armed else DisarmEffect(),effect_id=name)
            self.assertIsNone(result.reason);self.feed(armed=not armed)
            self.assertEqual(len(self.transport.writes),index+1)
            decoded=mav.MAVLink(None).parse_buffer(self.transport.writes[-1])[0]
            self.assertEqual(decoded.command,400);self.assertEqual(decoded.param1,int(armed))
            self.feed(armed=armed,ack=400)
            self.assertEqual(self.runtime.effect_status(name)['phase'],'COMPLETED')
            self.assertEqual(self.runtime.world_snapshot().vehicle.operation.armed,armed)

    def test_airborne_disarm_and_manual_are_rejected_without_writes(self):
        self.begin(mode=12,armed=True,height=50,speed=17)
        for name,effect in [('disarm',DisarmEffect()),('manual',ModeEffect('MANUAL')),('arm',ArmEffect())]:
            self.assertIsNotNone(self.runtime.submit_effect(effect,effect_id=name).reason)
        self.assertEqual(self.transport.writes,[])

    def test_hover_takeoff_land_velocity_and_pose_contracts_are_rejected(self):
        self.begin(mode=15,armed=True,height=50,speed=17)
        effects=(TakeoffEffect(1),LandEffect(),TwistTargetEffect('base_link',Twist3(Vector3(0,0,0),Vector3(0,0,0)),'x'),
                 PoseTargetEffect('odom',Pose3(Vector3(0,0,50),Quaternion(0,0,0,1)),'x'),StopMotionEffect('x'))
        for i,effect in enumerate(effects):
            self.assertIsNotNone(self.runtime.submit_effect(effect,effect_id=f'bad-{i}').reason)
        self.assertEqual(self.transport.writes,[])

    def test_native_mode_completion_means_mode_only(self):
        self.begin(armed=True)
        self.assertIsNone(self.runtime.submit_effect(ModeEffect('TAKEOFF'),effect_id='takeoff').reason)
        self.feed(armed=True)
        self.feed(armed=True,mode=13,ack=176)
        self.assertEqual(self.runtime.effect_status('takeoff')['phase'],'COMPLETED')
        self.assertEqual(self.runtime.world_snapshot().vehicle.reported_pose.value.position.z,0)
        self.assertEqual(len(self.transport.writes),1)  # no implicit throttle/VTOL command

    def test_mode_state_changed_while_queued_is_rechecked_before_write(self):
        self.begin(mode=12,armed=True,height=50,speed=17)
        self.assertIsNone(self.runtime.submit_effect(ModeEffect('AUTOLAND'),effect_id='land').reason)
        self.feed(mode=0,armed=False,height=0,speed=0)
        self.assertEqual(self.runtime.effect_status('land')['phase'],'REJECTED')
        self.assertEqual(self.transport.writes,[])

    def test_expired_lease_at_writer_writes_zero(self):
        self.begin(armed=True)
        from vehicle_autonomy.app.bootstrap.simulation_runtime import _later
        self.runtime.authority.grant(replace(self.runtime.authority.lease,expires_at=_later(self.clock(),50_000_000)),self.clock())
        self.runtime.authority.set_action_send(True)
        self.assertIsNone(self.runtime.submit_effect(ModeEffect('TAKEOFF'),effect_id='late').reason)
        self.feed(armed=True)
        self.assertEqual(self.runtime.effect_status('late')['phase'],'REJECTED')
        self.assertEqual(self.transport.writes,[])

    def test_old_signed_arm_ack_heartbeat_replay_cannot_complete_disarm(self):
        old=self.feed();self.runtime.begin_run(allow_send=True)
        self.runtime.submit_effect(ArmEffect(),effect_id='arm');self.feed()
        old_ack=pack(self.sender.command_ack_encode(400,0,target_system=250,target_component=191),self.sender)
        self.transport.incoming.append(old_ack);self.feed(armed=True)
        self.feed(armed=True)
        self.assertEqual(self.runtime.effect_status('arm')['phase'],'COMPLETED')
        self.runtime.submit_effect(DisarmEffect(),effect_id='disarm');self.feed(armed=True)
        writes=len(self.transport.writes)
        old_hb=b''.join(bytes(m.get_msgbuf()) for m in mav.MAVLink(None).parse_buffer(old) if m.get_type()=='HEARTBEAT')
        for _ in range(3):
            self.clock.advance()
            boot=self.clock.ns//1_000_000
            raw=b''.join(pack(self.sender.sys_status_encode(0,0,0,0,12000,0,100,0,0,0,0,0,0),self.sender) for i in range(255))
            raw+=pack(self.sender.attitude_encode(boot,0,0,0,0,0,0),self.sender)
            self.transport.incoming.append(raw+old_ack+old_hb)
            result=self.runtime.cycle();self.assertIsNone(result.fault)
        self.assertNotEqual(self.runtime.effect_status('disarm')['phase'],'COMPLETED')
        self.assertTrue(self.runtime.world_snapshot().vehicle.operation.armed)
        self.assertEqual(len(self.transport.writes),writes)

    def target_echo(self, center, *, unsigned=False):
        sender=mav.MAVLink(None,srcSystem=1,srcComponent=1) if unsigned else self.sender
        message=sender.position_target_global_int_encode(self.clock.ns//1_000_000,0,3576,
            round(center.latitude_deg*1e7),round(center.longitude_deg*1e7),center.altitude_m,
            0,0,0,0,0,0,0,0)
        return message.pack(sender) if unsigned else pack(message,sender)

    def test_native_target_requires_ack_guided_and_matching_new_signed_echo(self):
        self.begin(mode=12,armed=True,height=50,speed=17)
        center=GeoPoint(-35.363262,149.165237,634)
        self.assertIsNone(self.runtime.submit_effect(FixedWingTargetEffect(center),effect_id='target').reason)
        self.feed(mode=12,armed=True,height=50,speed=17)
        self.assertEqual(len(self.transport.writes),1)
        wire=mav.MAVLink(None).parse_buffer(self.transport.writes[0])[0]
        self.assertEqual(wire.get_type(),'COMMAND_INT');self.assertEqual(wire.command,192)
        self.assertEqual((wire.x,wire.y,wire.z),(-353632620,1491652370,634))
        self.feed(mode=15,armed=True,height=50,speed=17,ack=192)
        self.assertEqual(self.runtime.effect_status('target')['phase'],'ACKNOWLEDGED')
        wrong=GeoPoint(-35.363262,149.166237,634)
        self.feed(prefix=self.target_echo(wrong),mode=15,armed=True,height=50,speed=17)
        self.assertEqual(self.runtime.effect_status('target')['phase'],'ACKNOWLEDGED')
        self.feed(prefix=self.target_echo(center,unsigned=True),mode=15,armed=True,height=50,speed=17)
        self.assertEqual(self.runtime.effect_status('target')['phase'],'ACKNOWLEDGED')
        self.feed(prefix=self.target_echo(center),mode=15,armed=True,height=50,speed=17)
        self.assertEqual(self.runtime.effect_status('target')['phase'],'COMPLETED')
        self.assertEqual(len(self.transport.writes),1)

    def test_native_target_without_echo_expires_unknown_despite_fresh_telemetry(self):
        self.begin(mode=12,armed=True,height=50,speed=17)
        self.runtime.submit_effect(FixedWingTargetEffect(GeoPoint(-35.363262,149.165237,634)),effect_id='target')
        self.feed(mode=12,armed=True,height=50,speed=17)
        self.feed(mode=15,armed=True,height=50,speed=17,ack=192)
        for _ in range(55):self.feed(mode=15,armed=True,height=50,speed=17)
        self.assertEqual(self.runtime.effect_status('target')['phase'],'UNKNOWN')
        self.assertEqual(len(self.transport.writes),1)

    def test_native_target_bounded_and_not_available_to_copter(self):
        self.begin(mode=12,armed=True,height=50,speed=17)
        for index,center in enumerate((GeoPoint(0,0,634),GeoPoint(-35.363262,149.165237,590),GeoPoint(-35.363262,149.165237,1000))):
            self.assertIsNotNone(self.runtime.submit_effect(FixedWingTargetEffect(center),effect_id=f'bad-target-{index}').reason)
        self.assertEqual(self.transport.writes,[])
        from tests.test_simulation_runtime import SimulationRuntimeTests
        f=SimulationRuntimeTests();f.setUp();f.runtime.connect()
        f.cycle(f.heartbeat()+f.state_messages());f.runtime.begin_run(allow_send=True)
        result=f.runtime.submit_effect(FixedWingTargetEffect(GeoPoint(-35.363262,149.165237,634)),effect_id='wrong-vehicle')
        self.assertEqual(result.reason,'fixed_wing_target_requires_explicit_plane_policy')
        self.assertEqual(f.transports[-1].writes,[])
        f.runtime.shutdown()

    def test_autonomous_flight_envelope_violation_revokes_authority_and_no_write(self):
        self.begin(mode=12,armed=True,height=50,speed=17)
        self.clock.advance();boot=self.clock.ns//1_000_000
        raw=heartbeat_evidence(self.sender,1,12,True,boot)
        raw+=pack(self.sender.global_position_int_encode(boot+3,-353632620,1491652370,800000,216000,1700,0,0,0),self.sender)
        self.transport.incoming.append(raw)
        result=self.runtime.cycle()
        self.assertEqual(result.fault,'plane_state_outside_envelope')
        self.assertFalse(self.runtime.authority.system_send)
        self.assertIsNone(self.runtime.authority.lease)
        self.assertEqual(self.transport.writes,[])

    def test_lost_native_flight_retains_unconfirmed_shutdown_outcome(self):
        self.begin(mode=12,armed=True,height=50,speed=17)
        self.runtime.submit_effect(ModeEffect('LOITER'),effect_id='flight')
        self.feed(mode=12,armed=True,height=50,speed=17)
        self.feed(mode=12,armed=True,height=50,speed=17,ack=176)
        before=len(self.transport.writes)
        self.runtime._close_link('injected_link_loss')
        self.assertEqual(self.runtime.shutdown(),{'fixed-wing-flight':'UNCONFIRMED'})
        self.assertEqual(len(self.transport.writes),before)

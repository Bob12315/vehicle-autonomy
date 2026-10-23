"""Native Rover return is opt-in and retains the original profile/fences."""
from pathlib import Path
import unittest
from pymavlink.dialects.v20 import ardupilotmega as mav
from vehicle_autonomy.app.bootstrap.simulation_profile import SimulationProfile
from vehicle_autonomy.app.bootstrap.simulation_runtime import SimulationRuntime
from vehicle_autonomy.contracts.effects.vehicle import ModeEffect
from vehicle_autonomy.vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
from tests import test_plane_control as fixture
from tests.mavlink_fixture import receive_signing

ROOT=Path(__file__).resolve().parents[1]


class RoverNativeRtlTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.PlaneControlTests();self.f.setUp();self.f.runtime.shutdown()
        from tests.test_simulation_runtime import Transport
        self.f.transport=Transport()
        self.f.profile=SimulationProfile.load(ROOT/'simulation/profiles/rover_phase2.toml')
        self.f.translator=ArduRoverCommandTranslator(mode_ids=self.f.profile.mode_ids)
        self.f.runtime=SimulationRuntime(self.f.profile,translator=self.f.translator,clock=self.f.clock,
            transport_factory=lambda *a,**k:self.f.transport,receive_signing=receive_signing())
        self.f.runtime.connect()

    def tearDown(self):self.f.tearDown()

    def test_original_rover_profile_retains_all_limits_and_excludes_rtl(self):
        old=SimulationProfile.load(ROOT/'simulation/profiles/rover.toml');new=self.f.profile
        self.assertEqual(old.mode_ids,{'HOLD':4,'GUIDED':15})
        for name in old.safety.__dataclass_fields__:
            if name!='allowed_modes':self.assertEqual(getattr(old.safety,name),getattr(new.safety,name))
        with self.assertRaises(ValueError):ArduRoverCommandTranslator(mode_ids=old.mode_ids).mode_id('RTL')
        self.assertEqual((old.effect_ttl_ns,old.lease_ns),(new.effect_ttl_ns,new.lease_ns))

    def test_native_rtl_uses_the_same_writer_and_signed_ack_state(self):
        f=self.f;f.begin(mode=15,armed=True)
        self.assertIsNone(f.runtime.submit_effect(ModeEffect('RTL'),effect_id='rtl').reason)
        f.feed(mode=15,armed=True)
        self.assertEqual(len(f.transport.writes),1)
        wire=mav.MAVLink(None).parse_buffer(f.transport.writes[0])[0]
        self.assertEqual((wire.command,wire.param2),(176,11))
        f.feed(mode=11,armed=True,ack=176)
        self.assertEqual(f.runtime.effect_status('rtl')['phase'],'COMPLETED')
        self.assertEqual(f.runtime.world_snapshot().vehicle.operation.native_mode,'ARDUPILOT_CUSTOM_11')

    def test_state_invalidated_in_queue_prevents_native_rtl_write(self):
        f=self.f;f.begin(mode=15,armed=True)
        self.assertIsNone(f.runtime.submit_effect(ModeEffect('RTL'),effect_id='rtl').reason)
        f.feed(mode=4,armed=False)
        self.assertEqual(f.runtime.effect_status('rtl')['phase'],'REJECTED')
        self.assertEqual(f.transport.writes,[])

    def test_native_rtl_cancel_requests_hold_then_waits_for_post_confirmation_zero_state(self):
        from tests.mavlink_fixture import pack
        f=self.f;f.begin(mode=15,armed=True,speed=.5)
        f.runtime.submit_effect(ModeEffect('RTL'),effect_id='rtl');f.feed(mode=15,armed=True,speed=.5)
        f.feed(mode=11,armed=True,speed=.5,ack=176)
        original=f.transport.write
        def actuator(data):
            original(data)
            decoded=mav.MAVLink(None).parse_buffer(data)[0]
            self.assertEqual((decoded.command,decoded.param2),(176,4))
            f.transport.incoming.append(pack(f.sender.command_ack_encode(176,0,target_system=250,target_component=191),f.sender))
        f.transport.write=actuator
        f.runtime._sleep=lambda seconds:f.feed(mode=4,armed=True,speed=0)
        stops=f.runtime.end_run()
        self.assertEqual(stops,{'native-rover-rtl':'CONFIRMED'})
        self.assertFalse(f.runtime.authority.system_send)
        self.assertEqual(len(f.transport.writes),2)
        self.assertEqual(f.runtime.world_snapshot().vehicle.operation.native_mode,'ARDUPILOT_CUSTOM_4')

    def test_lost_native_rtl_link_cannot_report_shutdown_stop_confirmed(self):
        f=self.f;f.begin(mode=15,armed=True,speed=.5)
        f.runtime.submit_effect(ModeEffect('RTL'),effect_id='rtl');f.feed(mode=15,armed=True,speed=.5)
        f.feed(mode=11,armed=True,speed=.5,ack=176)
        before=len(f.transport.writes);f.runtime._close_link('injected_link_loss')
        self.assertEqual(f.runtime.shutdown(),{'native-rover-rtl':'UNCONFIRMED'})
        self.assertEqual(len(f.transport.writes),before)

"""Monitor isolation and non-default simulated vehicle identity fences."""
import socket
import unittest
from pymavlink.dialects.v20 import ardupilotmega as mav
from tests.test_simulation_runtime import Transport, Clock, PROFILE
from vehicle_autonomy.app.bootstrap.simulation_profile import SimulationProfile
from vehicle_autonomy.app.bootstrap.simulation_runtime import SimulationRuntime
from vehicle_autonomy.vehicles.ardupilot.commands import ArduPilotCommandTranslator
from vehicle_autonomy.vehicles.ardupilot.transports.monitor import TelemetryMirror
from vehicle_autonomy.vehicles.ardupilot.mavlink.monitor import MonitorFramer
from vehicle_autonomy.vehicles.ardupilot.mavlink.simulation_setup import FreshSimulationSigning


class MonitorTests(unittest.TestCase):
    def test_credential_setup_payload_is_never_mirrored(self):
        peer=mav.MAVLink(None,srcSystem=250,srcComponent=191)
        credential=peer.setup_signing_encode(3,1,b'0123456789abcdef'*2,1000).pack(peer)
        heartbeat=peer.heartbeat_encode(1,3,0,0,0).pack(peer)
        self.assertEqual(MonitorFramer().feed(credential+heartbeat),(heartbeat,))

    def test_fresh_provisioning_requires_pinned_unarmed_peer_and_only_queries(self):
        key=b'0123456789abcdef'*2
        protocol=FreshSimulationSigning(3,key,1000)
        wrong=mav.MAVLink(None,srcSystem=1,srcComponent=1)
        self.assertEqual(protocol.feed(wrong.heartbeat_encode(1,3,0,0,0).pack(wrong)),[])
        peer=mav.MAVLink(None,srcSystem=3,srcComponent=1)
        with self.assertRaisesRegex(RuntimeError,'unarmed'):
            protocol.feed(peer.heartbeat_encode(1,3,128,0,0).pack(peer))
        setup=protocol.feed(peer.heartbeat_encode(1,3,0,0,0).pack(peer))
        decoded=mav.MAVLink(None).parse_buffer(setup[0])[0]
        self.assertEqual((decoded.get_type(),decoded.target_system,decoded.target_component),('SETUP_SIGNING',3,1))
        peer.signing.secret_key=key;peer.signing.sign_outgoing=True;peer.signing.timestamp=1001
        query=protocol.feed(peer.heartbeat_encode(1,3,0,0,0).pack(peer))
        decoded=mav.MAVLink(None).parse_buffer(query[0])[0]
        self.assertEqual((decoded.get_type(),decoded.command,decoded.target_system),('COMMAND_LONG',512,3))
        protocol.feed(peer.command_ack_encode(512,0).pack(peer))
        self.assertTrue(protocol.complete);protocol.crosscheck()
        self.assertEqual({f['type'] for f in protocol.frames},{'HEARTBEAT','COMMAND_ACK'})
        request=protocol.parameter_requests(['ARMING_CHECK'])[0]
        decoded=mav.MAVLink(None).parse_buffer(request)[0]
        self.assertEqual((decoded.get_type(),decoded.target_system),('PARAM_REQUEST_READ',3))

    def test_fragmented_signed_telemetry_is_unchanged_and_gcs_input_never_writes(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as gcs:
            gcs.bind(('127.0.0.1', 0));gcs.settimeout(.1)
            transport = Transport()
            mirror = TelemetryMirror(transport, gcs.getsockname()[1], frames=MonitorFramer().feed)
            try:
                peer = mav.MAVLink(None, srcSystem=3, srcComponent=1)
                peer.signing.secret_key = b'0123456789abcdef' * 2
                peer.signing.sign_outgoing = True
                peer.signing.timestamp = 1000
                wire = peer.heartbeat_encode(1, 3, 0, 0, 0).pack(peer)
                transport.incoming = [wire[:7], wire[7:]]
                self.assertEqual(mirror.read(), wire[:7])
                with self.assertRaises(socket.timeout):gcs.recvfrom(4096)
                self.assertEqual(mirror.read(), wire[7:])
                received, source = gcs.recvfrom(4096)
                self.assertEqual(received, wire)
                # A real UDP reply addressed to the mirror has no path back.
                gcs.sendto(b'not a vehicle command source', source)
                self.assertIsNone(mirror.read())
                self.assertEqual(transport.writes, [])
                mirror.write(b'only the existing writer')
                self.assertEqual(transport.writes, [b'only the existing writer'])
            finally:mirror.close()
            self.assertTrue(transport.closed)

    def test_wrong_system_heartbeat_cannot_establish_selected_vehicle(self):
        profile = SimulationProfile.load(PROFILE);transport = Transport()
        runtime = SimulationRuntime(profile, translator=ArduPilotCommandTranslator(mode_ids=profile.mode_ids),
            transport_factory=lambda *a, **kw: transport, clock=Clock(), target_system=3)
        try:
            runtime.connect()
            wrong = mav.MAVLink(None, srcSystem=1, srcComponent=1)
            transport.incoming.append(wrong.heartbeat_encode(2, 3, 0, 4, 0).pack(wrong))
            runtime.cycle()
            self.assertIsNone(runtime.session_id)
            selected = mav.MAVLink(None, srcSystem=3, srcComponent=1)
            transport.incoming.append(selected.heartbeat_encode(2, 3, 0, 4, 0).pack(selected))
            runtime.cycle()
            self.assertIsNotNone(runtime.session_id)
            self.assertEqual(transport.writes, [])
            self.assertFalse(runtime.authority.system_send)
            self.assertFalse(runtime.authority.action_send)
        finally:runtime.shutdown()

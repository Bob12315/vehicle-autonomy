import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from app.control import request
from deployment.hardware_profile import load_profile
from deployment.hardware_runtime import HardwareReadOnlyRuntime
from application.runtime_service import RuntimeService
from infrastructure.transports.readonly import ReadOnlySerial
from protocols.mavlink.readonly import TelemetryDiagnostics


class HardwareTests(unittest.TestCase):
    def test_profiles_fail_closed(self):
        base = json.loads(Path('config/deployment/hardware-readonly.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'
            for key, value in [('system_send', True), ('action_send', 1), ('mode', 'hardware_controlled'),
                               ('telemetry', {'path': '/dev/ttyACM0', 'baudrate': 115200}), ('period_s', float('nan'))]:
                bad = {**base, key: value}
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    load_profile(path)
            path.write_text(json.dumps(base))
            self.assertEqual(load_profile(path)['mode'], 'hardware_readonly')
        self.assertFalse(hasattr(ReadOnlySerial, 'write'))

    def test_runtime_has_no_command_port_and_rejects_motion(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = HardwareReadOnlyRuntime(load_profile('config/deployment/hardware-readonly.json'), directory)
            try:
                service = RuntimeService(runtime)
                runtime.cycle()
                state = service.handle('status', {})
                self.assertFalse(state['system_send'] or state['action_send'])
                self.assertFalse(state['connected'])
                self.assertEqual(service.handle('cancel', {})['physical_stop'], 'UNCONFIRMED')
                for cmd, payload in [('start', {'mission': 'basic_route'}), ('arm', {}),
                                     ('mavlink', {}), ('camera', {})]:
                    with self.assertRaises(ValueError):
                        service.handle(cmd, payload)
                self.assertFalse(hasattr(runtime, 'vehicle'))
            finally:
                runtime.close()

    def test_actual_process_lifecycle_readonly_restart_and_socket_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            endpoint = str(Path(directory) / 'app.sock')
            generations = []
            for _ in range(2):
                proc = subprocess.Popen([sys.executable, '-m', 'app.hardware', '--control-socket', endpoint,
                    '--log-dir', directory], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    until = time.monotonic() + 5
                    while not Path(endpoint).exists() and time.monotonic() < until:
                        time.sleep(.02)
                    state = request(endpoint, 'status')['result']
                    generations.append(state['session_id'])
                    self.assertFalse(state['system_send'] or state['action_send'])
                    self.assertFalse(request(endpoint, 'start', {'mission': 'basic_route'})['ok'])
                    self.assertTrue(request(endpoint, 'shutdown')['ok'])
                    self.assertEqual(proc.wait(timeout=5), 0)
                    self.assertFalse(Path(endpoint).exists())
                finally:
                    if proc.poll() is None:
                        proc.kill(); proc.wait()
                    out, err = proc.communicate()
                    self.assertNotIn(b'Traceback', err)
            self.assertNotEqual(*generations)

    def test_receive_only_telemetry_quality_jump_epoch_and_stale(self):
        from pymavlink.dialects.v20 import ardupilotmega as mav
        decoder = mav.MAVLink(None)
        def message(item):
            return decoder.parse_buffer(item.pack(mav.MAVLink(None, srcSystem=1, srcComponent=1)))[0]
        monitor = TelemetryDiagnostics()
        monitor.ingest(message(mav.MAVLink_heartbeat_message(10, 3, 0, 4, 3, 3)), 1_000_000_000)
        monitor.ingest(message(mav.MAVLink_gps_raw_int_message(1, 3, 0, 0, 0, 100, 100, 0, 0, 12)), 1_000_000_000)
        monitor.ingest(message(mav.MAVLink_ekf_status_report_message(19, 0., 0., 0., 0., 0.)), 1_000_000_000)
        monitor.ingest(message(mav.MAVLink_global_position_int_message(10, 0, 0, 0, 0, 100, 200, 0, 0)), 1_000_000_000)
        state = monitor.view(1_100_000_000)
        self.assertTrue(state['gps_diagnostic_eligible'])
        self.assertFalse(state['control_eligible'])
        self.assertEqual(state['facts']['GLOBAL_POSITION_INT']['value']['velocity_enu_mps'], [2., 1., 0.])
        monitor.ingest(message(mav.MAVLink_global_position_int_message(20, 10000000, 0, 0, 0, 0, 0, 0, 0)), 1_200_000_000)
        self.assertIn('gps_jump', monitor.view(1_200_000_000)['reasons'][-1])
        monitor.ingest(message(mav.MAVLink_global_position_int_message(1, 0, 0, 0, 0, 0, 0, 0, 0)), 1_300_000_000)
        self.assertIn('epoch_regression', monitor.fault)
        self.assertFalse(monitor.view(3_000_000_000)['gps_diagnostic_eligible'])

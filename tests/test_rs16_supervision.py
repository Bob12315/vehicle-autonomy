"""Process fixtures here are synthetic, never physical LiDAR evidence."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from deployment.rs16_profile import sensor_commands


class Rs16SupervisionTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        binary = root/'receiver'
        binary.write_text('#!/bin/sh\nsleep 2\nexit 9\n')
        binary.chmod(0o700)
        profile = json.loads(Path('config/deployment/hardware-readonly.json').read_text())
        profile['lidar_exchange'] = str(root/'cloud.json')
        config = {'schema': 1, 'host_ip': '127.0.0.1', 'msop_port': 26699,
                  'difop_port': 27788, 'duration_s': 10, 'binary': str(binary),
                  'exchange': profile['lidar_exchange']}
        return profile, config

    def test_receiver_profile_cannot_add_commands_or_diverge_from_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            profile, config = self.fixture(directory)
            path = Path(directory)/'rs16.json'
            path.write_text(json.dumps(config))
            command = sensor_commands(path, profile, Path.cwd())[0][1]
            self.assertEqual(command[:6], [config['binary'], '127.0.0.1', '26699', '27788', '10', config['exchange']])
            commands=sensor_commands(path, profile, Path.cwd(),ros=True)
            self.assertIn(commands[0][1][-1],commands[1][1])
            for fields in ({'msop_port': True}, {'difop_port': 26699}, {'duration_s': 0},
                           {'exchange': '/tmp/other.json'}, {'host_ip': 'example.com'},
                           {'extra_command': 'arm'}):
                path.write_text(json.dumps({**config, **fields}))
                with self.assertRaises(ValueError):
                    sensor_commands(path, profile, Path.cwd())
            path.write_text(json.dumps(config))
            Path(directory).chmod(0o755)
            with self.assertRaisesRegex(ValueError, 'private'):
                sensor_commands(path, profile, Path.cwd())

    def test_owned_receiver_failure_stops_application_and_web(self):
        with tempfile.TemporaryDirectory(prefix='vaf-rs16-') as directory:
            profile, config = self.fixture(directory)
            root = Path(directory)
            (root/'profile.json').write_text(json.dumps(profile))
            (root/'rs16.json').write_text(json.dumps(config))
            state = root/'state'
            with socket.socket() as s:
                s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
            args = [sys.executable, '-m', 'deployment.onboard']
            try:
                result = subprocess.run([*args, 'start', '--state-dir', str(state), '--config',
                    str(root/'profile.json'), '--rs16-config', str(root/'rs16.json'), '--port', str(port)],
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                children = json.loads((state/'children.json').read_text())
                self.assertEqual({c['name'] for c in children}, {'rs16', 'application', 'web'})
                until = time.monotonic()+10
                while (state/'supervisor.json').exists() and time.monotonic()<until:
                    time.sleep(.05)
                stopped = json.loads((state/'last-stop.json').read_text())
                self.assertFalse(stopped['passed'])
                self.assertIn('rs16 exited 9', stopped['error'])
                self.assertEqual(stopped['physical_stop'], 'UNCONFIRMED')
                self.assertFalse((state/'app.sock').exists())
                from deployment.onboard import process_identity
                for child in children:
                    self.assertNotEqual(process_identity(child['pid']), child['start_ticks'])
            finally:
                subprocess.run([*args, 'stop', '--state-dir', str(state)], capture_output=True, timeout=15)

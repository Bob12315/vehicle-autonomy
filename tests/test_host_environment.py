"""Host configuration changes must not substitute software or writable roots silently."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from vehicle_autonomy.app.bootstrap.paths import RuntimePaths


class HostEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.config = self.root/'host.toml'

    def load(self, text):
        self.config.write_text('schema = 1\n'+text)
        return HostEnvironment(self.root, config=self.config)

    def test_explicit_environment_and_index_precedence_without_fallback(self):
        local = self.root/'index-ardupilot'
        host = self.load('[paths]\nardupilot_root = '+json.dumps(str(local)))
        self.assertEqual(host.path('ardupilot_root'), local)
        with patch.dict(os.environ, {'VAF_ARDUPILOT_ROOT': str(self.root/'environment')}):
            self.assertEqual(host.path('ardupilot_root'), self.root/'environment')
            self.assertEqual(host.path('ardupilot_root', self.root/'explicit'), self.root/'explicit')
        self.assertFalse(local.exists())
        self.assertEqual(host.path('ardupilot_root'), local)

    def test_missing_explicit_file_is_not_replaced_by_template(self):
        (self.root/'environments').mkdir()
        (self.root/'environments/tools.example.toml').write_text('schema = 1\n')
        with self.assertRaises(FileNotFoundError):
            HostEnvironment(self.root, config=self.root/'missing.toml')
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.root/'absent')}):
            self.assertIsNone(HostEnvironment(self.root).config)

    def test_invalid_paths_unknown_keys_and_shell_values_are_rejected(self):
        for text in ('[paths]\nardupilot_root="relative"', '[paths]\nunknown="/tmp"',
                     '[executables]\nshell="/bin/sh"', '[environment]\n"bad-key"="x"',
                     '[paths]\nros2_root=3'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load(text)

    def test_explicit_missing_executable_is_not_autodiscovered(self):
        path = self.root/'missing-gz'
        host = self.load('[executables]\ngazebo='+json.dumps(str(path)))
        self.assertEqual(host.executable('gazebo'), str(path))
        self.assertFalse(host.report()['tools']['gazebo']['installed'])
        host = self.load('[executables]\ngazebo="~/vaf-host-test/gz"')
        self.assertEqual(host.process_environment()['PATH'].split(os.pathsep)[0], str(Path.home()/'vaf-host-test'))

    def test_checksum_detects_software_replacement(self):
        binary = self.root/'software'
        binary.write_bytes(b'qualified')
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        host = self.load('[checksums]\n'+json.dumps(str(binary))+'='+json.dumps(digest))
        host.verify(binary)
        binary.write_bytes(b'different')
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            host.verify(binary)

    def test_checksum_reference_follows_its_explicit_software_symlink(self):
        first, second, alias = self.root/'first', self.root/'second', self.root/'alias'
        first.write_bytes(b'qualified')
        second.write_bytes(b'replacement')
        alias.symlink_to(first)
        digest = hashlib.sha256(first.read_bytes()).hexdigest()
        host = self.load('[checksums]\n'+json.dumps(str(alias))+'='+json.dumps(digest))
        host.verify(alias.resolve())
        alias.unlink();alias.symlink_to(second)
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            host.verify(alias.resolve())

    def test_ros_command_uses_configured_setup_and_literal_arguments(self):
        setup = self.root/'setup with spaces.bash'
        setup.write_text('export VAF_WORKER_TEST=from_setup\n')
        host = self.load('[paths]\nros2_setup='+json.dumps(str(setup)))
        argument = '$(touch SHOULD_NOT_EXIST); literal'
        command, env = host.ros_command([sys.executable, '-c', 'import os,sys,json;print(json.dumps([os.environ["VAF_WORKER_TEST"],sys.argv[1]]))', argument])
        result = subprocess.run(command, env=env, cwd=self.root, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), ['from_setup', argument])
        self.assertFalse((self.root/'SHOULD_NOT_EXIST').exists())

    def test_configured_missing_ros_root_never_selects_another_installation(self):
        host = self.load('[paths]\nros2_root='+json.dumps(str(self.root/'missing-ros')))
        with self.assertRaisesRegex(ValueError, 'ROS environment missing'):
            host.ros_command(['/usr/bin/env'])

    def test_runtime_is_separate_from_resources_and_rejects_traversal(self):
        with patch.dict(os.environ, {'VAF_RUNTIME_ROOT': str(self.root/'private')}):
            paths = RuntimePaths(self.root)
            self.assertEqual(paths.slot('state', 'console'), self.root/'private/state/console')
            self.assertNotEqual(paths.slot('state', 'console'), paths.slot('sessions', 'console'))
            with self.assertRaises(ValueError):
                paths.slot('state', '../../outside')
        self.assertFalse((self.root/'private').exists())

    def test_absolute_gazebo_launcher_keeps_exact_owned_world_and_arguments(self):
        from vehicle_autonomy.app.bootstrap.action_ownership import _owned_command_matches
        expected = [b'/usr/bin/gz', b'sim', b'-s', b'-r', b'/private/owned-world.sdf']
        self.assertTrue(_owned_command_matches('gazebo', [b'gz sim -s -r /private/owned-world.sdf'], expected))
        self.assertTrue(_owned_command_matches('gazebo', [b'ruby', *expected], expected))
        for actual in ([b'gz sim -s -r /private/another-world.sdf'],
                       [b'gz sim -s /private/owned-world.sdf'],
                       [b'gz sim -s -r /private/owned-world.sdf', b'extra'],
                       [b'unrelated', *expected[1:]]):
            self.assertFalse(_owned_command_matches('gazebo', actual, expected))

    def test_sitl_command_identity_is_never_basename_normalized(self):
        from vehicle_autonomy.app.bootstrap.action_ownership import _owned_command_matches
        expected = [b'/private/qualified/ardurover', b'--model', b'JSON']
        self.assertTrue(_owned_command_matches('sitl', expected, expected))
        self.assertFalse(_owned_command_matches('sitl', [b'ardurover', *expected[1:]], expected))
        self.assertFalse(_owned_command_matches('sitl', [b'/other/ardurover', *expected[1:]], expected))

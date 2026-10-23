"""Test-owned credential lifetimes; never inspect or print real signing keys."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.simulation.launch import OwnedSimulation


class CredentialCleanupTests(unittest.TestCase):
    def test_owned_sitl_eeprom_removed_on_close(self):
        with tempfile.TemporaryDirectory() as directory:
            owned = OwnedSimulation(Path(directory), 'rover', confirmation_signing=True)
            # Follow the launcher's real directory-creation path without AP/Gazebo.
            with patch.object(owned, 'start_process', side_effect=RuntimeError('injected startup failure')):
                with self.assertRaisesRegex(RuntimeError, 'injected startup failure'):
                    owned.start_sitl()
            state = Path(directory) / 'sitl_state'
            (state / 'eeprom.bin').write_bytes(b'synthetic ephemeral credential')
            owned.close()
            self.assertFalse(state.exists(), 'SITL persistence survives fixture close')
            self.assertEqual(json.loads((Path(directory)/'manifest.json').read_text())['remaining_process_groups'], [])

    def test_restart_private_files_and_open_handles_are_scrubbed(self):
        from tests.simulation.credentials import OwnedCredentials
        import os
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {}
            credentials = OwnedCredentials(root, manifest)
            handles = []
            for suffix in ('', '_restart'):
                state = credentials.create_state(suffix)
                binary = state / 'eeprom.bin'
                binary.write_bytes(b'nonsecret test credential' * 100)
                handles.append(binary.open('rb'))
                private = root / ('receive-signing'+suffix+'.private')
                fd = os.open(private, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                credentials.register_private(private.name, fd)
                os.write(fd, b'nonsecret test config')
                os.close(fd)
            # This user-created file has a matching name but was NOT registered.
            unrelated = root / 'receive-signing-user.private'
            unrelated.write_bytes(b'user file')
            try:
                credentials.destroy()
                credentials.destroy()
                self.assertEqual(list(root.iterdir()), [unrelated])
                self.assertTrue(all(h.read() == b'' for h in handles))
                self.assertEqual(unrelated.read_bytes(), b'user file')
                self.assertEqual(len(manifest['credential_destruction']), 4)
            finally:
                for h in handles:
                    h.close()

    def test_symlink_inside_state_never_touches_external_target(self):
        from tests.simulation.credentials import OwnedCredentials
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / 'run'; run.mkdir()
            external = root / 'external'; external.mkdir()
            preserved = external / 'eeprom.bin'; preserved.write_bytes(b'user data')
            credentials = OwnedCredentials(run, {})
            state = credentials.create_state('')
            (state / 'linked-directory').symlink_to(external, target_is_directory=True)
            (state / 'linked-file').symlink_to(preserved)
            credentials.destroy()
            self.assertFalse(state.exists())
            self.assertEqual(preserved.read_bytes(), b'user data')

    def test_hardlink_preflight_refuses_without_altering_user_data(self):
        from tests.simulation.credentials import OwnedCredentials
        import os
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / 'run'; run.mkdir()
            external = root / 'external'; external.write_bytes(b'user data')
            credentials = OwnedCredentials(run, {})
            state = credentials.create_state('')
            owned_file = state / 'a-eeprom.bin'; owned_file.write_bytes(b'fixture data')
            os.link(external, state / 'z-hardlink')
            with self.assertRaisesRegex(ValueError, 'multiply-linked'):
                credentials.destroy()
            self.assertEqual(owned_file.read_bytes(), b'fixture data')
            self.assertEqual(external.read_bytes(), b'user data')

    def test_replaced_directory_identity_is_rejected(self):
        from tests.simulation.credentials import OwnedCredentials
        with tempfile.TemporaryDirectory() as directory:
            credentials = OwnedCredentials(Path(directory), {})
            state = credentials.create_state('')
            state.rename(state.with_name('original'))
            state.mkdir()
            preserved = state / 'eeprom.bin'; preserved.write_bytes(b'user data')
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                credentials.destroy()
            self.assertEqual(preserved.read_bytes(), b'user data')

    def test_existing_directory_and_path_escape_are_not_adopted(self):
        from tests.simulation.credentials import OwnedCredentials
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            credentials = OwnedCredentials(root, {})
            state = root / 'sitl_state'; state.mkdir()
            with self.assertRaises(FileExistsError):
                credentials.create_state('')
            with self.assertRaises(ValueError):
                credentials.create_state('/../../outside')
            credentials.destroy()
            self.assertTrue(state.is_dir())

    def test_symlink_root_rejected(self):
        from tests.simulation.credentials import OwnedCredentials
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target'; target.mkdir()
            link = root / 'link'; link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError):
                OwnedCredentials(link, {})

    def test_close_continues_after_process_stop_error_once_writer_gone(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as directory:
            owned = OwnedSimulation(Path(directory), 'copter')
            state = owned.credentials.create_state('')
            (state/'eeprom.bin').write_bytes(b'fixture data')
            process = owned.start_process('worker', [sys.executable, '-c', 'pass'])
            process.wait(timeout=5)
            original = owned.stop_process
            def stopped_then_failed(p):
                original(p)
                raise OSError('injected log/save failure')
            with patch.object(owned, 'stop_process', side_effect=stopped_then_failed):
                with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
                    owned.close()
            self.assertFalse(state.exists())
            self.assertTrue(owned.manifest['credentials_removed'])

    def test_live_writer_blocks_destruction(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            owned = OwnedSimulation(Path(directory), 'rover')
            state = owned.credentials.create_state('')
            binary = state/'eeprom.bin'; binary.write_bytes(b'fixture data')
            process = owned.start_process('worker', [sys.executable, '-c', 'import time; time.sleep(60)'])
            try:
                with patch.object(owned, 'stop_process', side_effect=OSError('injected failure')):
                    with self.assertRaisesRegex(RuntimeError, 'writers still alive'):
                        owned.close()
                self.assertTrue(binary.exists())
            finally:
                owned.close()
            self.assertFalse(state.exists())

    def test_killed_scenario_parent_fallback_destroys_registered_state(self):
        from tests.simulation.harness import StageRunner
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); stage = root/'stage'
            code = '''from pathlib import Path
import os,signal,sys
from tests.simulation.launch import OwnedSimulation
p=Path(sys.argv[1]);p.mkdir()
o=OwnedSimulation(p,'rover')
s=o.credentials.create_state('')
(s/'eeprom.bin').write_bytes(b'synthetic test credential')
o._save()
os.kill(os.getpid(),signal.SIGKILL)
'''
            result = StageRunner(root).run_stage('killed', [sys.executable, '-c', code, str(stage)],
                                                 stage_dir=stage, timeout=10)
            self.assertFalse(result['passed'])
            self.assertFalse((stage/'sitl_state').exists())
            self.assertTrue(json.loads((stage/'manifest.json').read_text())['credentials_removed'])

    def test_historical_manifest_not_implicitly_adopted_by_fallback(self):
        from tests.simulation.harness import StageRunner
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root/'sitl_state'; state.mkdir()
            binary = state/'eeprom.bin'; binary.write_bytes(b'user data')
            (root/'manifest.json').write_text(json.dumps({'processes': []}))
            StageRunner(root).cleanup_manifest(root)
            self.assertEqual(binary.read_bytes(), b'user data')

    def test_parent_fallback_waits_for_real_writer_exit_before_scrubbing(self):
        from tests.simulation.harness import StageRunner
        import sys
        from threading import Thread
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owned = OwnedSimulation(root, 'rover')
            state = owned.credentials.create_state('')
            (state/'eeprom.bin').write_bytes(b'fixture data')
            process = owned.start_process('writer', [sys.executable, '-c', 'import time; time.sleep(60)'])
            reaper = Thread(target=process.wait)
            reaper.start()
            try:
                StageRunner(root).cleanup_manifest(root)
                reaper.join(timeout=2)
                self.assertIsNotNone(process.poll())
                self.assertFalse(state.exists())
            finally:
                owned.close()
                reaper.join(timeout=5)

"""Failure, timeout, signal, repetition, and occupied-port harness gates."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
from threading import Timer
import unittest
from tests.simulation.harness import StageRunner
from tests.simulation.launch import OwnedSimulation, choose_instance


class HarnessTests(unittest.TestCase):
    def runner(self, directory):
        return StageRunner(Path(directory), total_timeout=15)

    def assert_group_gone(self, record):
        with self.assertRaises(ProcessLookupError):
            os.killpg(record['pgid'], 0)

    def test_success_and_repeated_fresh_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            for name in ('first', 'second'):
                result = runner.run_stage(name, [sys.executable, '-c', 'print("pass")'], timeout=2)
                self.assertTrue(result['passed'])
                self.assertEqual(result['exit_code'], 0)
                self.assert_group_gone(result)
            self.assertNotEqual(runner.records[0]['pid'], runner.records[1]['pid'])

    def test_nonzero_exit_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.runner(directory).run_stage('fail', [sys.executable, '-c', 'raise SystemExit(7)'])
            self.assertFalse(result['passed'])
            self.assertEqual(result['exit_code'], 7)
            self.assertEqual(result['error'], 'nonzero_exit')
            self.assert_group_gone(result)

    def test_timeout_cleans_owned_child_and_parent_group(self):
        code = '''import signal,subprocess,sys,time
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
def stop(signum, frame):
    child.terminate()
    child.wait(timeout=2)
    sys.exit(0)
signal.signal(signal.SIGTERM,stop)
print(child.pid,flush=True)
while True: time.sleep(.1)
'''
        with tempfile.TemporaryDirectory() as directory:
            result = self.runner(directory).run_stage('timeout', [sys.executable, '-c', code], timeout=.3)
            self.assertFalse(result['passed'])
            self.assertEqual(result['error'], 'timeout')
            self.assert_group_gone(result)
            child = int(Path(result['log']).read_text())
            self.assertFalse(Path(f'/proc/{child}').exists())

    def test_ctrl_c_cleans_owned_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            timer = Timer(.3, lambda: os.kill(os.getpid(), signal.SIGINT))
            timer.start()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    runner.run_stage('interrupted', [sys.executable, '-c', 'import time; time.sleep(60)'])
            finally:
                timer.cancel()
                timer.join()
            self.assertFalse(runner.records[0]['passed'])
            self.assert_group_gone(runner.records[0])

    def test_occupied_port_selects_other_instance_without_touching_listener(self):
        instance = choose_instance()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 5760 + instance * 10))
            listener.listen(1)
            self.assertNotEqual(choose_instance(), instance)
            self.assertEqual(listener.getsockname()[1], 5760 + instance * 10)
            self.assertGreaterEqual(listener.fileno(), 0)

    def test_fallback_ignores_reused_pid_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
            try:
                stage = Path(directory) / 'stage'
                stage.mkdir()
                (stage / 'manifest.json').write_text(json.dumps({'processes': [
                    {'pid': process.pid, 'pgid': process.pid, 'start_ticks': 'wrong-identity'}]}))
                self.runner(directory).cleanup_manifest(stage)
                self.assertIsNone(process.poll())
            finally:
                process.terminate()
                process.wait(timeout=2)

    def test_repeated_nested_stage_names_have_different_world_epochs(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'suite-one/rover_full'
            second = Path(directory) / 'suite-two/rover_full'
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            a = OwnedSimulation(first, 'rover')
            b = OwnedSimulation(second, 'rover')
            self.assertNotEqual(a.world, b.world)
            self.assertEqual(a.profile.port, a.port)
            self.assertIn(str(a.json_port), a.model_path.read_text())

    def test_cli_injected_failure_is_nonzero_and_machine_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / 'suite'
            result = subprocess.run([sys.executable, '-m', 'tests.simulation.harness',
                '--inject-failure', '--run-dir', str(run_dir)], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            report = json.loads((run_dir / 'summary.json').read_text())
            self.assertFalse(report['passed'])
            self.assertEqual(report['failed_stages'], 1)
            self.assertEqual(report['not_run_scenarios'], 7)
            self.assertEqual(report['stages'][0]['exit_code'], 7)

import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
import os
import signal
import time


class SupervisorTests(unittest.TestCase):
    def test_owned_application_crash_stops_stack_and_restart_stays_readonly(self):
        with tempfile.TemporaryDirectory(prefix='vaf-crash-') as directory:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            def command(operation):
                result=subprocess.run([sys.executable,'-m','deployment.onboard',operation,'--state-dir',directory,
                    '--port',str(port)],capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                return json.loads(result.stdout)
            try:
                command('start');old=command('status')['result']['session_id']
                time.sleep(.3)  # allow supervisor to record its own socket inode
                children=json.loads((Path(directory)/'children.json').read_text())
                app=next(child for child in children if child['name']=='application')
                from deployment.onboard import process_identity
                self.assertEqual(process_identity(app['pid']),app['start_ticks'])
                os.kill(app['pid'],signal.SIGKILL)
                deadline=time.monotonic()+6
                while (Path(directory)/'supervisor.json').exists() and time.monotonic()<deadline:time.sleep(.05)
                self.assertFalse((Path(directory)/'supervisor.json').exists())
                self.assertFalse((Path(directory)/'app.sock').exists())
                stopped=json.loads((Path(directory)/'last-stop.json').read_text())
                self.assertFalse(stopped['passed']);self.assertIn('application exited',stopped['error'])
                command('start');new=command('status')['result']
                self.assertNotEqual(old,new['session_id'])
                self.assertFalse(new['system_send'] or new['action_send'])
            finally:subprocess.run([sys.executable,'-m','deployment.onboard','stop','--state-dir',directory],capture_output=True,timeout=15)
    def test_actual_start_health_stop_and_fresh_restart(self):
        with tempfile.TemporaryDirectory(prefix='vaf-supervisor-') as directory:
            Path(directory).chmod(0o700)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            def command(operation):
                result=subprocess.run([sys.executable,'-m','deployment.onboard',operation,'--state-dir',directory,
                    '--port',str(port)],capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr+result.stdout)
                return json.loads(result.stdout)
            sessions=[]
            try:
                for _ in range(2):
                    self.assertTrue(command('start')['started'])
                    state=command('status')['result'];sessions.append(state['session_id'])
                    self.assertFalse(state['system_send'] or state['action_send'])
                    self.assertEqual(state['mode'],'hardware_readonly')
                    self.assertTrue(command('stop')['stopped'])
                    self.assertFalse((Path(directory)/'app.sock').exists())
                self.assertNotEqual(*sessions)
            finally:
                subprocess.run([sys.executable,'-m','deployment.onboard','stop','--state-dir',directory],
                               capture_output=True,timeout=15)

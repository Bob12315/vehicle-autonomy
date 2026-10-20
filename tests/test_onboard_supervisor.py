import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest


class SupervisorTests(unittest.TestCase):
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

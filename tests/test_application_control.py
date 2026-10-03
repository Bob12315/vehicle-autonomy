"""IPC framing, retry identity and owned endpoint cleanup, including real CLI."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from app.control import ControlServer, request


class Service:
    def __init__(self):
        self.calls = 0

    def handle(self, command, payload):
        self.calls += 1
        return {"calls": self.calls}


class ControlTests(unittest.TestCase):
    def test_retry_validation_and_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.sock"
            service = Service()
            server = ControlServer(path, service)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            raw = json.dumps({"request_id": "one", "command": "start", "payload": {"mission": "x"}})
            self.assertEqual(server._response(raw), server._response(raw))
            self.assertEqual(service.calls, 1)
            self.assertFalse(server._response(raw.replace('"x"', '"y"'))["ok"])
            self.assertFalse(server._response('{"command":"start"}')["ok"])
            with self.assertRaises(OSError):
                ControlServer(path, service)
            self.assertTrue(path.exists())
            path.unlink()
            path.write_text("replacement")
            server.close()
            self.assertEqual(path.read_text(), "replacement")

    def test_real_process_without_sitl_is_queryable_and_sigterm_cleans_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.sock"
            config = Path(directory) / "profile.toml"
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            source = Path("simulation/profiles/copter.toml").read_text()
            config.write_text(source.replace("port = 5760", f"port = {port}"))
            process = subprocess.Popen([sys.executable, "-m", "app.main", "run", "--profile", "copter_sim",
                                       "--config", str(config), "--control-socket", str(path)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                until = time.monotonic() + 5
                while not path.exists() and time.monotonic() < until and process.poll() is None:
                    time.sleep(.02)
                state = request(path, "status")["result"]
                self.assertEqual(state["state"], "CONNECTING")
                self.assertFalse(state["system_send"])
                self.assertFalse(request(path, "start", {"mission": "disarmed_mode"})["ok"])
                self.assertFalse(request(path, "mavlink", {"raw": "x"})["ok"])
                # A stalled partial message does not block the scheduler/status client.
                with socket.socket(socket.AF_UNIX) as stalled:
                    stalled.connect(str(path))
                    stalled.sendall(b'{')
                    self.assertTrue(request(path, "status")["ok"])
                cli = subprocess.run([sys.executable, "-m", "app.main", "ctl", "--profile", "copter_sim",
                    "--control-socket", str(path), "status"], capture_output=True, text=True, timeout=4)
                self.assertEqual(cli.returncode, 0, cli.stderr)
                self.assertTrue(json.loads(cli.stdout)["ok"])
                process.terminate()
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertFalse(path.exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                errors = process.stderr.read().decode()
                process.stderr.close()
                self.assertNotIn("Traceback", errors)

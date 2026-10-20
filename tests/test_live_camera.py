import base64
from pathlib import Path
import tempfile
import time
import unittest

from sensors.camera.live import CameraSource


class CameraTests(unittest.TestCase):
    def test_explicit_recording_capture_preview_and_process_cleanup(self):
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            recording=Path(directory)/'synthetic-software-fixture.avi'
            writer=cv2.VideoWriter(str(recording),cv2.VideoWriter_fourcc(*'MJPG'),10,(64,48))
            self.assertTrue(writer.isOpened())
            for i in range(30):writer.write(np.full((48,64,3),i*8,dtype=np.uint8))
            writer.release()
            source=CameraSource({'kind':'recording','path':str(recording),'fps':5})
            try:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline and not source.health()['online']:time.sleep(.05)
                health=source.health()
                self.assertTrue(health['online'],health)
                self.assertEqual(health['kind'],'recording')
                self.assertIn('unknown',health['capture_time'])
                self.assertTrue(base64.b64decode(source.frame()['base64']).startswith(b'\xff\xd8'))
                pid=source.process.pid
                source.process.kill();source.process.wait(timeout=2)
                self.assertFalse(source.health()['online'])
                with self.assertRaises(ValueError):source.frame()
            finally:source.close()
            self.assertFalse(Path(f'/proc/{pid}').exists())

    def test_missing_recording_never_becomes_live_hardware(self):
        source=CameraSource({'kind':'recording','path':'/nonexistent/vaf.avi','fps':5})
        try:
            source.process.wait(timeout=5)
            self.assertFalse(source.health()['online'])
            with self.assertRaises(ValueError):source.frame()
        finally:source.close()

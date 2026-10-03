"""Recorded timestamp/quality/EOS/geometry faults, with no model download/device."""
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contracts.core.time import TimePoint
from contracts.core.quality import QualityState
from perception.vision.yolox import PixelDetection
from sensors.camera.recorded import RecordedVisionSource

class Detector:
    delay=0
    def detect(self,image):
        time.sleep(self.delay)
        return (PixelDetection(5,.9,(0.,0.,1.,1.)),)

class RecordedCameraTests(unittest.TestCase):
    def fixture(self,directory,*,calibrated=False):
        root=Path(directory);(root/'image').write_bytes(b'fixture');digest=hashlib.sha256(b'fixture').hexdigest()
        if calibrated:(root/'cal.toml').write_text('''schema=1
frame="odom"
width=1
height=1
fx=1.0
fy=1.0
cx=0.5
cy=0.5
translation=[0.0,0.0,2.0]
rotation=[1.0,0.0,0.0,0.0]
plane_z=0.0
source="explicit test rig"
max_distance_m=4.0
''')
        path=root/'recording.json';path.write_text(json.dumps({'schema':1,'kind':'recorded_virtual_camera','source':'test recording','model':'unused','model_sha256':'unused','calibration':'cal.toml' if calibrated else None,'threshold':.5,'class_map':{'5':'bucket_1'},'frames':[{'pts_ns':0,'path':'image','sha256':digest}]}));return path
    def now(self):return TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),'host-monotonic-simulation')
    def test_unlocated_detections_never_enter_motion_world_and_eos(self):
        with TemporaryDirectory() as d,patch('sensors.camera.recorded.YoloXDetector',return_value=Detector()),patch.dict('sys.modules',{'cv2':SimpleNamespace(imread=lambda _:SimpleNamespace(shape=(1,1,3)))}):
            source=RecordedVisionSource(self.fixture(d),self.now().clock_domain_id)
            try:
                source.poll(self.now());until=time.monotonic()+2
                while source.health['frames']<1 and time.monotonic()<until:time.sleep(.01)
                self.assertEqual(source.poll(self.now()),());self.assertEqual(source.health['unlocated'],1)
                self.assertEqual(source.pixel_observations[0].frame_id,'camera_optical');self.assertTrue(source.health['eos'])
                self.assertFalse(source.health['error'])
            finally:source.close()
            self.assertFalse(source.thread.is_alive())
    def test_late_inference_preserves_capture_and_invalidates(self):
        detector=Detector();detector.delay=1.1
        with TemporaryDirectory() as d,patch('sensors.camera.recorded.YoloXDetector',return_value=detector),patch.dict('sys.modules',{'cv2':SimpleNamespace(imread=lambda _:SimpleNamespace(shape=(1,1,3)))}):
            source=RecordedVisionSource(self.fixture(d,calibrated=True),self.now().clock_domain_id)
            try:
                capture=self.now();source.poll(capture);until=time.monotonic()+3
                while source.health['frames']<1 and time.monotonic()<until:time.sleep(.01)
                output=source.poll(self.now());self.assertEqual(len(output),1)
                self.assertEqual(output[0].quality,QualityState.INVALID);self.assertEqual(output[0].captured_at,capture)
                self.assertGreater(output[0].received_at.elapsed_ns_since(output[0].captured_at),1_000_000_000)
            finally:source.close()
    def test_recording_regression_rejected_before_loading_weights(self):
        with TemporaryDirectory() as d:
            path=self.fixture(d);document=json.loads(path.read_text());document['frames']*=2;path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):RecordedVisionSource(path,'clock')

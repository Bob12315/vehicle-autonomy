"""Producer synchronization/independence fixtures; not flight evidence."""
import json,math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.world.sensors.camera.nadir_stream import NadirStream
from vehicle_autonomy.world.sensors.camera.nadir_stream import capture_from_metadata
from vehicle_autonomy.world.sensors.camera.gazebo import capture_lower_bound
from vehicle_autonomy.world.sensors.camera.packet import encode,decode
from vehicle_autonomy.world.sensors.camera.motion import match_position
from vehicle_autonomy.world.perception.vision.rescue_geometry import project
from vehicle_autonomy.world.perception.vision.yolox import PixelDetection


class NadirStreamTests(unittest.TestCase):
    def setUp(self):
        import cv2,numpy as np
        self.folder=TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name)
        self.now=1_000_000_000_000;self.capture=self.now-100_000_000
        config=json.loads((resource_root()/'configs/perception/rescue_2026_pt.json').read_text())
        self.config=dict(config,camera_topic='/owned/camera',camera_packet=str(self.root/'camera.packet'))
        image=np.full((480,640,3),90,np.uint8);image[80:200,100:250]=(230,70,80)
        self.jpeg=cv2.imencode('.jpg',image)[1].tobytes()
        self.stream=NadirStream(self.root,self.config,'epoch');self.addCleanup(self.stream.close)
        self.motion(self.now)

    def motion(self,end,*,generation='world'):
        self.value=dict(schema=1,world_generation=generation,link_session_id='session',clock_domain_id='host-monotonic-simulation',
            published_ns=self.now,positions=[],attitudes=[[end-i*50_000_000,0,0,math.sin(math.pi/4),math.cos(math.pi/4)] for i in reversed(range(20))])
        (self.root/'pose.json').write_text(json.dumps(self.value))

    def camera(self,sequence,capture=None):
        capture=self.capture if capture is None else capture
        self.original=dict(kind='gazebo',sequence=sequence,source='/owned/camera',captured_ns=sequence*100_000_000,
            received_ns=capture+1_000_000,capture_clock='gazebo-simulation',clock_sim_ns=sequence*100_000_000,
            clock_host_ns=capture,width=640,height=480)
        (self.root/'camera.packet').write_bytes(encode(self.original,self.jpeg))

    def step(self):
        with patch('vehicle_autonomy.world.sensors.camera.nadir_stream.time.monotonic_ns',return_value=self.now):self.stream.step()

    def test_missing_position_does_not_block_stabilized_pixels_or_create_a_world_origin(self):
        self.camera(1);self.step()
        header,_=decode((self.root/'stabilized.packet').read_bytes())
        self.assertTrue(header['rectification']['valid']);self.assertFalse(header['rectification']['position_valid'])
        self.assertIsNone(header['rectification']['origin_enu']);self.assertEqual(header['received_ns'],self.original['received_ns'])
        captured=self.stream.ready.get_nowait()
        with self.assertRaises(ValueError):match_position(self.value,self.capture,self.now)
        with self.assertRaisesRegex(ValueError,'no qualified position'):
            project(PixelDetection(0,.9,(310,230,330,250)),None,'bucket',virtual_camera=captured.frame.camera)

    def test_pending_original_is_kept_while_waiting_for_a_real_after_sample(self):
        first_capture=self.now-50_000_000;self.motion(self.now-100_000_000)
        self.camera(1,first_capture);self.step()
        self.assertEqual(len(self.stream.pending),1);self.assertTrue(self.stream.ready.empty())
        self.now+=100_000_000;self.motion(self.now)
        self.camera(2,self.now-50_000_000);self.step()
        first=self.stream.ready.get_nowait();second=self.stream.ready.get_nowait()
        self.assertEqual((first.metadata['sequence'],second.metadata['sequence']),(1,2))
        self.assertEqual(first.capture_ns,first_capture)
        self.assertEqual(self.stream.stats['produced'],2)

    def test_slow_inference_cannot_block_production_and_ring_and_queue_are_bounded(self):
        for sequence in range(1,70):self.camera(sequence);self.step()
        self.assertEqual(self.stream.stats['produced'],69)
        self.assertEqual(self.stream.ready.qsize(),4)
        self.assertEqual(self.stream.stats['inference_queue_overflow'],65)
        self.assertEqual(len(list((self.root/'stabilized-history').iterdir())),64)
        self.assertEqual(decode((self.root/'stabilized.packet').read_bytes())[0]['sequence'],69)

    def test_old_frame_cannot_be_refreshed_by_new_health_publication(self):
        self.camera(1);self.step();received=self.original['received_ns']
        self.now+=2_000_000_000;self.motion(self.now);self.step()
        health=json.loads((self.root/'stabilization-health.json').read_text())
        self.assertFalse(health['rectification_valid'])
        self.assertEqual(decode((self.root/'stabilized.packet').read_bytes())[0]['received_ns'],received)

    def test_pending_overflow_and_expiration_do_not_extrapolate(self):
        self.motion(self.now-200_000_000)
        for sequence in range(1,12):self.camera(sequence,self.now-50_000_000);self.step()
        self.assertEqual(len(self.stream.pending),8);self.assertEqual(self.stream.stats['pending_overflow'],3)
        self.assertEqual(self.stream.stats['produced'],0)
        self.now+=500_000_000;self.motion(self.now);self.step()
        self.assertEqual(len(self.stream.pending),0);self.assertEqual(self.stream.stats['capture_expired'],8)

    def test_camera_clock_uses_real_causal_samples_at_any_simulation_speed(self):
        # Sim runs at 0.5x here: extrapolating the latest clock at 1x would
        # invent an exposure AFTER the actual image receipt.
        history=[(100,1000),(110,1020),(120,1040)]
        self.assertEqual(capture_lower_bound(history,110,1025),1020)
        self.assertEqual(capture_lower_bound(history,115,1030),1020)
        self.assertIsNone(capture_lower_bound(history,90,1025))
        self.assertIsNone(capture_lower_bound([(120,1040)],110,1025))
        metadata=dict(capture_host_lower_ns=1020,received_ns=1025,clock_host_ns=1040,clock_sim_ns=120,captured_ns=110)
        self.assertEqual(capture_from_metadata(metadata),1020)
        with self.assertRaises(ValueError):capture_from_metadata(dict(metadata,capture_host_lower_ns=None))
        with self.assertRaises(ValueError):capture_from_metadata(dict(metadata,capture_host_lower_ns=1030))


if __name__=='__main__':unittest.main()

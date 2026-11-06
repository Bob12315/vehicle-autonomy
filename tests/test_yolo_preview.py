"""Annotated preview contracts; native PT/browser checks live in simulation/."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import time
import unittest

from vehicle_autonomy.world.perception.vision.preview import annotated_packet
from vehicle_autonomy.world.perception.vision.yolox import PixelDetection
from vehicle_autonomy.world.sensors.camera.packet import decode, encode
from vehicle_autonomy.world.sensors.camera.processed import DetectionPreviewSource
from tests.test_camera_preview import Source, JPEG


class YoloPreviewTests(unittest.TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.raw=Source();self.worker=dict(worker_alive=True,model_sha256='pinned-model')
        self.world=SimpleNamespace(version=SimpleNamespace(generation_id='generation'))
        self.source=DetectionPreviewSource(self.directory.name,self.raw,lambda:self.world,lambda:self.worker,
            model_sha256='pinned-model',source='owned-camera-topic')
        self.metadata=dict(sequence=7,received_ns=time.monotonic_ns()-20_000_000,
            kind='gazebo',source='owned-camera-topic',capture_clock='gazebo-simulation',captured_ns=123)
        self.header=dict(self.metadata,kind='yolo',original_received_ns=self.metadata['received_ns'],
            captured_host_ns=self.metadata['received_ns']-1_000_000,inference_completed_ns=time.monotonic_ns(),
            detector_epoch='epoch',world_generation='generation',model_sha256='pinned-model')
        self.write()

    def write(self):
        (Path(self.directory.name)/'preview.packet').write_bytes(encode(self.header,JPEG))

    def test_render_exact_detections_without_mutating_input_or_retiming_capture(self):
        import cv2,numpy as np
        image=np.full((480,640,3),120,np.uint8);before=image.copy()
        detections=[(PixelDetection(0,.9,(40.,80.,200.,230.)),'pt'),
            (PixelDetection(1,.8,(350.,90.,500.,260.)),'h_marker')]
        data=annotated_packet(image,self.metadata,detections,('bucket','H'),epoch='epoch',
            world_generation='generation',model_sha256='pinned-model',
            captured_host_ns=self.header['captured_host_ns'],started_ns=1,completed_ns=20_000_001)
        header,jpeg=decode(data);pixels=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
        self.assertTrue(np.array_equal(image,before));self.assertEqual(pixels.shape,image.shape)
        self.assertGreater(int(pixels[100,40,1]),int(pixels[100,40,0])+70)
        self.assertGreater(int(pixels[100,350,0]),int(pixels[100,350,2])+70)
        self.assertEqual(header['received_ns'],self.metadata['received_ns'])
        self.assertEqual(header['captured_ns'],123);self.assertEqual(header['sequence'],7)
        self.assertEqual([d['detector'] for d in header['detections']],['pt','h_marker'])
        self.assertEqual([d['label'] for d in header['detections']],['bucket','H'])

    def test_fresh_view_does_not_require_world_localizable_objects_or_send(self):
        self.worker.update(online=False,error='unprojectable object')
        self.assertTrue(self.source.health()['online'])
        self.assertEqual(self.source.packet(),(self.header,JPEG))

    def test_new_jpeg_timestamp_cannot_refresh_old_original_capture(self):
        self.header['captured_host_ns']=time.monotonic_ns()-2_000_000_000;self.write()
        self.assertFalse(self.source.health()['online'])
        with self.assertRaises(ValueError):self.source.packet()

    def test_mismatched_provenance_and_invalid_times_are_rejected(self):
        for key,value in (('source','other'),('model_sha256','other'),('world_generation','other'),
                ('kind','gazebo'),('original_received_ns',0),('inference_completed_ns',time.monotonic_ns()+10**12)):
            with self.subTest(key=key):
                original=self.header[key];self.header[key]=value;self.write()
                with self.assertRaises(ValueError):self.source.packet()
                self.header[key]=original
        self.write();self.assertTrue(self.source.health()['online'])

    def test_worker_death_raw_staleness_and_epoch_replacement_cannot_reuse_frame(self):
        self.source.packet();self.worker['worker_alive']=False
        with self.assertRaises(ValueError):self.source.packet()
        self.worker['worker_alive']=True;self.raw.stale=True
        with self.assertRaises(ValueError):self.source.packet()
        self.raw.stale=False;self.header['detector_epoch']='replacement';self.write()
        with self.assertRaises(ValueError):self.source.packet()

    def test_retiring_view_does_not_close_original_capture(self):
        self.source.close();self.source.close()
        self.assertFalse(self.source.health()['online']);self.assertFalse(self.raw.closed)
        with self.assertRaises(ValueError):self.source.packet()

    def test_virtual_domain_reference_and_live_synchronization_are_required(self):
        self.source=DetectionPreviewSource(self.directory.name,self.raw,lambda:self.world,lambda:self.worker,
            model_sha256='pinned-model',source='owned-camera-topic',image_domain='virtual_nadir')
        self.worker['stabilization']=dict(valid=True,reference_id='reference')
        self.header.update(image_domain='virtual_nadir',rectification=dict(valid=True,reference_id='reference'))
        self.write();self.assertTrue(self.source.health()['online'])
        self.worker['stabilization']['valid']=False
        with self.assertRaises(ValueError):self.source.packet()
        self.worker['stabilization']['valid']=True;self.header['image_domain']='raw';self.write()
        with self.assertRaises(ValueError):self.source.packet()
        self.header['image_domain']='virtual_nadir';self.header['rectification']['reference_id']='changed';self.write()
        with self.assertRaises(ValueError):self.source.packet()
        self.header['rectification']=[];self.write()
        self.assertFalse(self.source.health()['online'])
        with self.assertRaises(ValueError):self.source.packet()

    def test_export_ring_recovers_bursts_but_not_stale_or_retired_frames(self):
        self.source=DetectionPreviewSource(self.directory.name,self.raw,lambda:self.world,lambda:self.worker,
            model_sha256='pinned-model',source='owned-camera-topic',kind='stabilized',
            filename='stabilized.packet',image_domain='virtual_nadir')
        self.worker['stabilization']=dict(valid=True,reference_id='reference')
        self.header.update(kind='stabilized',image_domain='virtual_nadir',rectification=dict(valid=True,reference_id='reference'))
        self.source.path.write_bytes(encode(self.header,JPEG))
        for sequence in (6,7):
            slot=Path(self.directory.name)/'stabilized-history'/format(sequence%64,'02d');slot.mkdir(parents=True)
            original=dict(self.metadata,sequence=sequence)
            (slot/'raw.packet').write_bytes(encode(original,JPEG))
            (slot/'stabilized.packet').write_bytes(encode(dict(self.header,sequence=sequence),JPEG))
        pairs=self.source.recording_pairs(5)
        self.assertEqual([p[0]['sequence'] for p in pairs],[6,7])
        stale=dict(self.header,sequence=6,captured_host_ns=time.monotonic_ns()-2_000_000_000)
        slot=Path(self.directory.name)/'stabilized-history/06/stabilized.packet';slot.write_bytes(encode(stale,JPEG))
        self.assertEqual([p[0]['sequence'] for p in self.source.recording_pairs(5)],[7])
        self.source.close()
        with self.assertRaises(ValueError):self.source.recording_pairs(5)


if __name__=='__main__':unittest.main()

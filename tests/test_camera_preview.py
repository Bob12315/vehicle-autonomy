"""Video contracts/HTTP fixtures only; native acceptance uses real Gazebo Image."""
import base64
import hashlib
import http.client
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from vehicle_autonomy.world.sensors.camera.packet import encode, decode
from vehicle_autonomy.world.sensors.camera.manager import CameraSourceManager
from vehicle_autonomy.app.simulation.camera_assembly import assemble
from tests.web_ui.helpers import Harness

JPEG = b'\xff\xd8unit-video-contract-fixture\xff\xd9'


class Source:
    def __init__(self): self.closed=False; self.stale=False
    def health(self):return dict(online=not self.stale,kind='fixture',source='unit-only',age_ns=2_000_000_000 if self.stale else 0)
    def packet(self):
        if self.closed or self.stale: raise ValueError('no fresh frame')
        now=time.monotonic_ns()
        return dict(sequence=now//100_000_000,received_ns=now,captured_ns=None,capture_clock='unknown'),JPEG
    def close(self):self.closed=True


def binding(target='A',epoch='e1'):return dict(target=target,vehicle_id='vehicle-'+target,world='w',session='s',epoch=epoch)


class CameraRegistryTests(unittest.TestCase):
    def test_atomic_packet_pair_and_bounds(self):
        for i in range(2):
            meta=dict(sequence=i,received_ns=i)
            self.assertEqual(decode(encode(meta,JPEG)),(meta,JPEG))
        for data in (b'',b'\x00\x00\xff\xff'+JPEG,b'x'*1_016_389):
            with self.assertRaises(ValueError):decode(data)
        with self.assertRaises(ValueError):encode({},b'wrong')

    def test_corrupt_worker_health_is_a_camera_fault_not_a_world_exception(self):
        from vehicle_autonomy.world.sensors.camera.live import CameraSource
        source=CameraSource(dict(kind='recording',path='/missing/camera-preview-unit.avi',fps=5))
        try:
            source.process.wait(5)
            for health in ([1],dict(received_ns='invalid'),dict(received_ns=None)):
                (source.path/'health.json').write_text(json.dumps(health))
                self.assertFalse(source.health()['online'])
                with self.assertRaises(ValueError):source.packet()
        finally:source.close()

    def test_queued_clock_and_old_simulation_capture_cannot_appear_fresh(self):
        from vehicle_autonomy.world.sensors.camera.gazebo import clock_pair,fresh_capture
        with self.assertRaises(ValueError):clock_pair(5_000_000_000,1_000_000_000,8_000_000_000,3_000_000_000)
        pair=clock_pair(5_000_000_000,3_000_000_000,8_000_000_000,3_100_000_000)
        self.assertTrue(fresh_capture(pair,4_900_000_000,8_100_000_000))
        self.assertFalse(fresh_capture(pair,3_000_000_000,8_100_000_000))
        self.assertFalse(fresh_capture(pair,5_000_000_000,9_000_000_000))

    def test_target_epoch_retirement_and_recreation_cannot_return_old_frame(self):
        active={'A':'e1'};m=CameraSourceManager(lambda b:active.get(b['target'])==b['epoch']);self.addCleanup(m.close)
        old=Source();a=m.register(binding(),'front',old)
        with self.assertRaises(ValueError):m.packet('B',a)
        active['A']='e2'
        self.assertEqual(m.catalog('A'),[])
        with self.assertRaises(ValueError):m.packet('A',a)
        fresh=m.register(binding(epoch='e2'),'front',Source());self.assertNotEqual(a,fresh)
        self.assertEqual(m.packet('A',fresh)[0]['binding']['epoch'],'e2')
        m.retire('A');self.assertTrue(old.closed);self.assertEqual(m.catalog('A'),[])

    def test_multiple_sources_budget_and_closed_manager(self):
        m=CameraSourceManager();ids=[]
        for i in range(16):ids.append(m.register(binding(),'camera-'+str(i),Source()))
        self.assertEqual(len(set(ids)),16)
        with self.assertRaises(ValueError):m.register(binding(),'extra',Source())
        with self.assertRaises(ValueError):m.register(binding(),'camera-0',Source())
        m.close()
        self.assertEqual(m.catalog('A'),[])
        with self.assertRaises(ValueError):m.packet('A',ids[0])

    def test_stale_source_never_supplies_snapshot(self):
        m=CameraSourceManager();self.addCleanup(m.close);s=Source();camera=m.register(binding(),'front',s)
        m.packet('A',camera);s.stale=True
        self.assertFalse(m.catalog('A')[0]['online'])
        with self.assertRaises(ValueError):m.packet('A',camera)

    def test_recorded_source_is_finite_and_manager_owns_process(self):
        import cv2,numpy as np
        with TemporaryDirectory() as d:
            path=Path(d)/'explicit-unit-recording.avi';w=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),5,(32,24))
            self.assertTrue(w.isOpened())
            for i in range(6):w.write(np.full((24,32,3),i*30,dtype=np.uint8))
            w.release();m=CameraSourceManager()
            try:
                cam=m.add_source(binding(),'recorded',dict(kind='recording',path=str(path),fps=5))
                end=time.monotonic()+4
                while time.monotonic()<end and not m.catalog('A')[0]['online']:time.sleep(.02)
                meta,jpeg=m.packet('A',cam);self.assertEqual(meta['kind'],'recording');self.assertIsNone(meta['captured_ns'])
                source=m.sources[cam][2];pid=source.process.pid;source.process.wait(5)
                self.assertFalse(m.catalog('A')[0]['online'])
                with self.assertRaises(ValueError):m.packet('A',cam)
            finally:m.close()
            self.assertFalse(Path('/proc/'+str(pid)).exists())


class CameraHTTPTests(unittest.TestCase):
    def setUp(self):
        self.h=Harness();self.addCleanup(self.h.close);self.c=self.h.client();self.c.login()
        self.h.lab.cameras.binding_valid=lambda b:True
        self.source=Source();self.camera=self.h.lab.cameras.register(binding('rover'),'front',self.source)
        self.route='/api/cameras/'+self.camera
    def connection(self,path,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.h.server.server_address[1],timeout=3);self.addCleanup(conn.close)
        conn.request('GET',path,headers=headers or {});return conn.getresponse()
    def test_auth_target_and_query_credentials_are_required(self):
        self.assertEqual(self.connection('/api/cameras?target=rover').status,401)
        headers={'Authorization':'Bearer '+self.h.token}
        self.assertEqual(self.connection('/api/cameras?target=rover&token=no',headers).status,409)
        self.assertEqual(self.connection(self.route+'/snapshot?target=B',headers).status,409)
        self.assertEqual(self.connection('/api/cameras',headers).status,409)
        dotted=self.h.lab.cameras.register(binding('rover.2'),'front',Source())
        self.assertEqual(self.connection('/api/cameras/'+dotted+'/snapshot?target=rover.2',headers).status,200)
        self.assertEqual(self.connection('/api/cameras?target=rover',dict(headers,Origin='https://evil.test')).status,403)
    def test_snapshot_mjpeg_metadata_and_no_control_or_writer(self):
        headers={'Authorization':'Bearer '+self.h.token}
        r=self.connection(self.route+'/snapshot?target=rover',headers)
        self.assertEqual(r.status,200);self.assertEqual(r.getheader('X-Camera-Target'),'rover');self.assertEqual(r.read(),JPEG)
        r=self.connection(self.route+'/stream?target=rover',headers)
        self.assertEqual(r.status,200);self.assertTrue(r.getheader('Content-Type').startswith('multipart/'))
        self.assertEqual(r.readline(),b'--vaf-camera\r\n');fields={}
        while True:
            line=r.readline()
            if line==b'\r\n':break
            k,v=line.decode().strip().split(': ',1);fields[k]=v
        self.assertEqual(fields['X-Camera-ID'],self.camera);self.assertEqual(r.read(int(fields['Content-Length'])),JPEG)
        self.assertFalse(self.h.lab.operator_controls.records);self.assertFalse(self.h.lab.runtime.views());self.assertFalse(self.h.drivers['rover'].writes)
    def test_stream_rechecks_logout_stale_and_retirement(self):
        for reason in ('logout','stale','retire'):
            if reason=='logout':
                headers={'Cookie':'; '.join(c.name+'='+c.value for c in self.c.cookies)}
            else:headers={'Authorization':'Bearer '+self.h.token}
            r=self.connection(self.route+'/stream?target=rover',headers);self.assertEqual(r.status,200)
            self.assertEqual(r.readline(),b'--vaf-camera\r\n')
            if reason=='logout':self.c.call('/api/auth/logout',{})
            if reason=='stale':self.source.stale=True
            if reason=='retire':self.h.lab.cameras.binding_valid=lambda b:False
            self.assertLess(len(r.read()),5000);self.source.stale=False
    def test_stream_budget_does_not_exhaust_control_http_slots(self):
        for _ in range(4):self.h.server.camera_slots.acquire()
        try:
            self.assertEqual(self.connection(self.route+'/stream?target=rover',{'Authorization':'Bearer '+self.h.token}).status,429)
            self.assertEqual(self.c.call('/api/control/state')[0],200)
        finally:
            for _ in range(4):self.h.server.camera_slots.release()


class CameraAssemblyTests(unittest.TestCase):
    def test_camera_overlay_preserves_base_locks_and_vehicle_dynamics(self):
        from vehicle_autonomy._resources import resource_root
        with TemporaryDirectory() as d:
            path=Path(d)/'model.sdf';path.write_text('<sdf version="1.9"><model name="unit"><link name="base_link"><inertial><mass>1</mass></inertial><collision name="c"/></link><plugin name="ArduPilotPlugin" filename="unit"><control channel="0"/></plugin></model></sdf>')
            import xml.etree.ElementTree as ET
            before=ET.parse(path);original=hashlib.sha256(path.read_bytes()).hexdigest()
            p=dict(kind='rover',entity_name='unit',model_path=path,fingerprint='unchanged-base-lock',prepared_model_hash=original)
            result=assemble(resource_root(),Path(d),p,'world-A')
            after=ET.parse(path)
            for query in ('model/link/inertial','model/link/collision','model/plugin'):
                self.assertEqual(ET.tostring(before.find(query)),ET.tostring(after.find(query)))
            self.assertEqual(result['base_fingerprint'],p['fingerprint']);self.assertEqual(result['base_prepared_sha256'],original)
            self.assertIn('/world-A/unit/',result['cameras'][0]['topic']);self.assertNotEqual(result['derived_prepared_sha256'],original)
            saved=json.loads((Path(d)/'vehicle.json').read_text())
            self.assertEqual(saved['base_prepared_model_hash'],original)
            self.assertEqual(saved['prepared_model_hash'],hashlib.sha256(path.read_bytes()).hexdigest())
    def test_nested_existing_camera_topics_are_isolated_without_rewriting_geometry(self):
        from vehicle_autonomy._resources import resource_root
        with TemporaryDirectory() as d:
            root=Path(d);child=root/'child.sdf';child.write_text('<sdf><model name="gimbal"><link name="pitch"><sensor name="camera" type="camera"><pose>0 0 0 1 2 3</pose><topic>/shared</topic><camera/><plugin name="GstCameraPlugin"/></sensor></link></model></sdf>')
            model=root/'model.sdf';model.write_text('<sdf><model name="copter"><include><uri>'+str(child)+'</uri><name>gimbal</name></include></model></sdf>')
            p=dict(kind='copter',entity_name='CopterB',model_path=model,fingerprint='base')
            result=assemble(resource_root(),root,p,'WorldB');camera=result['cameras'][0]
            self.assertEqual(camera['original_topic'],'/shared');self.assertEqual(camera['removed_plugins'],['GstCameraPlugin'])
            self.assertIn('/WorldB/CopterB/gimbal-camera/image',camera['topic']);self.assertIn('0 0 0 1 2 3',camera['source_configuration'])

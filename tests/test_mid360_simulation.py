"""Synthetic contract/ownership fixtures, NOT native MID-360/GUI acceptance."""
from copy import deepcopy
import json
import math
from pathlib import Path
import sqlite3
import struct
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.simulation.mid360_assembly import assemble
from vehicle_autonomy.app.simulation.mid360_tools import Mid360Tools, DomainLease, recover_center_recordings
from vehicle_autonomy.app.simulation.manager import SimulationManager
from vehicle_autonomy.world.sensors.lidar.mid360_data import convert, POINT_STEP, fresh
from vehicle_autonomy.world.sensors.lidar.mid360_probe import health

ROOT=resource_root()


def cloud(endian='<'):
    return Obj(width=2,height=1,point_step=16,row_step=36,is_bigendian=endian=='>',
        header=Obj(stamp=Obj(sec=42,nsec=12345)),
        field=[Obj(name=n,offset=i*4,datatype=6,count=1) for i,n in enumerate(('x','y','z','intensity'))],
        data=struct.pack(endian+'ffffffff',1.,2.,3.,7.,float('inf'),0.,0.,0.)+b'pad!')


class Mid360CloudTests(unittest.TestCase):
    def test_packed_cloud_bytes_are_materialized_once_per_frame(self):
        source=cloud();reads=[]
        class Packed:
            def __getattr__(self,name):return getattr(source,name)
            @property
            def data(self):reads.append(True);return memoryview(source.data).tobytes()
        convert(Packed())
        self.assertEqual(len(reads),1)

    def test_gazebo_enum_endian_row_padding_and_capture_time(self):
        for endian in ('<','>'):
            data,meta=convert(cloud(endian))
            self.assertEqual(meta['points'],1)
            self.assertEqual(len(data),POINT_STEP)
            values=struct.unpack('<fffffH2xfId',data)
            self.assertEqual(values[:4],(1.,2.,3.,7.))
            self.assertAlmostEqual(values[4],math.sqrt(14),places=6)
            self.assertEqual(values[-3:],(0.,0,42_000_012_345.))
            self.assertEqual(meta['stamp_ns'],42_000_012_345)

    def test_does_not_invent_intensity_when_unavailable(self):
        m=cloud();m.field.pop()
        data,meta=convert(m)
        self.assertFalse(meta['intensity_available'])
        self.assertEqual(struct.unpack_from('<f',data,12)[0],0.)

    def test_rejects_malformed_layout_and_ros_enum_in_gazebo_input(self):
        for key,value in [('width',0),('row_step',1),('data',b''),('point_step',3),('height',999)]:
            m=cloud();setattr(m,key,value)
            with self.assertRaises(ValueError):convert(m)
        for changes in ({'offset':16},{'count':2},{'datatype':7}):
            m=cloud()
            for key,value in changes.items():setattr(m.field[0],key,value)
            with self.assertRaises(ValueError):convert(m)

    def test_stale_future_corrupt_health_is_never_ready(self):
        with TemporaryDirectory() as directory:
            p=Path(directory)/'health.json'
            for value in ([1],{'online':True,'received_ns':'bad'},
                          {'online':True,'received_ns':time.monotonic_ns()-2_000_000_000},
                          {'online':True,'received_ns':time.monotonic_ns()+2_000_000_000}):
                p.write_text(json.dumps(value));self.assertFalse(health(p))
            p.write_text(json.dumps(dict(online=True,received_ns=time.monotonic_ns())))
            self.assertTrue(health(p))
        self.assertFalse(fresh(None,1))
        self.assertFalse(fresh('broken',1))


class Mid360AssemblyTests(unittest.TestCase):
    def prepared(self,directory,kind):
        directory.mkdir()
        path=directory/'model.sdf'
        model=ET.Element('sdf',version='1.9');m=ET.SubElement(model,'model',name='fixture')
        if kind=='copter':
            child=directory/'iris_with_standoffs';child.mkdir()
            include=ET.SubElement(m,'include');ET.SubElement(include,'uri').text=str(child/'model.sdf')
            include_root=ET.Element('sdf',version='1.9');base=ET.SubElement(include_root,'model',name='iris_with_standoffs')
            ET.SubElement(base,'link',name='base_link')
            ET.ElementTree(include_root).write(child/'model.sdf')
        else:
            link=ET.SubElement(m,'link',name='base_link')
            ET.SubElement(link,'pose').text='0 0 0.19 0 0 0'
            ET.SubElement(ET.SubElement(link,'inertial'),'mass').text='6'
        ET.SubElement(m,'plugin',name='ArduPilotPlugin',filename='fixture_untouched')
        ET.ElementTree(model).write(path)
        return dict(kind=kind,model_path=path,entity_name='vaf_fixture_'+kind,
                    fingerprint='immutable-base',prepared_model_hash='prior-camera-hash')

    def test_common_component_two_actual_mount_chains_and_unchanged_dynamics(self):
        with TemporaryDirectory() as directory:
            for kind,z in [('rover',.19),('copter',0.)]:
                d=Path(directory)/kind;p=self.prepared(d,kind)
                original=ET.tostring(ET.parse(p['model_path']).find('.//plugin'))
                result=assemble(ROOT,d,p,'unit_world')
                changed=ET.parse(d/result['modified_file'])
                self.assertEqual(result['model_to_body'],[0.,0.,z])
                self.assertEqual(changed.findtext('.//sensor[@name="mid360"]/lidar/scan/horizontal/samples'),'720')
                self.assertEqual(changed.findtext('.//sensor[@name="mid360"]/lidar/scan/vertical/samples'),'28')
                self.assertEqual(changed.findtext('.//sensor[@name="mid360_imu"]/update_rate'),'200')
                self.assertAlmostEqual(float(changed.findtext('.//vertical/min_angle'))*180/math.pi,-7.)
                self.assertAlmostEqual(float(changed.findtext('.//vertical/max_angle'))*180/math.pi,52.)
                self.assertEqual(ET.tostring(ET.parse(p['model_path']).find('.//plugin')),original)
                self.assertEqual(p['pre_mid360_prepared_hash'],'prior-camera-hash')
                self.assertIn('snapshot',result['backend'])
                self.assertEqual(result['points_gz'],result['namespace']+'/gz_scan/points')
                with self.assertRaises(ValueError):assemble(ROOT,d,p,'unit_world')

    def test_rejects_external_model_mutation_and_unsupported_vehicle(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);p=self.prepared(root/'source','rover');owned=root/'owned';owned.mkdir()
            with self.assertRaises(ValueError):assemble(ROOT,owned,p,'unit_world')
            p['kind']='plane'
            with self.assertRaises(ValueError):assemble(ROOT,owned,p,'unit_world')

    def test_model_snapshot_is_separately_attested(self):
        with TemporaryDirectory() as directory:
            p=self.prepared(Path(directory)/'vehicle','rover')
            result=assemble(ROOT,Path(directory)/'vehicle',p,'unit_world')
            self.assertNotEqual(result['before_sha256'],result['after_sha256'])
            self.assertEqual(result['base_fingerprint'],'immutable-base')
            self.assertEqual(len(result['recipe_sha256']),64)


class Mid360LifecycleTests(unittest.TestCase):
    def test_world_shutdown_closes_reopened_tools_of_removed_vehicle(self):
        from unittest.mock import Mock
        manager=SimulationManager.__new__(SimulationManager)
        retired,active,other=Mock(),Mock(),Mock()
        manager._owners_closed=set();manager._cancel=Mock()
        manager.mid360_services={'removed':('world',retired),'active':('world',active),'other':('other-world',other)}
        owner=Mock(vehicles={'active':object()})
        self.assertEqual(manager._cleanup_owner('world',owner),[])
        retired.close.assert_called_once();active.close.assert_not_called();other.close.assert_not_called()
        owner.close.assert_called_once()

    def test_center_summary_reads_the_selected_sensor_owner_instead_of_unrelated_rviz(self):
        from threading import Event,RLock
        from vehicle_autonomy.app.control_center.service import ControlCenter
        center=ControlCenter.__new__(ControlCenter)
        center.bindings={'rviz2':{'mid360_vehicle':'vehicle-unit'}}
        owned=Obj(lock=RLock(),instances={'rviz2':{'ready':True,'state':'READY'}})
        sensor=Obj(tools=owned)
        center.application=Obj(simulation_manager=Obj(mid360_services={'vehicle-unit':('world',sensor)}))
        center.host={'tools':{'rviz2':{'installed':True}},'ros_error':None,'desktop':{'available':True}}
        center.session_id='unit';center.stop=Event();center.lock=RLock();center.operation=None
        self.assertTrue(center.summary()['rviz2_ready'])
        sensor.tools=None
        self.assertEqual(center.summary()['rviz2_state'],'STOPPED')

    def test_domain_leases_isolate_instances_and_quarantine_unclean_exit(self):
        with TemporaryDirectory() as directory, patch.dict('os.environ',{'VAF_RUNTIME_ROOT':directory}):
            a,b=DomainLease(ROOT),DomainLease(ROOT)
            self.assertNotEqual(a.domain,b.domain)
            old=a.domain
            a.file.close();a.file=None  # simulate owner crash: no clean release marker
            c=DomainLease(ROOT)
            self.assertNotEqual(c.domain,old)
            b.close();c.close()

    def service(self,directory):
        child=Obj(id='vehicle-'+'a'*32,directory=Path(directory),target='simulation-unit',
                  owner=Obj(root=ROOT,partition='unit-only-no-Gazebo'))
        return Mid360Tools(child,dict(source='gazebo-live',kind='rover',namespace='/vaf/unit/sensors/mid360',
            backend='uniform-snapshot',limitations=[]))

    def test_live_replay_domains_and_all_tool_profiles_use_existing_supervisor(self):
        with TemporaryDirectory() as directory,patch.dict('os.environ',{'VAF_RUNTIME_ROOT':directory}):
            service=self.service(directory)
            self.assertNotEqual(service._ctx('live')['ros_domain_id'],service._ctx('replay')['ros_domain_id'])
            with patch('vehicle_autonomy.app.simulation.mid360_tools.ros_environment',return_value={}):
                service._ensure()
                self.assertEqual(set(service.tools.registry),{'mid360','rviz2','record','replay'})
                self.assertFalse(service.tools.check('record','default')['missing'])
                store=service.tools.store
            service.close()
            self.assertIsNone(store.lock_fd)
            self.assertIsNone(store.handler)

    def test_retired_instance_cannot_start_live_or_record_but_can_show_saved_bags(self):
        with TemporaryDirectory() as directory:
            service=self.service(directory);service.close()
            for action in ('sensor_start','record_start','fault_on','fault_off'):
                with self.assertRaises(ValueError):service.handle(action)
            self.assertFalse(service.snapshot()['online'])
            self.assertTrue(service.snapshot()['live_closed'])
            for bag in ('/tmp/arbitrary',[],True):
                with self.assertRaises(ValueError):service.handle('replay_start',bag_id=bag)

    def test_restarted_worker_cannot_inherit_previous_fresh_health(self):
        with TemporaryDirectory() as directory:
            service=self.service(directory)
            p=service.directory/'health.json'
            p.write_text(json.dumps(dict(online=True,received_ns=time.monotonic_ns())))
            with patch.object(service,'_launch',return_value={'state':'STARTING'}):
                service.start()
            self.assertFalse(p.exists())
            self.assertFalse(service.online())

    def test_record_complete_requires_all_real_message_streams(self):
        with TemporaryDirectory() as directory:
            service=self.service(directory);key='bag-'+'b'*32
            path=service.directory/'bags'/key;path.mkdir(parents=True)
            (path/'metadata.yaml').write_text('unit-only metadata marker')
            service.bags[key]=dict(id=key,path=str(path));service.recording=key
            service._finish_record()
            self.assertFalse(service.bags[key]['complete'])
            with sqlite3.connect(path/'fixture.db3') as connection:
                connection.executescript('CREATE TABLE topics(id INTEGER, name TEXT);CREATE TABLE messages(topic_id INTEGER);')
                for i,name in enumerate(('points','imu','tf','tf_static','robot_description','trajectory','status','/clock')):
                    topic=name if name.startswith('/') else service.config['namespace']+'/'+name
                    connection.execute('INSERT INTO topics VALUES(?,?)',(i,topic))
                    connection.execute('INSERT INTO messages VALUES(?)',(i,))
            service.recording=key;service._finish_record()
            self.assertTrue(service.bags[key]['complete'])
            restored=Mid360Tools.archive(ROOT,service.config_path,'simulation-unit')
            self.assertTrue(restored.live_closed)
            self.assertIsNone(restored.tools)
            self.assertEqual(restored.bags[key]['path'],str(path))

    def test_sensor_request_admission_rejects_hardware_and_unknown_fields(self):
        manager=SimulationManager.__new__(SimulationManager)
        for raw in ({'kind':'rover','sensors':{'mid360':1}},
                    {'kind':'plane','sensors':{'mid360':True}},
                    {'kind':'rover','sensors':{'physical_ip':'192.168.1.1'}},
                    {'kind':'rover','device':'/dev/ttyUSB0'}):
            with self.assertRaises(ValueError):manager._specifications('R01',[raw],{},0)

    def test_new_center_recovers_finalized_bags_without_adopting_vehicle_or_process(self):
        with TemporaryDirectory() as directory,patch.dict('os.environ',{'VAF_RUNTIME_ROOT':directory}):
            runtime=Path(directory);sid='sim-'+'b'*32;vid='vehicle-'+'a'*32;bag='bag-'+'c'*32
            prior=runtime/'sessions/control-center/cc-previous/application/simulation'/sid
            child=prior/vid;child.mkdir(parents=True)
            service=self.service(child)
            path=service.directory/'bags'/bag;path.mkdir(parents=True)
            (path/'metadata.yaml').write_text('fixture, not native evidence')
            (service.directory/'recordings.json').write_text(json.dumps({bag:dict(id=bag,complete=True,path='/untrusted/ignored')}))
            (prior/'report.json').write_text(json.dumps(dict(id=sid,state='RUNNING',vehicles=[dict(id=vid,target='old-target')],history=[])))
            manager=Obj(root=ROOT,directory=runtime/'sessions/control-center/cc-new/application/simulation',records={},mid360_services={})
            recover_center_recordings(manager)
            self.assertEqual(manager.records[sid]['state'],'FAILED')
            restored=manager.mid360_services[vid][1]
            self.assertTrue(restored.live_closed)
            self.assertIsNone(restored.tools)
            self.assertFalse(restored.contexts)
            self.assertEqual(restored.bags[bag]['path'],str(path))
            for action in ('sensor_start','record_start'):
                with self.assertRaises(ValueError):restored.handle(action)
            # A symlinked prior session is never a recording catalog input.
            manager.records.clear();manager.mid360_services.clear()
            (prior/'report.json').rename(prior/'real-report.json')
            (prior/'report.json').symlink_to(prior/'real-report.json')
            recover_center_recordings(manager)
            self.assertFalse(manager.records)

    def test_shutdown_cleanup_failure_retains_domain_fences(self):
        with TemporaryDirectory() as directory,patch.dict('os.environ',{'VAF_RUNTIME_ROOT':directory}):
            service=self.service(directory);service._ctx('live')
            from unittest.mock import Mock
            tools=Mock();tools.close.side_effect=RuntimeError('UNCONFIRMED')
            service.tools=tools
            with patch.object(service,'_finish_record'),self.assertRaises(RuntimeError):service.close()
            self.assertTrue(service.leases['live'].file)
            service.tools=None;service.close()


if __name__=='__main__':
    unittest.main()

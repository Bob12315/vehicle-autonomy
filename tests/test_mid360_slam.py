"""Timing/ownership contracts. These fixtures never count as native SLAM."""
import json,struct,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as Obj
from unittest.mock import patch

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.simulation.mid360_tools import Mid360Tools,DomainLease
from vehicle_autonomy.world.sensors.lidar.mid360_timed_data import convert_custom,packed_capture_times
from vehicle_autonomy.world.mapping.fast_lio_config import configure
from vehicle_autonomy.app.simulation.mid360_slam import Mid360Slam


def custom():
    return Obj(header=Obj(frame_id='mid360',stamp=Obj(sec=10,nanosec=100)),timebase=10_000_000_100,point_num=5,
        points=[Obj(x=1.,y=.1,z=.2,reflectivity=50,line=i%4,offset_time=i*20_000_000) for i in range(5)])


class TimedSensorContracts(unittest.TestCase):
    def test_view_requires_original_capture_transform_and_real_static_resource_alias(self):
        from vehicle_autonomy.app.simulation.lio_probe import transform_ready
        cfg=dict(frame_id='saved/map');stamp=object();calls=[]
        def available(parent,child,when):
            calls.append((parent,child,when));return child!='current/lidar'
        self.assertTrue(transform_ready(cfg,'saved/map/pcd_snapshot',stamp,available))
        self.assertEqual(calls,[('saved/map','saved/map/pcd_snapshot',stamp)])
        self.assertFalse(transform_ready(cfg,'saved/map/pcd_snapshot',stamp,lambda *_:False))
        self.assertFalse(transform_ready(cfg,'unqualified/frame',stamp,available))
        cfg=dict(sensor={},frames=dict(map='current/map',odom='current/odom',lidar='current/lidar'))
        self.assertFalse(transform_ready(cfg,'current/odom',stamp,available))
        self.assertTrue(transform_ready(cfg,'current/odom',stamp,lambda *_:True))

    def test_preserves_real_five_slice_times_without_assigning_firing_order(self):
        source=custom();data,meta=convert_custom(source,'mid360')
        self.assertEqual(meta['capture_offsets_ns'],[0,20_000_000,40_000_000,60_000_000,80_000_000])
        self.assertEqual(meta['end_stamp_ns'],10_080_000_100)
        for i in range(5):
            p=struct.unpack_from('<fffffH2xfId',data,i*40)
            self.assertEqual(p[-2],source.points[i].offset_time)
            self.assertEqual(p[-1],float(source.timebase+source.points[i].offset_time))
            self.assertAlmostEqual(p[-3],source.points[i].offset_time/1e9,places=7)

    def test_rejects_wrong_frame_timebase_line_order_and_nonfinite_returns(self):
        for key,value in (('timebase',9),('point_num',20001)):
            c=custom();setattr(c,key,value)
            with self.assertRaises(ValueError):convert_custom(c,'mid360')
        for key,value in (('line',4),('offset_time',-1),('offset_time',300_000_000),('x',float('nan'))):
            c=custom();setattr(c.points[2],key,value)
            with self.assertRaises(ValueError):convert_custom(c,'mid360')
        c=custom();c.points[-1].offset_time=1
        with self.assertRaises(ValueError):convert_custom(c,'mid360')
        with self.assertRaises(ValueError):convert_custom(custom(),'different-frame')

    def test_packed_audit_preserves_source_counts_and_rejects_timestamp_corruption(self):
        c=custom();c.points.insert(2,c.points[1]);c.point_num+=1
        data,_=convert_custom(c,'mid360')
        message=Obj(header=c.header,width=len(c.points),height=1,point_step=40,row_step=len(data),is_bigendian=False,
            data=data,fields=[Obj(name='offset_time',offset=28,datatype=6,count=1),Obj(name='timestamp',offset=32,datatype=8,count=1)])
        begin,times,counts=packed_capture_times(message,'mid360')
        self.assertEqual(begin,c.timebase);self.assertEqual(len(times),5)
        self.assertEqual(sum(counts.values()),c.point_num);self.assertEqual(counts[c.timebase+20_000_000],2)
        damaged=bytearray(data);struct.pack_into('<d',damaged,32,float(c.timebase+1));message.data=damaged
        with self.assertRaisesRegex(ValueError,'disagrees'):packed_capture_times(message,'mid360')
        message.data=data;message.fields[0].offset=24
        with self.assertRaisesRegex(ValueError,'missing'):packed_capture_times(message,'mid360')

    def test_gazebo_owned_context_domain_is_not_released_by_tool_shutdown(self):
        with TemporaryDirectory() as directory,patch.dict('os.environ',{'VAF_RUNTIME_ROOT':directory}):
            owner=Obj(root=resource_root(),partition='fixture',_timed_mid360_leases={})
            child=Obj(id='vehicle-fixture',target='simulation-fixture',directory=Path(directory),owner=owner)
            lease=DomainLease(resource_root())
            sensor=Mid360Tools(child,dict(source='gazebo-live',kind='rover',backend='livox-gz-sliced-pattern-v1',namespace='/fixture',limitations=[]),live_lease=lease)
            sensor.close()
            self.assertIs(owner._timed_mid360_leases[child.id],lease)
            self.assertIsNotNone(lease.file)
            contender=DomainLease(resource_root());self.assertNotEqual(contender.domain,lease.domain)
            contender.close();lease.close()

    def test_thresholds_are_fixed_independently_of_measured_results(self):
        rules=json.loads((resource_root()/'configs/mid360-slam-acceptance.json').read_text())
        self.assertEqual(rules['repetitions_per_vehicle'],3)
        self.assertTrue(rules['fixed_before_native_runs'])
        self.assertEqual(rules['sensor']['minimum_distinct_capture_times_per_scan'],5)

    def test_shared_core_uses_vehicle_surface_sampling_and_explicit_bound_topics(self):
        with TemporaryDirectory() as directory:
            for kind,voxel,map_voxel in (('rover',.3,.5),('copter',.15,.2)):
                root=Path(directory)/kind;root.mkdir()
                sensor=dict(kind=kind,backend='livox-gz-sliced-pattern-v1',mount=[0.]*6,imu_in_lidar=[0.]*6,namespace='/owned/'+kind)
                path,args,resolved=configure(resource_root(),sensor,root)
                self.assertEqual(resolved['filter_size_surf'],voxel)
                self.assertEqual(resolved['filter_size_map'],map_voxel)
                self.assertEqual(resolved['common']['lid_topic'],'/owned/'+kind+'/custom')
                self.assertEqual(json.loads(path.read_text())['/**']['ros__parameters'],resolved)
                self.assertIn('/tf:=/owned/'+kind+'/slam/algorithm_tf',args)

    def test_view_gap_does_not_delay_clock_or_process_fault_cleanup(self):
        from threading import RLock
        stopped=[]
        parent=Obj(tools=Obj(lock=RLock(),instances={}),_active=lambda key:key=='slam-rviz' and not stopped,_stop=stopped.append)
        service=Mid360Slam.__new__(Mid360Slam);service.parent=parent;service.started_at=1
        service.world=Obj(latched=None,raw={'revision':1});service.unavailable_since=None;service.rviz_mode='lio'
        service.viewer_error=None;service.viewer_events=[];service.pgo_directory=None
        state=dict(running=True,online=False,error='LIO output expired/uninitialized',state={},relocalization={})
        service.snapshot=lambda:state;service.stop=lambda:stopped.append('all dependencies')
        for now in (10.,10.8):
            with patch('vehicle_autonomy.app.simulation.mid360_slam.time.monotonic',return_value=now):service.supervise()
        self.assertEqual(stopped,[])
        with patch('vehicle_autonomy.app.simulation.mid360_slam.time.monotonic',return_value=11.1):service.supervise()
        self.assertEqual(stopped,['slam-rviz'])
        stopped.clear();service.unavailable_since=None;state['error']='simulation clock paused'
        with patch('vehicle_autonomy.app.simulation.mid360_slam.time.monotonic',return_value=20.):service.supervise()
        self.assertEqual(stopped,['slam-rviz'])
        stopped.clear();state['running']=False;service.supervise()
        self.assertEqual(stopped,['all dependencies'])

    def test_relocated_view_gap_preserves_only_window_not_pose_or_clock_fault(self):
        from threading import RLock
        stopped=[]
        parent=Obj(tools=Obj(lock=RLock(),instances={}),_active=lambda key:key=='slam-rviz' and not stopped,_stop=stopped.append)
        service=Mid360Slam.__new__(Mid360Slam);service.parent=parent;service.started_at=1
        service.world=Obj(latched=None,raw={'revision':1});service.unavailable_since=None
        service.relocation_unavailable_since=None;service.rviz_mode='relocated'
        service.viewer_error=None;service.viewer_events=[];service.pgo_directory=None
        state=dict(running=True,online=True,error=None,state={'relocation_tf':{'online':False}},relocalization={'online':False,'error':'capture expired'})
        service.snapshot=lambda:state
        for now in (10.,10.8):
            with patch('vehicle_autonomy.app.simulation.mid360_slam.time.monotonic',return_value=now):service.supervise()
        self.assertEqual(stopped,[])
        self.assertFalse(state['relocalization']['online']);self.assertFalse(state['state']['relocation_tf']['online'])
        with patch('vehicle_autonomy.app.simulation.mid360_slam.time.monotonic',return_value=11.1):service.supervise()
        self.assertEqual(stopped,['slam-rviz'])
        stopped.clear();service.relocation_unavailable_since=None;state['error']='simulation clock paused'
        with patch('vehicle_autonomy.app.simulation.mid360_slam.time.monotonic',return_value=20.):service.supervise()
        self.assertEqual(stopped,['slam-rviz'])


if __name__=='__main__':unittest.main()

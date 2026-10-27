"""First actual managed native Nav2 -> existing Rover Execution motion path."""
import argparse,json,math,os,time,hashlib
from pathlib import Path
from uuid import uuid4
from tests.simulation.launch import ROOT,install_signal_cleanup
from tests.simulation.phase5_sensors import SensorFixture
from tests.simulation.phase5_slam import start_slam,wait_native
from vehicle_autonomy.app.bootstrap.native_navigation_processes import NativeNavigationProcesses
from vehicle_autonomy.app.bootstrap.navigation_ownership import OwnedNavigationIdentity
from vehicle_autonomy.app.bootstrap.stream_collector import StreamCollector
from vehicle_autonomy.actions.navigation.native_rover import NativeRoverNavigationFactory,register_native_navigation
from vehicle_autonomy.contracts.streams import FrameDescriptor,DataKind
from vehicle_autonomy.engine.navigation.write_fence import NativeNavigationWriteFence
from vehicle_autonomy.world.sensors.stream_store import StreamReader
from vehicle_autonomy.world.mapping.grid import pose_from_json


def run(path):
    fence=NativeNavigationWriteFence();f=SensorFixture(path,source_time_sync=True,secure=True,native_input_fence=fence,contact_evidence=True);collector=None;report={'passed':False};factory=None
    os.environ['VAF_SLAM_BOUNDARY_LIBRARY']=str((ROOT/'artifacts/phase5-world-navigation/slam-boundary/libvaf_slam_boundary.so').resolve())
    binary=ROOT/'artifacts/phase5-world-navigation/source-receiver-qualified/vaf_native_source_receiver'
    os.environ['VAF_NATIVE_SOURCE_RECEIVER']=str(binary);os.environ['VAF_NATIVE_SOURCE_RECEIVER_SHA256']=hashlib.sha256(binary.read_bytes()).hexdigest()
    try:
        f.start();root=path/'native-world';root.mkdir(mode=0o700);map_epoch='map:'+uuid4().hex;source='slam:'+uuid4().hex
        config=dict(schema=1,directory=str(root),source_id=source,frame_epoch=f.sensor_config['frame_epoch'],map_epoch=map_epoch,calibration_version=f.sensor_config['calibration_version'],generation_clock_world=f.owned.world)
        profile=path/'native-world.json';profile.write_text(json.dumps(config))
        collector=StreamCollector(f.driver,root,source_id=source,origin_id=config['frame_epoch'],calibration_version=config['calibration_version'],frames={k:FrameDescriptor('map','ENU',map_epoch) for k in ('map','slam_pose','map_transform')},max_age_ns={'map':10_000_000_000,'slam_pose':500_000_000,'map_transform':500_000_000},poll_period_s=.01)
        f.ros_start('native-world',[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','vehicle_autonomy.world.mapping.slam_streams','--config',str(profile)],role='world_reader')
        start_slam(f,'slam',ROOT/'simulation/phase5/slam_mapping.yaml');state,_=wait_native(f,root)
        report['native_world_initial']=state
        reader=StreamReader(root/'payloads',slots=6,max_bytes=2_000_000)
        def pose_reader(w,epoch):
            matches=[s for s in w.streams if s.header.kind is DataKind.SLAM_POSE and s.header.source_id==source and s.header.frame.origin_id==epoch]
            if len(matches)!=1:raise ValueError('exact native World pose absent')
            return pose_from_json(json.loads(reader.load(matches[0].data))['pose'])
        identity=OwnedNavigationIdentity(f.driver.ownership);identity.provision()
        factory=NativeRoverNavigationFactory(identity,security_environment=f.security_environment,scan_source=f.sensor_config['source_id'],slam_source=source,pose_reader=pose_reader,clock=f.driver.clock,write_fence=fence,cohort_factory=NativeNavigationProcesses)
        register_native_navigation(f.lab.registry,factory)
        report['arm']=f.wait_action(f.action('Arm'));report['guided']=f.wait_action(f.action('SetMode',{'mode':'GUIDED'}))
        contacts=f.contacts.snapshot();assert contacts['frames']>0 and contacts['ground_pairs']>0 and contacts['unknown_pairs']==0 and not contacts['error'],'independent contact oracle not qualified: '+str(contacts)
        report['contacts_before_navigation']=contacts
        origin=f.truth();action=f.action('NavigateToPose',dict(x_m=1.5,y_m=0.,yaw_rad=0.,map_epoch=map_epoch),timeout_s=85)
        from collections import deque
        telemetry=deque(maxlen=4096);end=time.monotonic()+100;conflict_checked=False
        while time.monotonic()<end:
            f.truth();view=f.lab.runtime.view(action['id'])
            if not conflict_checked and view['state']=='RUNNING' and len(view['effects'])>=3:
                from urllib.error import HTTPError
                try:f.api('/api/manual/start',dict(name='Drive',target='rover',parameters={'speed_mps':.1},allow_send=True))
                except HTTPError as exc:
                    assert exc.code==409,'unexpected manual conflict response';report['web_manual_conflict']=dict(status=exc.code,response=exc.read().decode())
                else:raise AssertionError('Web manual motion bypassed native owner')
                denied=f.lab.runtime.submit('Drive','rover',dict(speed_mps=.1),allow_send=True)
                assert denied['state']=='REJECTED' and not denied['effects'],'engine control resource conflict was bypassed'
                report['engine_conflict']=denied
                report['concurrent_query']=f.wait_action(f.action('GetVehicleState'))
                assert not report['concurrent_query']['effects'] and f.driver.info()['scope']==action['id'],'read-only query changed vehicle ownership'
                assert len(list(identity.root.joinpath('native-navigation-jobs').iterdir()))==1,'second actual native job started'
                conflict_checked=True
            current=json.loads((root/'state.json').read_text());h=current['streams'].get('slam_pose',{}).get('header',{});now=time.monotonic_ns()
            telemetry.append(dict(at_ns=now,action_state=view['state'],native_source_ns=h.get('source_timestamp_ns'),native_age_ns=now-h['captured_at']['monotonic_ns'] if h else None,counts=current['counts'],queue_depths=current['queue_depths'],waiting=current['waiting'],error=current['error'],world_streams=[dict(kind=s.header.kind.value,age_ns=now-s.header.captured_at.monotonic_ns) for s in f.driver.snapshot().streams]))
            if view['state'] in ('SUCCEEDED','FAILED','UNKNOWN','TIMED_OUT','REJECTED','CANCELLED'):break
            time.sleep(.04)
        (path/'navigation-timing.json').write_text(json.dumps(list(telemetry),indent=2))
        report['contacts']=f.contacts.snapshot()
        report['action']=view;truth=f.truth();report['truth']=dict(x=truth.x_m,y=truth.y_m,yaw=truth.yaw_rad,speed=f.oracle.recent_speed_mps())
        report['physical_displacement_m']=math.hypot(truth.x_m-origin.x_m,truth.y_m-origin.y_m)
        assert conflict_checked,'real active-owner conflict and positive query controls were not exercised'
        assert report['contacts']['obstacle_pairs']==0 and not report['contacts']['error'],'actual physics collision'
        assert view['state']=='SUCCEEDED' and view['safety']['release_safe'],view['error']
        assert math.hypot(truth.x_m-1.5,truth.y_m)<=.75,'independent actual Gazebo goal error'
        assert f.oracle.recent_speed_mps()<=.1,'existing stopped-motion limit'
        assert report['physical_displacement_m']>=.8,'native Goal did not cause actual motion'
        assert not factory.resource_store.records(),'native resource occupation leaked'
        report['subsequent_native_mode']=f.wait_action(f.action('SetMode',{'mode':'GUIDED'}))
        report.update(passed=True,writer_calls=len(f.writer),effects=len(view['effects']))
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc)
        report['contacts']=f.contacts.snapshot() if f.contacts else None
        report['write_fence']=dict(rejected=fence.rejected,last_rejection=fence.last_rejection)
        report['collector_errors']=list(collector.errors) if collector else []
        report['sensor_collector_errors']=list(f.collector.errors) if f.collector else []
        report['failure_driver']=f.driver.info() if f.driver else None
        for label,file in (('failure_native_world',path/'native-world/state.json'),('failure_sensors',path/'streams/state.json')):
            if file.exists():report[label]=json.loads(file.read_text())
        if f.driver and f.driver.snapshot():
            from vehicle_autonomy.contracts.core.serialization import to_json_value
            report['failure_world']=to_json_value(f.driver.snapshot())
        raise
    finally:
        if collector:collector.close()
        try:f.close()
        finally:
            from pymavlink.dialects.v20 import ardupilotmega as mav
            types={}
            for frame in f.writer:
                for message in mav.MAVLink(None).parse_buffer(bytes.fromhex(frame['raw_hex'])) or []:types[message.get_type()]=types.get(message.get_type(),0)+1
            report['actual_writer']=dict(total=len(f.writer),message_types=types,control=sum(n for name,n in types.items() if name!='TIMESYNC'))
            (path/'actual-writer.json').write_text(json.dumps(f.writer,indent=2))
            (path/'summary.json').write_text(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args();install_signal_cleanup();print(run(a.run_dir.resolve())['passed'],flush=True)

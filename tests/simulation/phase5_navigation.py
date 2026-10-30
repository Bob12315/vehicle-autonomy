"""First actual managed native Nav2 -> existing Rover Execution motion path."""
import argparse,json,math,os,time,hashlib
from pathlib import Path
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
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


def run(path,scenario='reach'):
    if scenario not in ('reach','cancel','bridge_loss','nav2_crash','lidar_loss','localization_loss','no_path','static_obstacle'):raise ValueError('explicit qualified scenario required')
    fence=NativeNavigationWriteFence();f=SensorFixture(path,source_time_sync=True,secure=True,native_input_fence=fence,contact_evidence=True,split_lidar_bridge=True);collector=None;report={'passed':False,'scenario':scenario};factory=None
    os.environ['VAF_SLAM_BOUNDARY_LIBRARY']=str((HostEnvironment(ROOT).path('slam_boundary_library')).resolve())
    binary=HostEnvironment(ROOT).path('native_source_receiver')
    os.environ['VAF_NATIVE_SOURCE_RECEIVER']=str(binary);os.environ['VAF_NATIVE_SOURCE_RECEIVER_SHA256']=hashlib.sha256(binary.read_bytes()).hexdigest()
    try:
        goal_x=0. if scenario=='static_obstacle' else 3. if scenario=='no_path' else 1.5
        if scenario=='no_path':
            from tests.simulation.phase5_nav_scene import no_path
            report['scene']=no_path(f.owned)
        if scenario=='static_obstacle':
            from tests.simulation.phase5_nav_scene import static_obstacle
            report['scene']=static_obstacle(f.owned);report['scene']['goal_x_m']=goal_x
        report['world_sdf_sha256']=hashlib.sha256(f.owned.world_path.read_bytes()).hexdigest()
        from tests.simulation.phase5_inputs import freeze
        report['frozen_inputs_sha256']=freeze(path/'source-inputs.json')
        f.start();root=path/'native-world';root.mkdir(mode=0o700);map_epoch='map:'+uuid4().hex;source='slam:'+uuid4().hex
        config=dict(schema=1,directory=str(root),source_id=source,frame_epoch=f.sensor_config['frame_epoch'],map_epoch=map_epoch,calibration_version=f.sensor_config['calibration_version'],generation_clock_world=f.owned.world)
        profile=path/'native-world.json';profile.write_text(json.dumps(config))
        collector=StreamCollector(f.driver,root,source_id=source,origin_id=config['frame_epoch'],calibration_version=config['calibration_version'],frames={k:FrameDescriptor('map','ENU',map_epoch) for k in ('map','slam_pose','map_transform')},max_age_ns={'map':10_000_000_000,'slam_pose':500_000_000,'map_transform':500_000_000},poll_period_s=.01)
        native_reader=f.ros_start('native-world',[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','vehicle_autonomy.world.mapping.slam_streams','--config',str(profile)],role='world_reader')
        mapping_profile=ROOT/'simulation/phase5/slam_mapping.yaml'
        if scenario=='static_obstacle':
            # Bound redundant stationary graph growth during the mapping survey.
            # Localization below uses the original 0.1 s processing interval;
            # every existing World/Writer freshness limit remains unchanged.
            mapping_profile=path/'survey_mapping.yaml'
            mapping_profile.write_text((ROOT/'simulation/phase5/slam_mapping.yaml').read_text().replace('minimum_time_interval: 0.1','minimum_time_interval: 0.4'))
            report['survey_mapping_profile_sha256']=hashlib.sha256(mapping_profile.read_bytes()).hexdigest()
        slam_process=start_slam(f,'slam',mapping_profile);state,_=wait_native(f,root)
        report['native_world_initial']=state
        reader=StreamReader(root/'payloads',slots=6,max_bytes=2_000_000)
        def pose_reader(w,epoch):
            matches=[s for s in w.streams if s.header.kind is DataKind.SLAM_POSE and s.header.source_id==source and s.header.frame.origin_id==epoch]
            if len(matches)!=1:raise ValueError('exact native World pose absent')
            return pose_from_json(json.loads(reader.load(matches[0].data))['pose'])
        if scenario=='static_obstacle':
            report['arm']=f.wait_action(f.action('Arm'));report['guided']=f.wait_action(f.action('SetMode',{'mode':'GUIDED'}))
            report['mapping_survey']=[]
            # Explicit user-style mapping route, using ONLY existing AP Actions
            # and signed AP feedback. Gazebo truth is a test oracle, not a target
            # generator or SLAM map/localization input.
            for x,y in ((0.,-2.2),(2.5,-1.8)):
                f.wait_action(f.action('SetMode',{'mode':'GUIDED'}))
                report['mapping_survey'].append(f.wait_action(f.action('Goto',dict(x_m=x,y_m=y,z_m=0.))))
                assert f.contacts.snapshot()['obstacle_pairs']==0,'mapping survey collided'
            from tests.simulation.phase5_slam import read_maps
            state,values=wait_native(f,root);mapping_pose=pose_from_json(values['slam_pose']['pose'])
            directory=path/'maps';directory.mkdir(mode=0o700)
            saver=f.ros_start('native-map-save',[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','vehicle_autonomy.app.bootstrap.slam_storage','--directory',str(directory),'--name','survey','--result',str(path/'native-map-save.json')],role='manager',transient=True)
            try:code=saver.wait(timeout=35)
            finally:f.owned.stop_process(saver)
            report['saved_native_map']=json.loads((path/'native-map-save.json').read_text());assert code==0 and report['saved_native_map']['state']=='SUCCEEDED','actual native map save failed'
            f.owned.stop_process(slam_process);f.owned.stop_process(native_reader);collector.close()
            source='slam:'+uuid4().hex;root=path/'native-localization';root.mkdir(mode=0o700)
            config.update(directory=str(root),source_id=source);profile=path/'native-localization.json';profile.write_text(json.dumps(config))
            collector=StreamCollector(f.driver,root,source_id=source,origin_id=config['frame_epoch'],calibration_version=config['calibration_version'],frames={k:FrameDescriptor('map','ENU',map_epoch) for k in ('map','slam_pose','map_transform')},max_age_ns={'map':10_000_000_000,'slam_pose':500_000_000,'map_transform':500_000_000},poll_period_s=.01)
            native_reader=f.ros_start('native-localization',[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/python3','-m','vehicle_autonomy.world.mapping.slam_streams','--config',str(profile)],role='world_reader')
            q=mapping_pose.orientation;angle=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
            localization=path/'slam_localization.yaml';settings=(ROOT/'simulation/phase5/slam_mapping.yaml').read_text().replace('    mode: mapping','    mode: localization')
            localization.write_text(settings+'    do_loop_closing: false\n    map_file_name: '+str(directory/'survey')+'\n    map_start_pose: '+json.dumps([mapping_pose.position.x,mapping_pose.position.y,angle])+'\n')
            slam_process=start_slam(f,'localization',localization);report['loaded_native_localization'],_=wait_native(f,root)
            f.wait_action(f.action('SetMode',{'mode':'GUIDED'}))
            reader=StreamReader(root/'payloads',slots=6,max_bytes=2_000_000)
        identity=OwnedNavigationIdentity(f.driver.ownership);identity.provision()
        factory=NativeRoverNavigationFactory(identity,security_environment=f.security_environment,scan_source=f.sensor_config['source_id'],slam_source=source,pose_reader=pose_reader,clock=f.driver.clock,write_fence=fence,cohort_factory=NativeNavigationProcesses)
        register_native_navigation(f.lab.registry,factory)
        if scenario!='static_obstacle':
            report['arm']=f.wait_action(f.action('Arm'));report['guided']=f.wait_action(f.action('SetMode',{'mode':'GUIDED'}))
        contacts=f.contacts.snapshot();assert contacts['frames']>0 and contacts['ground_pairs']>0 and contacts['unknown_pairs']==0 and not contacts['error'],'independent contact oracle not qualified: '+str(contacts)
        report['contacts_before_navigation']=contacts
        origin=f.truth()
        if scenario=='static_obstacle':
            scene=report['scene'];line_clearance=min(math.hypot(max(abs(origin.x_m*(1-t)-scene['x_m'])-scene['size_x_m']/2,0.),max(abs(origin.y_m*(1-t)-scene['y_m'])-scene['size_y_m']/2,0.))-.75 for t in (i/1000 for i in range(1001)))
            report['straight_line_clearance_m']=line_clearance
            assert line_clearance<0,'scene does not require a physical detour with the conservative body bound'
        action=f.action('NavigateToPose',dict(x_m=goal_x,y_m=0.,yaw_rad=0.,map_epoch=map_epoch),timeout_s=85)
        from collections import deque
        telemetry=deque(maxlen=4096);end=time.monotonic()+100;conflict_checked=False;injected=False;closed_at=None;max_lateral=0.;min_clearance=float('inf')
        while time.monotonic()<end:
            sample=f.truth();view=f.lab.runtime.view(action['id'])
            max_lateral=max(max_lateral,abs(sample.y_m-origin.y_m))
            if scenario=='static_obstacle':
                scene=report['scene'];dx=max(abs(sample.x_m-scene['x_m'])-scene['size_x_m']/2,0.);dy=max(abs(sample.y_m-scene['y_m'])-scene['size_y_m']/2,0.)
                min_clearance=min(min_clearance,math.hypot(dx,dy)-.75)
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
            if scenario not in ('reach','no_path','static_obstacle') and not injected and conflict_checked and view['state']=='RUNNING' and f.oracle.recent_speed_mps()>=.1 and math.hypot(f.truth().x_m-origin.x_m,f.truth().y_m-origin.y_m)>=.05:
                report['fault']=dict(scenario=scenario,at_ns=time.monotonic_ns(),writer_index=len(f.writer))
                if scenario=='cancel':report['cancel_response']=f.api('/api/cancel',{'id':action['id']})
                elif scenario in ('lidar_loss','localization_loss'):
                    process=f.lidar_bridge if scenario=='lidar_loss' else slam_process
                    assert process is not None and process.poll() is None,'actual owned source process not running'
                    f.owned.stop_process(process)
                    report['fault']['stopped_source_pid']=process.pid
                else:
                    import signal
                    from vehicle_autonomy.engine.action.durable import DurableRecord
                    jobs=list((identity.root/'native-navigation-jobs').iterdir());assert len(jobs)==1
                    records=DurableRecord(jobs[0]/'cohort/processes.json').read()['processes']
                    name='native-source-receiver' if scenario=='bridge_loss' else 'controller_server'
                    record,=[r for r in records if r['name']==name]
                    pid=record['pid'];fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
                    assert fields[19]==record['start_ticks'] and os.getpgid(pid)==record['pgid'],'fault target process ownership changed'
                    os.killpg(record['pgid'],signal.SIGSTOP if scenario=='bridge_loss' else signal.SIGKILL)
                    report['fault']['process']=record
                injected=True
            if injected and scenario=='bridge_loss' and not report.get('held_stopped_producer'):
                record=report['fault']['process'];proc=Path(f"/proc/{record['pid']}/stat")
                if proc.exists() and proc.read_text().rsplit(')',1)[1].split()[0]=='T':
                    claims=factory.resource_store.records()
                    assert any(r['owner']==action['id'] for r in claims),'live stopped producer lost its durable resource occupation'
                    report['held_stopped_producer']=dict(at_ns=time.monotonic_ns(),pid=record['pid'],claims=claims)
            if injected and closed_at is None and fence._closed:closed_at=time.monotonic_ns()
            current=json.loads((root/'state.json').read_text());h=current['streams'].get('slam_pose',{}).get('header',{});now=time.monotonic_ns()
            telemetry.append(dict(at_ns=now,action_state=view['state'],native_source_ns=h.get('source_timestamp_ns'),native_age_ns=now-h['captured_at']['monotonic_ns'] if h else None,counts=current['counts'],queue_depths=current['queue_depths'],waiting=current['waiting'],error=current['error'],world_streams=[dict(kind=s.header.kind.value,age_ns=now-s.header.captured_at.monotonic_ns) for s in f.driver.snapshot().streams]))
            if view['state'] in ('SUCCEEDED','FAILED','UNKNOWN','TIMED_OUT','REJECTED','CANCELLED'):break
            time.sleep(.04)
        (path/'navigation-timing.json').write_text(json.dumps(list(telemetry),indent=2))
        report['contacts']=f.contacts.snapshot()
        report['action']=view;truth=f.truth();report['truth']=dict(x=truth.x_m,y=truth.y_m,yaw=truth.yaw_rad,speed=f.oracle.recent_speed_mps())
        report['physical_displacement_m']=math.hypot(truth.x_m-origin.x_m,truth.y_m-origin.y_m)
        jobs=list((identity.root/'native-navigation-jobs').iterdir());assert len(jobs)==1
        native_terminal=json.loads((jobs[0]/'terminal.json').read_text());report['native_terminal']=native_terminal
        cut=native_terminal.get('active_source_admission_ns')
        if cut is not None:
            from pymavlink.dialects.v20 import ardupilotmega as mav
            created=action['history'][0]['at_ns']
            preparation_frames=[m for row in f.writer if created<=row['host_ns']<cut for m in mav.MAVLink(None).parse_buffer(bytes.fromhex(row['raw_hex'])) or []]
            assert all(m.get_type()=='TIMESYNC' for m in preparation_frames),'preparation produced an actual vehicle control write'
            assert native_terminal['preparation_channel']['control_eligible'] is False,'channel proof acquired control eligibility'
            report['preparation_actual_control_writes']=0
        if scenario!='no_path':assert conflict_checked,'real active-owner conflict and positive query controls were not exercised'
        assert report['contacts']['obstacle_pairs']==0 and not report['contacts']['error'],'actual physics collision'
        expected='SUCCEEDED' if scenario in ('reach','static_obstacle') else 'CANCELLED' if scenario=='cancel' else 'FAILED'
        assert view['state']==expected and view['safety']['release_safe'],view['error']
        assert f.oracle.recent_speed_mps()<=.1,'existing stopped-motion limit'
        if scenario in ('reach','static_obstacle'):
            assert math.hypot(truth.x_m-goal_x,truth.y_m)<=.75,'independent actual Gazebo goal error'
            assert report['physical_displacement_m']>=.8,'native Goal did not cause actual motion'
            if scenario=='static_obstacle':
                report['physical_obstacle_clearance']=dict(conservative_body_radius_m=.75,min_clearance_m=min_clearance,max_lateral_excursion_m=max_lateral)
                assert min_clearance>0,'conservative physical footprint intersects known box'
                assert max_lateral>=.8,'vehicle did not physically detour around the real obstacle'
        elif scenario=='no_path':
            from pymavlink.dialects.v20 import ardupilotmega as mav
            jobs=list((identity.root/'native-navigation-jobs').iterdir());assert len(jobs)==1
            native=json.loads((jobs[0]/'terminal.json').read_text());report['native_no_path_result']=native
            assert native['state']=='FAILED' and native['native_status']==6,'unreachable path must be a real native ABORT, not a client timeout'
            frames=[m for row in f.writer for m in mav.MAVLink(None).parse_buffer(bytes.fromhex(row['raw_hex'])) or []]
            assert all(abs(m.vx)+abs(m.vy)+abs(m.vz)+abs(m.yaw_rate)<1e-9 for m in frames if m.get_type()=='SET_POSITION_TARGET_LOCAL_NED'),'unreachable path caused actual nonzero Writer motion'
            assert report['physical_displacement_m']<=.05,'unreachable path caused actual vehicle movement'
        else:
            from pymavlink.dialects.v20 import ardupilotmega as mav
            assert injected and closed_at is not None,'fault was not injected during actual motion or source not fenced'
            if scenario=='bridge_loss':assert report.get('held_stopped_producer'),'stopped-producer resource barrier was not observed'
            if 'process' in report['fault']:
                from vehicle_autonomy.app.bootstrap.native_navigation_processes import group_exists
                assert not group_exists(report['fault']['process']['pgid']),'owned failed producer process group remains live after terminal release'
            report['source_closed_at_ns']=closed_at
            later=[r for r in f.writer if r['host_ns']>=closed_at]
            frames=[m for r in later for m in mav.MAVLink(None).parse_buffer(bytes.fromhex(r['raw_hex'])) or []]
            motion=[m for m in frames if m.get_type()=='SET_POSITION_TARGET_LOCAL_NED']
            assert all(abs(m.vx)+abs(m.vy)+abs(m.vz)+abs(m.yaw_rate)<1e-9 for m in motion),'nonzero frame written after confirmed source closure'
            all_after=[m for r in f.writer if r['host_ns']>=report['fault']['at_ns'] for m in mav.MAVLink(None).parse_buffer(bytes.fromhex(r['raw_hex'])) or []]
            actual_stop=[m for m in all_after if m.get_type()=='SET_POSITION_TARGET_LOCAL_NED' and abs(m.vx)+abs(m.vy)+abs(m.vz)+abs(m.yaw_rate)<1e-9]
            assert actual_stop,'physical stop had no actual zero-setpoint Writer evidence'
            report['actual_stop_writer_calls']=len(actual_stop)
            report['post_closure_writer']=dict(total=len(later),nonzero_motion=0,zero_motion=len(motion))
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
            from tests.simulation.phase5_inputs import unchanged
            report['frozen_inputs_unchanged']=unchanged(path/'source-inputs.json') if (path/'source-inputs.json').exists() else False
            if not report['frozen_inputs_unchanged']:report.update(passed=False,error=report.get('error') or 'code/test/config inputs changed during run')
            report['actual_writer']=dict(total=len(f.writer),message_types=types,control=sum(n for name,n in types.items() if name!='TIMESYNC'))
            (path/'actual-writer.json').write_text(json.dumps(f.writer,indent=2))
            (path/'summary.json').write_text(json.dumps(report,indent=2))
    if not report['passed']:raise AssertionError(report.get('error'))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--scenario',choices=('reach','cancel','bridge_loss','nav2_crash','lidar_loss','localization_loss','no_path','static_obstacle'),default='reach');a=p.parse_args();install_signal_cleanup();print(run(a.run_dir.resolve(),a.scenario)['passed'],flush=True)

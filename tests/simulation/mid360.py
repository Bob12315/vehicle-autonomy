"""Real SITL/Gazebo/ROS/RViz acceptance. Never touches physical transports.

Preflight failures leave native checks NOT TESTED, never synthetic PASS.
Example: .venv/bin/python -m tests.simulation.mid360 --run-dir artifacts/mid360-native --allow-send --gui
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
from uuid import uuid4

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from vehicle_autonomy.app.control_center.desktop import diagnostic, windows

ROOT=resource_root()
CHECKS=('rover_cloud_tf_imu','copter_cloud_tf_imu','rover_motion','copter_motion',
        'gazebo_gui','rover_rviz_gui','copter_rviz_gui','rover_record_replay','copter_record_replay',
        'rover_fault_recovery','copter_fault_recovery','worker_exit_cleanup',
        'simulation_cleanup','camera_regression','rs16_native_regression','disabled_mid360_regression',
        'multi_instance_isolation','single_instance_stop','retired_recording_replay','backend_recording_recovery',
        'rover_rviz_reopen','copter_rviz_reopen','rover_moving_cloud_tf','copter_moving_cloud_tf','process_port_cleanup')


def remaining_owned(directory,partition):
    excluded={os.getpid()};pid=os.getppid()
    while pid>1:
        excluded.add(pid)
        try:pid=int(Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[1])
        except (OSError,ValueError,IndexError):break
    result=[];prefix=str(directory).encode();tag=('GZ_PARTITION='+partition).encode() if partition else None
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit() or int(entry.name) in excluded:continue
        try:
            if entry.stat().st_uid!=os.getuid():continue
            args=(entry/'cmdline').read_bytes();environment=(entry/'environ').read_bytes().split(b'\0')
            cwd=(entry/'cwd').resolve()
            if prefix in args or cwd.is_relative_to(directory) or tag and tag in environment:
                result.append(dict(pid=int(entry.name),cwd=str(cwd),command=args.replace(b'\0',b' ').decode(errors='replace'),
                    state=(entry/'stat').read_text().rsplit(')',1)[1].split()[0]))
        except OSError:pass
    return result


def run(directory, *, allow_send=False, gui=False):
    directory=Path(directory).resolve()
    directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    result=dict(status='NOT TESTED',scope='owned localhost SITL/Gazebo only',
        checks={key:'NOT TESTED' for key in CHECKS},preflight={},errors=[])
    def save():
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
    try:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0))
        result['preflight']['loopback_sockets']='PASS'
    except OSError as exc:
        result['preflight']['loopback_sockets']='FAIL'
        result['errors'].append(str(exc))
    result['preflight']['desktop']=diagnostic()
    host=HostEnvironment(ROOT)
    result['preflight']['host']=host.report()
    command,env=host.ros_command([sys.executable,'-c',
        'import rclpy, rosbag2_py, tf2_ros; from gz.transport13 import Node; print("optional imports PASS")'])
    imported=subprocess.run(command,env=env,capture_output=True,text=True,timeout=20)
    (directory/'optional-imports.log').write_text(imported.stdout+imported.stderr)
    result['preflight']['optional_imports']='PASS' if imported.returncode==0 else 'FAIL'
    save()
    if result['preflight']['loopback_sockets']!='PASS' or imported.returncode:
        return result

    from tests.simulation.control_binding_native import Native
    from tests.simulation.oracle import GazeboTruthOracle
    from vehicle_autonomy.app.tools.builtins import make,profile
    n=None
    active_check=None
    try:
        n=Native(directory/'native')
        r=n.api('/api/simulation/create',dict(scene_id='L01',vehicles=[
            dict(kind='rover',spawn={'id':'center'},sensors={'mid360':True}),
            dict(kind='copter',spawn={'id':'north'},sensors={'mid360':True})],parameters={'obstacle_count':0}))
        n.api('/api/simulation/start',dict(id=r['id']))
        n.app.simulation_manager.wait_ready(r['id'],160)
        owner=n.app.simulation_manager.owners[r['id']]
        os.environ.update(GZ_PARTITION=owner.partition,GZ_IP='127.0.0.1')
        children=list(owner.vehicles.values())
        result['runtime']=dict(world_id=r['id'],world=owner.world,partition=owner.partition)
        def tool(sensor,action,**kwargs):
            return n.api('/api/simulation/mid360',dict(id=r['id'],vehicle_id=sensor.child.id,action=action,**kwargs))
        def probe(sensor,source):
            name='mid360-probe-'+uuid4().hex[:8]
            command=[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/env',
                'ROS_DOMAIN_ID='+str(sensor._ctx(source)['ros_domain_id']),'ROS_LOCALHOST_ONLY=1',sys.executable,
                '-m','vehicle_autonomy.world.sensors.lidar.mid360_probe','--config',str(sensor.config_path),'--timeout','8']
            if sensor.live_closed:
                checked=subprocess.run(command,capture_output=True,text=True,timeout=15)
                code,text=checked.returncode,checked.stdout+checked.stderr
            else:
                process=sensor.child.session.start(name,command,transient=True)
                code=process.wait(timeout=15)
                text=(sensor.child.directory/(name+'.log')).read_text()
            (directory/(sensor.config['kind']+'-'+source+'-probe.json')).write_text(text)
            assert code==0,text
        def sources_ready():
            states={c.vehicle:c.mid360.snapshot() for c in children}
            (directory/'source-readiness.json').write_text(json.dumps(states,indent=2,default=str))
            return all(s['online'] for s in states.values())
        n.wait(sources_ready,60)
        observers={}
        def start_observer(child,source):
            sensor=child.mid360;output=directory/(child.vehicle+'-'+source+'-observed.json')
            command=[str(ROOT/'scripts/with_ros2.sh'),'/bin/bash','-c',
                'export PYTHONPATH="$1${PYTHONPATH:+:$PYTHONPATH}"; shift; exec "$@"','vaf-test',str(ROOT),'/usr/bin/env',
                'ROS_DOMAIN_ID='+str(sensor._ctx(source)['ros_domain_id']),sys.executable,
                '-m','tests.simulation.mid360_observer','--config',str(sensor.config_path),'--output',str(output)]
            # The existing session owns this read-only collector too.
            observers[(child.id,source)]=(child.session.start('mid360-observer-'+source,command,transient=True),output)
        def observed(child,source):
            process,path=observers[(child.id,source)]
            if process.poll() is not None:raise RuntimeError('read-only ROS observer exited: '+str(path))
            try:return json.loads(path.read_text())
            except (OSError,ValueError):return {}
        def stop_observer(child,source):
            process,_=observers[(child.id,source)]
            if process.poll() is None:process.terminate();process.wait(timeout=10)
        for child in children:start_observer(child,'live')
        domains=[c.mid360._ctx('live')['ros_domain_id'] for c in children]
        assert len(set(domains))==len(domains)
        if gui and result['preflight']['desktop']['available']:
            active_check='gazebo_gui'
            sensor=children[0].mid360
            environment={k:v for k,v in owner.session.env.items() if k.startswith('GZ_') or k in
                ('HOME','USER','LANG','PATH','DISPLAY','XAUTHORITY','XDG_RUNTIME_DIR')}
            # Gazebo's distro GUI must not load the ROS vendor Qt/Gazebo ABI
            # inherited from this sensor Tool container.
            for key in ('LD_LIBRARY_PATH','PYTHONPATH'):
                environment[key]=owner.session.env.get(key,'')
            environment['QT_QPA_PLATFORM']='xcb'
            probe_spec=dict(argv=[sys.executable,'-m','vehicle_autonomy.app.control_center.desktop','--gazebo'],
                            contains=['"status": "READY"'],timeout_s=5)
            p=profile([host.executable('gazebo'),'sim','-g','-v3'],env=environment,
                      ready=probe_spec,health=probe_spec,timeout=90)
            sensor.tools.registry['gazebo-gui']=make('gazebo-gui','Native acceptance Gazebo GUI','gui',
                                                    {'default':p},permissions=['desktop'])
            sensor.tools.execute('launch','gazebo-gui','default',sensor._ctx('live'))
            from tests.visualization.desktop import goal
            def gui_pid():
                with sensor.tools.lock:pid=sensor.tools.instances['gazebo-gui']['pid']
                return pid if pid and windows([pid]) else None
            owned=n.wait(gui_pid,30)
            goal(owned,capture=directory/'gazebo-before-readiness.png',select=False)
            def rendered():
                state=sensor.snapshot()['tools'].get('gazebo-gui',{})
                (directory/'gazebo-readiness.json').write_text(json.dumps(state,indent=2))
                return state.get('ready')
            n.wait(rendered,100)
            goal(owned,capture=directory/'gazebo.png',select=False)
            result['checks'][active_check]='PASS'
        # Allow the existing AP estimator to qualify; this grants no SEND itself.
        time.sleep(45)
        for child in children:
            sensor=child.mid360;kind=child.vehicle
            active_check=kind+'_cloud_tf_imu'
            probe(sensor,'live')
            evidence=n.wait(lambda:(v if (v:=observed(child,'live')).get('valid_cloud_tf_cuts',0)>5 else None),20)
            assert not evidence['invalid'],evidence['invalid']
            assert evidence['clock_publishers']==1 and evidence['point_publishers']==1,evidence
            assert evidence['max_wall_hits']>30 and evidence['max_world_z']>3.5,evidence
            assert evidence['min_world_z']<.2 and 9.<evidence['imu']['acceleration_norm']<10.5,evidence
            assert evidence['imu']['frame']==sensor.config['lidar_frame']
            result[kind+'_ros_evidence']=evidence
            state=sensor.snapshot()
            assert state['health']['cloud']['points']>0
            assert state['health']['cloud']['timing']=='simultaneous_snapshot_zero_offsets'
            assert -7.5 <= state['health']['cloud']['elevation_min_deg'] <= 52.5
            assert -7.5 <= state['health']['cloud']['elevation_max_deg'] <= 52.5
            result[kind+'_initial']=state
            result['checks'][active_check]='PASS'
            active_check='camera_regression'
            source=next(iter(child.camera_sources.values()))
            n.wait(lambda:source.health()['online'],30)
            _,jpeg=source.packet();assert jpeg.startswith(b'\xff\xd8')
            result['checks'][active_check]='PASS'
            active_check=kind+'_record_replay'
            tool(sensor,'record_start')
            if gui and result['preflight']['desktop']['available']:
                active_check=kind+'_rviz_gui'
                tool(sensor,'rviz_start')
                n.wait(lambda:sensor.snapshot()['tools'].get('rviz2',{}).get('ready'),100)
                with sensor.tools.lock:record=sensor.tools.instances['rviz2'];pid=record['pid']
                visible=windows([pid]);assert visible
                from tests.visualization.desktop import goal
                goal(pid,capture=directory/(kind+'-rviz.png'),select=False)
                result[kind+'_windows']=visible
                result['checks'][active_check]='PASS'
                tool(sensor,'rviz_stop')
                old_pid=pid
                tool(sensor,'rviz_start')
                n.wait(lambda:sensor.snapshot()['tools'].get('rviz2',{}).get('ready'),100)
                with sensor.tools.lock:pid=sensor.tools.instances['rviz2']['pid']
                assert pid!=old_pid and not Path('/proc',str(old_pid)).exists() and sensor.online()
                result['checks'][kind+'_rviz_reopen']='PASS'
            if allow_send:
                active_check=kind+'_motion'
                oracle=GazeboTruthOracle(owner.world,child.model.name)
                n.oracles[child.target]=oracle
                first=oracle.wait_new(after_host_ns=time.monotonic_ns(),timeout_s=10)
                n.action(child.target,'SetMode',{'mode':'GUIDED'})
                n.action(child.target,'Arm')
                if kind=='rover':
                    n.drive(child.target,neutral=True)
                    n.action(child.target,'Disarm')
                else:
                    n.action(child.target,'Takeoff',{'height_m':2.})
                    takeoff=oracle.latest()
                    assert takeoff.z_m-first.z_m>1.3,('actual Copter height',first,takeoff)
                    state=child.driver.snapshot().vehicle.reported_pose.value.position
                    # Ordinary Copter Goto retains its audited 0..2 m envelope;
                    # takeoff overshoot must not be copied into an invalid goal.
                    n.action(child.target,'Goto',dict(x_m=state.x+1.,y_m=state.y,z_m=1.8))
                    moved=oracle.latest()
                    n.action(child.target,'Land',timeout=90)
                last=oracle.latest()
                assert max(abs(last.x_m-first.x_m),abs(last.y_m-first.y_m))>.3
                if kind=='copter':
                    assert abs(last.z_m-first.z_m)<.3,('actual landing height',first,last)
                    result['copter_flight']=dict(ground=first,takeoff=takeoff,moved=moved,landed=last)
                probe(sensor,'live')
                moving=observed(child,'live')
                assert moving['max_displacement_m']>.3 and moving['valid_cloud_tf_cuts']>evidence['valid_cloud_tf_cuts'],moving
                assert not moving['invalid'],moving['invalid']
                if gui:goal(pid,capture=directory/(kind+'-rviz-after-motion.png'),select=False)
                result['checks'][kind+'_moving_cloud_tf']='PASS'
                result[kind+'_motion']=dict(before=first,after=last,
                    writer=child.driver.info()['writer'],final_sensor=sensor.snapshot())
                result['checks'][active_check]='PASS'
            tool(sensor,'rviz_stop')
            time.sleep(3)
            active_check=kind+'_record_replay'
            bag=tool(sensor,'record_stop')['bags'][-1]
            assert bag['complete'],bag
            tool(sensor,'replay_start',bag_id=bag['id'])
            assert sensor._ctx('replay')['ros_domain_id']!=sensor._ctx('live')['ros_domain_id']
            probe(sensor,'replay')
            start_observer(child,'replay')
            replay=n.wait(lambda:(v if (v:=observed(child,'replay')).get('valid_cloud_tf_cuts',0)>5 and v.get('status',{}).get('source')=='rosbag2' else None),25)
            assert replay['clock_publishers']==1 and replay['point_publishers']==1 and not replay['invalid'],replay
            result[kind+'_replay_evidence']=replay
            if gui and result['preflight']['desktop']['available']:
                tool(sensor,'rviz_start',source='replay')
                n.wait(lambda:sensor.snapshot()['tools'].get('rviz2',{}).get('ready'),100)
                with sensor.tools.lock:pid=sensor.tools.instances['rviz2']['pid']
                goal(pid,capture=directory/(kind+'-replay.png'),select=False)
                tool(sensor,'rviz_stop')
            if kind=='rover':
                # Real recorded Gazebo input through the existing RS16 ROS
                # converter's explicit replay mode; no SDK/physical endpoint.
                cfg=json.loads((ROOT/'configs/rs16-scan.json').read_text());cfg['frame']=sensor.config['lidar_frame']
                cfg_path=directory/'rs16-replay.json';cfg_path.write_text(json.dumps(cfg))
                health_path=directory/'rs16-replay-health.json'
                command=[str(ROOT/'scripts/with_ros2.sh'),'/usr/bin/env',
                    'ROS_DOMAIN_ID='+str(sensor._ctx('replay')['ros_domain_id']),sys.executable,
                    '-m','vehicle_autonomy.world.sensors.lidar.rs16_scan','--replay','--topic',sensor.config['namespace']+'/points',
                    '--config',str(cfg_path),'--health-file',str(health_path)]
                rs=child.session.start('rs16-replay-regression',command,transient=True)
                try:
                    def rs_ready():
                        if rs.poll() is not None:raise RuntimeError('RS16 replay converter exited')
                        try:v=json.loads(health_path.read_text())
                        except (OSError,ValueError):return None
                        return v if v.get('accepted',0)>5 else None
                    result['rs16_replay_regression']=n.wait(rs_ready,20)
                    assert result['rs16_replay_regression']['control_eligible'] is False
                    scans=n.wait(lambda:(v if (v:=observed(child,'replay')).get('counts',{}).get('rs16_scan',0)>5 else None),20)
                    assert scans['rs16_scan']['frame']==sensor.config['lidar_frame'] and scans['rs16_scan']['bins']==720
                    assert scans['rs16_scan']['finite_bins']>0
                    result['rs16_scan_evidence']=scans['rs16_scan']
                    result['checks']['rs16_native_regression']='PASS'
                finally:rs.terminate();rs.wait(timeout=10)
            stop_observer(child,'replay')
            tool(sensor,'replay_stop')
            result['checks'][active_check]='PASS'
            active_check=kind+'_fault_recovery'
            tool(sensor,'fault_on')
            n.wait(lambda:not sensor.online(),5)
            count=sensor.snapshot()['health']['sequence']
            time.sleep(2)
            assert sensor.snapshot()['health']['sequence']==count
            assert observed(child,'live')['empty_clouds']>0 and observed(child,'live')['empty_paths']>0
            tool(sensor,'fault_off')
            n.wait(sensor.online,10)
            result['checks'][active_check]='PASS'
        active_check='worker_exit_cleanup'
        sensor=children[0].mid360
        tool(sensor,'record_start')
        if gui:
            tool(sensor,'rviz_start');n.wait(lambda:sensor.snapshot()['tools'].get('rviz2',{}).get('ready'),100)
            with sensor.tools.lock:dependent_pid=sensor.tools.instances['rviz2']['pid']
        with sensor.tools.lock:record=sensor.tools.instances['mid360'];pid=record['pid']
        # Explicitly owned process only; no discovered or recorded PID adoption.
        import signal
        os.kill(pid,signal.SIGKILL)
        n.wait(lambda:not sensor.online(),5)
        n.wait(lambda:sensor.source_fault_handled,20)
        assert sensor.recording is None and not sensor._active('record')
        if gui:assert not Path('/proc',str(dependent_pid)).exists()
        tool(sensor,'sensor_start');n.wait(sensor.online,30)
        result['checks'][active_check]='PASS'
        # Removing one live instance must not retire the other's point source.
        active_check='multi_instance_isolation'
        assert children[0].mid360.config['namespace']!=children[1].mid360.config['namespace']
        assert children[0].mid360.config['base_frame']!=children[1].mid360.config['base_frame']
        assert len(set(domains))==2 and all(c.mid360.online() for c in children)
        result['checks'][active_check]='PASS'
        active_check='single_instance_stop'
        stop_observer(children[0],'live')
        before=children[1].mid360.snapshot()['health']['sequence']
        n.api('/api/simulation/remove_vehicle',dict(id=r['id'],vehicle_id=children[0].id))
        operation=n.operation(r['id']);assert operation['operation']['state']=='SUCCEEDED',operation
        n.wait(lambda:children[1].mid360.online() and children[1].mid360.snapshot()['health']['sequence']>before+5,15)
        assert children[0].mid360.live_closed
        result['checks'][active_check]='PASS'
        active_check='retired_recording_replay'
        saved=next(b for b in children[0].mid360.bags.values() if b['complete'])
        tool(children[0].mid360,'replay_start',bag_id=saved['id']);probe(children[0].mid360,'replay')
        with children[0].mid360.tools.lock:retired_player=children[0].mid360.tools.instances['replay']['pid']
        # Keep playback active through World shutdown to exercise removed-owner
        # cleanup, rather than testing only an already stopped player.
        result['checks'][active_check]='PASS'
        active_check='disabled_mid360_regression'
        ordinary=n.api('/api/simulation/create',dict(scene_id='R01',vehicles=[dict(kind='rover',spawn={'id':'center'})],parameters={'obstacle_count':0}))
        n.api('/api/simulation/start',dict(id=ordinary['id']))
        n.app.simulation_manager.wait_ready(ordinary['id'],160)
        ordinary_owner=n.app.simulation_manager.owners[ordinary['id']]
        ordinary_child=next(iter(ordinary_owner.vehicles.values()))
        assert ordinary_child.mid360 is None
        assert not ordinary_child.view()['sensor_activation']['mid360']['enabled']
        n.wait(lambda:any(s.health()['online'] for s in ordinary_child.camera_sources.values()),30)
        n.api('/api/simulation/stop',dict(id=ordinary['id']))
        n.wait(lambda:n.app.simulation_manager.sample(ordinary['id'])['cleanup']=='COMPLETE',90)
        result['checks'][active_check]='PASS'
        active_check='simulation_cleanup'
        stop_observer(children[1],'live')
        n.api('/api/simulation/stop',dict(id=r['id']))
        n.wait(lambda:n.app.simulation_manager.sample(r['id'])['cleanup']=='COMPLETE',90)
        assert all(c.mid360.tools is None for c in children)
        assert not Path('/proc',str(retired_player)).exists()
        result['checks'][active_check]='PASS'
        active_check='backend_recording_recovery'
        # Restart the actual app owner over its durable state, not a fabricated
        # archive fixture. Only finalized recordings may be re-opened.
        n.app.close()
        from vehicle_autonomy.app.web.mission_control import MissionControl
        n.app=MissionControl({},n.path/'application',simulation_allow_send=True)
        n.server.service=n.app
        restored=n.app.simulation_manager.mid360_services[children[1].id][1]
        assert restored.live_closed and restored.tools is None
        bag=next(b for b in restored.bags.values() if b['complete'])
        tool(restored,'replay_start',bag_id=bag['id'])
        # Archives have no live VehicleSession; probe in a normal owned process.
        command,env=host.ros_command(['/usr/bin/env','ROS_DOMAIN_ID='+str(restored._ctx('replay')['ros_domain_id']),sys.executable,
            '-m','vehicle_autonomy.world.sensors.lidar.mid360_probe','--config',str(restored.config_path)])
        check=subprocess.run(command,env=env,capture_output=True,text=True,timeout=15)
        (directory/'restored-replay-probe.json').write_text(check.stdout+check.stderr);assert check.returncode==0
        tool(restored,'replay_stop');result['checks'][active_check]='PASS'
        result['status']='PASS' if all(v=='PASS' for v in result['checks'].values()) else 'NOT TESTED'
        n.report['status']=result['status']
    except Exception as exc:
        result['status']='FAIL'
        if active_check:result['checks'][active_check]='FAIL'
        result['errors'].append(type(exc).__name__+': '+str(exc))
        (directory/'traceback.log').write_text(traceback.format_exc())
    finally:
        if n:
            n.close()
            result['framework_native_report']=n.report
            if n.report.get('cleanup_error'):result['status']='FAIL'
            try:
                remaining=remaining_owned(directory,result.get('runtime',{}).get('partition',''))
                ports=[]
                for manifest in (directory/'native/application/simulation').glob('sim-*/vehicle-*/session.json'):
                    saved=json.loads(manifest.read_text())
                    assert not saved.get('remaining_process_groups') and not saved.get('cleanup_errors'),str(manifest)
                    assert saved.get('ports_released') is True,str(manifest)
                    for key,values in saved['ports'].items():
                        for port in values if isinstance(values,list) else [values]:
                            with socket.socket(socket.AF_INET,socket.SOCK_STREAM if key.startswith('tcp') else socket.SOCK_DGRAM) as s:
                                s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
                            ports.append(dict(kind=key,port=port,released=True))
                result['cleanup_audit']=dict(remaining=remaining,ports=ports)
                assert not remaining,remaining
                result['checks']['process_port_cleanup']='PASS'
                if not result['errors'] and not n.report.get('cleanup_error'):
                    result['status']='PASS' if all(v=='PASS' for v in result['checks'].values()) else 'NOT TESTED'
                    n.report['status']=result['status']
                    (n.path/'result.json').write_text(json.dumps(n.report,indent=2)+'\n')
            except Exception as exc:
                result['checks']['process_port_cleanup']='FAIL';result['status']='FAIL';result['errors'].append('cleanup audit: '+str(exc))
        save()
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--allow-send',action='store_true')
    p.add_argument('--gui',action='store_true')
    a=p.parse_args()
    result=run(a.run_dir,allow_send=a.allow_send,gui=a.gui)
    print(json.dumps(result,ensure_ascii=False,default=str))
    raise SystemExit(result['status']!='PASS')

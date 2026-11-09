"""Real original-chain LIO route acceptance with independent Gazebo judge."""
import argparse,json,os,sys,time,traceback,math
from pathlib import Path
from threading import Event,Thread
from dataclasses import asdict
from tests.simulation.control_binding_native import Native
from tests.simulation.oracle import GazeboTruthOracle
from tests.simulation.lio_accuracy import score,geometry,compare_optimization,motion_excitation
from tests.simulation.process_resources import sample_cpu
from vehicle_autonomy.app.simulation.mid360_slam import Mid360Slam
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from vehicle_autonomy.app.tools.builtins import make,profile
from vehicle_autonomy.world.mapping.cloud_maps import read_pcd


def controlled_circle(n,child,laps):
    """Finite test maneuver via original Drive tickets; AP state, never truth."""
    assert child.prepared['model_name']=='wildthumper','orbit fixture requires the audited central six-wheel body origin'
    segments=[];identifier=session=None
    def start(speed,rate,timeout):
        nonlocal identifier,session
        n.action(child.target,'SetMode',{'mode':'GUIDED'})
        response=n.api('/api/manual/start',dict(name='Drive',target=child.target,parameters=dict(speed_mps=speed,yaw_rate_rad_s=rate),allow_send=True,timeout_s=timeout))
        identifier=response['action']['id'];session=response['session']['id']
        n.wait(lambda:n.app.runtime.view(identifier)['state']=='RUNNING',10)
    def update(speed,rate):
        v=n.app.runtime.view(identifier)
        assert v['state']=='RUNNING',(v['state'],v['error'])
        n.api('/api/manual/update',dict(session_id=session,sequence=v['input_sequence']+1,deadline_ns=v['input_ticket'],parameters=dict(speed_mps=speed,yaw_rate_rad_s=rate)))
    def stop():
        n.api('/api/manual/stop',dict(session_id=session))
        final=n.wait(lambda:(lambda v:v if v['state'] in ('CANCELLED','FAILED','TIMED_OUT','UNKNOWN') else None)(n.app.runtime.view(identifier)),20)
        assert final['state']=='CANCELLED' and final['safety']['release_safe'],final
        segments.append(dict(id=identifier,state=final['state'],release_safe=True))
    start(0.,.2,30)
    deadline=time.monotonic()+25
    while True:
        pose=child.driver.snapshot().vehicle.reported_pose
        assert pose is not None,'real AP heading required'
        q=pose.value.orientation;yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
        error=math.atan2(math.sin(math.pi/2-yaw),math.cos(math.pi/2-yaw))
        if abs(error)<.06:break
        assert time.monotonic()<deadline,'controlled pivot deadline'
        update(0.,.2 if error>0 else -.2);time.sleep(.1)
    stop()
    # A bounded fixed orbit exercised through the original manual API. Only
    # AP reported ENU pose/twist guides the declared maneuver. Neither LIO nor
    # Gazebo judge state enters it. WildThumper turns about its central body,
    # so the old front-drive/caster axle offset must not be carried over.
    time.sleep(2)
    pose=child.driver.snapshot().vehicle.reported_pose.value.position
    center=(pose.x+1.5,pose.y);radius=1.5
    def angle(v):return math.atan2(math.sin(v),math.cos(v))
    for _ in range(laps):
        start(0.,0.,60);deadline=time.monotonic()+55;previous=None;orbit=0.
        while True:
            vehicle=child.driver.snapshot().vehicle;p=vehicle.reported_pose.value;q=p.orientation
            yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
            x=p.position.x;y=p.position.y
            polar=math.atan2(y-center[1],x-center[0])
            if previous is not None:orbit-=angle(polar-previous)
            previous=polar
            if orbit>=2*math.pi-.06:break
            assert time.monotonic()<deadline,dict(reason='declared orbit deadline',orbit=orbit)
            assert max(abs(p.position.x),abs(p.position.y))<4.5,'approaching original 5 m safety boundary'
            radial=math.hypot(x-center[0],y-center[1])-radius
            tangent=polar-math.pi/2
            error=angle(tangent-math.atan2(1.2*radial,.25)-yaw)
            speed=.25 if abs(error)<=.5 else 0.
            rate=max(-.25,min(.25,-speed/radius+1.2*error-.25*vehicle.reported_twist.value.angular.z))
            update(speed,rate);time.sleep(.1)
        stop();time.sleep(1)
    return dict(id=identifier,name='Drive',state='CANCELLED',release_safe=True,radius_m=radius,laps=laps,segments=segments,
        control_feedback='ArduPilot reported ENU pose/twist only; fixed operator orbit, no map or truth input')



def run(path,kind,*,gui=False,pgo=False,laps=1,route_name='square',scene='L01'):
    if type(laps) is not int or not 1<=laps<=3:raise ValueError('one to three declared route laps required')
    if route_name not in ('square','pillar','circle') or route_name in ('pillar','circle') and kind!='rover':raise ValueError('declared vehicle route required')
    if scene not in ('L01','L02') or route_name in ('pillar','circle') and scene!='L02':raise ValueError('pillar route requires within-fence L02')
    n=Native(path);path=n.path;result=dict(status='FAIL',kind=kind,checks={});stop=Event();collector=None;poses=[];states=[];resources=[];oracle=None;health=[]
    extra_columns=((2,0,2),) if scene=='L02' else ()
    (path/'acceptance-plan.json').write_text(json.dumps(dict(scene=scene,route=route_name,laps=laps,
        thresholds=json.loads((n.app.simulation_manager.root/'configs/mid360-slam-acceptance.json').read_text()),
        extra_geometry_columns=extra_columns),indent=2)+'\n')
    def check(name,condition,detail=None):
        result['checks'][name]=dict(status='PASS' if condition else 'FAIL',detail=detail)
    try:
        r=n.api('/api/simulation/create',dict(scene_id=scene,vehicles=[dict(kind=kind,spawn={'id':'center'},
            sensors={'mid360':True,'mid360_lio':True})],parameters={'obstacle_count':0}))
        n.api('/api/simulation/start',{'id':r['id']});n.app.simulation_manager.wait_ready(r['id'],180)
        owner=n.app.simulation_manager.owners[r['id']];child=next(iter(owner.vehicles.values()));sensor=child.mid360
        os.environ.update(GZ_IP='127.0.0.1',GZ_PARTITION=owner.partition)
        oracle=GazeboTruthOracle(owner.world,child.model.name,history_size=20000);n.oracles[child.target]=oracle
        n.wait(sensor.online,60)
        service=Mid360Slam(sensor);sensor.slam=service
        # Exercise the actual authenticated Tool/Web route, not a second owner.
        binding=dict(id=r['id'],vehicle_id=child.id)
        api=lambda action,**kw:n.api('/api/simulation/slam',dict(binding,action=action,**kw))
        def motion_ready():
            vehicle=child.driver.snapshot().vehicle
            return vehicle and vehicle.reported_pose is not None and vehicle.reported_twist is not None
        api('start');n.wait(lambda:service.snapshot()['online'],60)
        def collect():
            previous=-1;previous_health=None;process_previous={}
            while not stop.wait(.02):
                try:
                    status=service.snapshot();raw=status['state'];pose=raw.get('localization')
                    current_health=(status['online'],status['error'],raw.get('error'))
                    if current_health!=previous_health:
                        health.append(dict(at_host_ns=time.monotonic_ns(),online=status['online'],error=status['error'],
                            raw_error=raw.get('error'),viewer_events=status['viewer_events'],
                            source_diagnostic=raw if not status['online'] else None))
                        previous_health=current_health
                    if pose and pose['capture_ros_ns']>previous:
                        previous=pose['capture_ros_ns'];poses.append(pose);states.append(raw)
                        record=sensor.tools.instances.get('fast-lio')
                        if record and record['pid']:
                            processes={}
                            for key in ('fast-lio','lio-adapter','map-process','sc-pgo'):
                                instance=sensor.tools.instances.get(key,{})
                                process_pid=raw.get('map_worker',{}).get('pid') if key=='map-process' else instance.get('pid')
                                if not process_pid:continue
                                try:
                                    root=Path('/proc',str(process_pid));fields=root.joinpath('stat').read_text().split(') ',1)[1].split()
                                    identity=(process_pid,int(fields[19]));measurement=sample_cpu(process_pid,identity,process_previous)
                                    status_text=root.joinpath('status').read_text();memory=int(next(l.split()[1] for l in status_text.splitlines() if l.startswith('VmRSS:')))/1024
                                    processes[key]=dict(pid=process_pid,start_ticks=identity[1],rss_mib=memory,**measurement)
                                except (OSError,StopIteration):continue
                            required={'fast-lio','lio-adapter','map-process'}
                            fast=processes.get('fast-lio')
                            if not fast:continue
                            resources.append(dict(at=time.monotonic(),rss_mib=fast['rss_mib'],cpu_percent=fast['cpu_percent'],latency_ms=raw.get('latency_host_ms'),
                                processes=processes,pipeline_sample_complete=required<=processes.keys() and all(processes[k]['cpu_percent'] is not None for k in required),
                                pipeline_rss_mib=sum(p['rss_mib'] for key,p in processes.items() if key in required),
                                pipeline_cpu_percent=sum(p['cpu_percent'] or 0. for key,p in processes.items() if key in required)))
                except Exception:result['collector_error']=traceback.format_exc();return
        collector=Thread(target=collect,daemon=True);collector.start()
        if pgo:api('pgo_start')
        if gui:
            from tests.visualization.desktop import goal
            from vehicle_autonomy.app.control_center.desktop import windows
            host=HostEnvironment(owner.root)
            environment={k:v for k,v in owner.session.env.items() if k.startswith('GZ_') or k in
                ('HOME','USER','LANG','PATH','DISPLAY','XAUTHORITY','XDG_RUNTIME_DIR','LD_LIBRARY_PATH','PYTHONPATH')}
            environment['QT_QPA_PLATFORM']='xcb'
            probe=dict(argv=[sys.executable,'-m','vehicle_autonomy.app.control_center.desktop','--gazebo'],contains=['"status": "READY"'],timeout_s=5)
            sensor.tools.registry['gazebo-gui']=make('gazebo-gui','SLAM acceptance Gazebo','gui',
                {'default':profile([host.executable('gazebo'),'sim','-g','-v3'],env=environment,ready=probe,health=probe,timeout=90)},permissions=['desktop'])
            sensor.tools.execute('launch','gazebo-gui','default',sensor._ctx('live'))
            # Reuse goal one's real-window activation. A mapped but obscured
            # Qt shell may not render camera events until it is activated.
            # The render-event probe remains required after activation.
            def mapped_gui():
                with sensor.tools.lock:pid=sensor.tools.instances['gazebo-gui']['pid']
                return pid if pid and windows([pid]) else None
            gpid=n.wait(mapped_gui,30)
            goal(gpid,capture=path/'gazebo-before-readiness.png',select=False)
            n.wait(lambda:sensor.snapshot()['tools'].get('gazebo-gui',{}).get('ready'),100)
            gpid=sensor.tools.instances['gazebo-gui']['pid'];goal(gpid,capture=path/'gazebo-before.png',select=False)
            api('rviz_start');n.wait(lambda:sensor.snapshot()['tools'].get('slam-rviz',{}).get('ready'),100)
            rviz=sensor.tools.instances['slam-rviz']['pid'];goal(rviz,capture=path/'rviz-before.png',select=False)
            check('actual_gui_ready',True)
        time.sleep(max(0,45-(time.monotonic()-service.started_at)))
        n.action(child.target,'SetMode',{'mode':'GUIDED'});n.action(child.target,'Arm')
        initial=child.driver.snapshot().vehicle.reported_pose.value.position
        first=oracle.latest();height=0. if kind=='rover' else 1.6
        if kind=='copter':n.action(child.target,'Takeoff',{'height_m':1.6})
        route=[(initial.x+2,initial.y,height),(initial.x+2,initial.y+2,height),
            (initial.x,initial.y+2,1.1 if kind=='copter' else 0.),(initial.x,initial.y,height)]*laps
        if route_name=='pillar':
            # Nominal L02 column at (2,0), radius .4 m. A declared
            # within-fence rectangle gives turn clearance; no truth feedback or
            # obstacle planner chooses these waypoints at runtime.
            route=[(initial.x+x,initial.y+y,0.) for x,y in
                [(0,-1.5),(3.25,-1.5),(3.25,1.5),(0,1.5),(0,-1.5),(0,0)]]*laps
        result['route']=route;result['route_name']=route_name;result['laps']=laps;result['actions']=[]
        if route_name=='circle':
            result['actions']=[controlled_circle(n,child,laps)];route=[];result['route']=[]
            result['maneuver']='AP-heading pivot and bounded original Drive orbit; nominal center (1.5,0), radius 1.5 m'
            if gui:
                goal(rviz,capture=path/'rviz-after-circle.png',select=False)
                goal(gpid,capture=path/'gazebo-after-circle.png',select=False)
        for x,y,z in route:
            # Ordinary Goto deliberately finishes in HOLD. Re-enter GUIDED
            # through the same authorized Action before each next waypoint.
            n.action(child.target,'SetMode',{'mode':'GUIDED'})
            # Mode Action releases its writer session before the next Action.
            # Wait for real telemetry after that transition; never treat a
            # momentarily empty receive snapshot as permission to move.
            n.wait(motion_ready,10)
            action=n.action(child.target,'Goto',dict(x_m=x,y_m=y,z_m=z),timeout=90)
            result['actions'].append(dict(id=action['id'],name='Goto',state=action['state']))
            assert service.snapshot()['online'],service.snapshot()
            if gui and len(result['actions'])==1:
                goal(rviz,capture=path/'rviz-during-route.png',select=False)
                goal(gpid,capture=path/'gazebo-during-route.png',select=False)
            time.sleep(2)
        if kind=='copter':
            n.action(child.target,'SetMode',{'mode':'GUIDED'})
            n.action(child.target,'SetYaw',{'yaw_rad':.6});n.action(child.target,'SetYaw',{'yaw_rad':0.})
            n.action(child.target,'Land',timeout=90)
        else:n.action(child.target,'Disarm')
        time.sleep(3);last=oracle.latest()
        if pgo:
            service._register('pgo-judge','Independent read-only PGO evidence')
            sensor._launch('pgo-judge',[sys.executable,str(owner.root/'tests/simulation/pgo_observe.py'),
                '--sensor',str(sensor.config_path),'--output',str(path/'pgo-observation'),'--seconds','12'])
            n.wait(lambda:not sensor._active('pgo-judge'),30)
            result['pgo_observation']=json.loads((path/'pgo-observation/observation.json').read_text())
        check('controlled_actual_motion',((last.x_m-first.x_m)**2+(last.y_m-first.y_m)**2)**.5<1.5 and
            len(result['actions'])==(1 if route_name=='circle' else len(route)))
        final=service.snapshot();check('lio_after_motion',final['online'],final['error'])
        publication=service.world.reader().snapshot()
        check('typed_readonly_localization',publication.localization is not None and publication.vehicle is None and
            publication.localization.covariance is None and str(publication.localization.pose.frame_id)==service.config['frames']['map'])
        check('typed_live_map_resource',publication.map is not None and publication.map.version.generation_id==service.config['generation'])
        saved=api('save',name='L01 '+kind+' controlled closed route');metadata,data=service.catalog.load(saved['id'])
        (path/'map.pcd').write_bytes(data);(path/'map-metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
        result['map']=dict(id=saved['id'],points=metadata['points'],sha256=metadata['sha256'])
        if gui:
            check('viewer_continuous_during_route',sensor._active('slam-rviz'),service.snapshot()['viewer_error'])
            if not sensor._active('slam-rviz'):
                api('rviz_start');n.wait(lambda:sensor.snapshot()['tools'].get('slam-rviz',{}).get('ready'),100)
                rviz=sensor.tools.instances['slam-rviz']['pid']
            goal(rviz,capture=path/'rviz-after.png',select=False);goal(gpid,capture=path/'gazebo-after.png',select=False)
            api('load',map_id=saved['id']);api('loaded_rviz_start')
            n.wait(lambda:sensor.snapshot()['tools'].get('slam-rviz',{}).get('ready'),100)
            # Activate the new owned client, then allow its own render cycle
            # to paint. A received-message probe alone cannot certify pixels.
            goal(sensor.tools.instances['slam-rviz']['pid'],select=False)
            time.sleep(2)
            goal(sensor.tools.instances['slam-rviz']['pid'],capture=path/'rviz-loaded-map.png',select=False)
            check('loaded_map_actual_view',True)
        stop.set();collector.join(3)
        with oracle._condition:truth=[asdict(v) for v in oracle._samples]
        (path/'lio-poses.json').write_text(json.dumps(poses)+'\n');(path/'judge-truth.json').write_text(json.dumps(truth)+'\n')
        metrics=score(poses,truth,sensor.config['model_to_body']);metrics.update(geometry(read_pcd(data),metrics,extra_columns));result['metrics']=metrics
        result['motion_excitation']=motion_excitation(truth)
        if route_name in ('pillar','circle'):
            import numpy as np
            xy=np.array([[row['x_m']-2.,row['y_m']] for row in truth])
            polar=np.unwrap(np.arctan2(xy[:,1],xy[:,0]));turns=float((polar[-1]-polar[0])/(2*math.pi))
            clearance=float(np.linalg.norm(xy,axis=1).min())
            result['independent_pillar_orbit']=dict(signed_turns=turns,minimum_center_distance_m=clearance,pillar=[2.,0.,.4])
            check('actual_encirclement_of_scene_pillar',abs(turns)>=.8*laps,result['independent_pillar_orbit'])
            check('actual_pillar_clearance',clearance>=.8,result['independent_pillar_orbit'])
        if kind=='copter':
            excitation=result['motion_excitation']
            check('actual_vertical_motion',excitation['height_span_m']>=1.,excitation)
            check('actual_roll_pitch_and_yaw_motion',excitation['roll_range_deg']>=1. and excitation['pitch_range_deg']>=1. and excitation['yaw_range_deg']>=20.,excitation)
        if pgo:
            pgo_poses=json.loads((path/'pgo-observation/poses.json').read_text())
            optimized=score(pgo_poses,truth,sensor.config['model_to_body'])
            if (path/'pgo-observation/map.pcd').exists():optimized.update(geometry(read_pcd((path/'pgo-observation/map.pcd').read_bytes()),optimized,extra_columns))
            result['pgo_metrics']=optimized
            result['pgo_same_capture_comparison']=compare_optimization(poses,pgo_poses,truth,sensor.config['model_to_body'])
            check('pgo_actual_pose_correction',result['pgo_same_capture_comparison']['correction_max_m']>1e-5,
                result['pgo_same_capture_comparison'])
            check('pgo_actual_applied_loop',states[-1].get('pgo',{}).get('applied_loop_constraints',0)>0,states[-1].get('pgo'))
            check('pgo_has_no_tf_publisher',result['pgo_observation']['tf_publishers']==0,result['pgo_observation'])
            check('pgo_map_preserves_capture_stamp',result['pgo_observation'].get('map_capture_ros_ns',0)>0,result['pgo_observation'])
            for key,limit in json.loads((owner.root/'configs/mid360-slam-acceptance.json').read_text())[kind].items():
                check('pgo_'+key,optimized[key]<=limit,dict(measured=optimized[key],limit=limit))
            check('pgo_geometry',optimized.get('geometry_residual_p95_m',float('inf'))<=.20,optimized.get('geometry_residual_p95_m'))
        thresholds=json.loads((owner.root/'configs/mid360-slam-acceptance.json').read_text())
        for key,limit in thresholds[kind].items():check(key,metrics[key]<=limit,dict(measured=metrics[key],limit=limit))
        check('actual_route_distance',metrics['truth_distance_m']>=6,metrics['truth_distance_m'])
        for key in ('geometry_residual_p95_m','minimum_points','minimum_matching_landmark_groups'):
            actual=metrics[{'minimum_points':'points','minimum_matching_landmark_groups':'matching_landmark_groups'}.get(key,key)]
            limit=thresholds['map'][key];check(key,actual<=limit if key.endswith('_m') else actual>=limit,dict(measured=actual,limit=limit))
        max_gap=max(s.get('imu_max_gap_sim_ns',0) for s in states)/1e9;check('imu_gap',max_gap<=.02,max_gap)
        skew=max(s.get('scan_imu_nearest_ns',0) for s in states)/1e9;check('point_imu_skew',skew<=.01,skew)
        for name,field,limit in (('lio_rss','rss_mib',2048),('lio_cpu','cpu_percent',300),('lio_latency','latency_ms',1000)):
            value=max(v[field] for v in resources if v[field] is not None);check(name,value<=limit,dict(measured=value,limit=limit))
        complete=[r for r in resources if r.get('pipeline_sample_complete')]
        check('pipeline_resource_samples',len(complete)>=.95*len(resources),dict(complete=len(complete),samples=len(resources)))
        for field,limit in (('pipeline_rss_mib',2048),('pipeline_cpu_percent',300)):
            check(field,bool(complete) and max(v[field] for v in complete)<=limit,
                dict(measured=max((v[field] for v in complete),default=None),limit=limit,scope='FAST-LIO + adapter + map process; optional PGO separately sampled'))
        delivery=states[-1].get('scan_delivery',{});fraction=delivery.get('dropped_fraction')
        check('dropped_scan_fraction',fraction is not None and fraction<=.10,delivery)
        result['status']='PASS' if all(c['status']=='PASS' for c in result['checks'].values()) else 'FAIL'
        n.report['status']=result['status']
    except Exception:result['error']=traceback.format_exc();print(result['error'],flush=True)
    finally:
        stop.set()
        if collector:collector.join(3)
        (path/'lio-states.json').write_text(json.dumps(states)+'\n')
        (path/'health-events.json').write_text(json.dumps(health,indent=2)+'\n')
        (path/'lio-poses.json').write_text(json.dumps(poses)+'\n');(path/'resources.json').write_text(json.dumps(resources)+'\n')
        if oracle:
            with oracle._condition:truth=[asdict(v) for v in oracle._samples]
            (path/'judge-truth.json').write_text(json.dumps(truth)+'\n')
            if 'metrics' not in result:
                try:result['metrics']=score(poses,truth,sensor.config['model_to_body'])
                except ValueError as exc:result['metrics_error']=str(exc)
        if resources:
            result['runtime']=dict(max_rss_mib=max(r['rss_mib'] for r in resources),max_cpu_percent=max(r['cpu_percent'] for r in resources if r['cpu_percent'] is not None),
                max_latency_host_s=max(r['latency_ms'] for r in resources)/1000)
            complete=[r for r in resources if r.get('pipeline_sample_complete')]
            if complete:result['runtime'].update(pipeline_max_rss_mib=max(r['pipeline_rss_mib'] for r in complete),
                pipeline_max_cpu_percent=max(r['pipeline_cpu_percent'] for r in complete))
        if 'service' in locals():result['last_source_status']=service.snapshot()
        n.close();result['cleanup']=n.report['cleanup']
        if n.report.get('cleanup_error'):result.update(status='FAIL',cleanup_error=n.report['cleanup_error'])
        (path/'slam-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result['status'],flush=True);return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True,type=Path)
    parser.add_argument('--kind',choices=['rover','copter'],required=True);parser.add_argument('--gui',action='store_true');parser.add_argument('--pgo',action='store_true')
    parser.add_argument('--laps',type=int,default=1)
    parser.add_argument('--route',choices=['square','pillar','circle'],default='square')
    parser.add_argument('--scene',choices=['L01','L02'],default='L01')
    args=parser.parse_args();raise SystemExit(0 if run(args.run_dir,args.kind,gui=args.gui,pgo=args.pgo,laps=args.laps,route_name=args.route,scene=args.scene)['status']=='PASS' else 1)

"""Native CUADC map, fixed camera, PT inference and optional Mission acceptance.

Uses only an owned loopback SITL through the existing SimulationManager and
Action/Mission ingress. Read-only mode grants no SEND; --flight is explicit.
"""
import argparse,json,time,traceback
from pathlib import Path
from vehicle_autonomy.app.web.mission_control import MissionControl
from vehicle_autonomy.app.scenarios.cuadc.rescue import template
from vehicle_autonomy.contracts.core.serialization import to_json_value


def run(directory,*,flight=False,landing_only=False,record_comparison=False):
    directory=Path(directory).resolve();directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    result={'status':'FAIL','flight_requested':flight};app=MissionControl({},directory/'application',simulation_allow_send=flight)
    identifier=None;recorder=None
    try:
        manager=app.simulation_manager
        record=manager.create(dict(scene_id='CUADC2026',vehicles=[dict(kind='copter_rescue')],parameters={}))
        identifier=record['id'];manager.start(identifier)
        ready=manager.wait_ready(identifier,150)
        owner=manager.owners[identifier];child=next(iter(owner.vehicles.values()));driver=app.drivers[child.target]
        result['session']=identifier;result['target']=child.target
        until=time.monotonic()+45
        while time.monotonic()<until:
            world=driver.snapshot()
            if world and world.vehicle and world.vehicle.health.quality.value=='VALID' and any(s.health()['online'] for s in child.camera_sources.values()):break
            time.sleep(.2)
        else:raise TimeoutError('fresh vehicle and actual fixed camera unavailable')
        source=next(iter(child.camera_sources.values()));meta,jpeg=source.packet();(directory/'camera.jpg').write_bytes(jpeg)
        result['camera']=meta
        result['capabilities']=sorted(driver.context().capabilities)
        assert {'rescue_flight','rescue_vision','rescue_payload'}<=driver.context().capabilities
        assert not driver.info()['system_send'] and not driver.info()['action_send']
        # Camera is too close to the ground for bucket localization here. A
        # positive pixel inference is not required to claim process readiness.
        until=time.monotonic()+45;detection=child.directory/'rescue-inference/detections.json'
        while time.monotonic()<until:
            if detection.is_file():
                value=json.loads(detection.read_text())
                if time.monotonic_ns()-value['received_ns']<2_000_000_000:result['detections']=value;break
            time.sleep(.2)
        else:raise TimeoutError('actual local PT inference did not publish')
        definition=template(child.target)
        if landing_only:
            from vehicle_autonomy.app.mission_designer.studio_examples import edge
            keep=['start','settle_estimator','guided','arm','takeoff_4_5m','landing_marker','final_land_align','land_home','end']
            definition['nodes']=[next(n for n in definition['nodes'] if n['node_id']==name) for name in keep]
            next(n for n in definition['nodes'] if n['node_id']=='takeoff_4_5m')['parameters']['height_m']=2.5
            definition['edges']=[edge(a,b) for a,b in zip(keep,keep[1:])]
            definition['mission_id']='Rescue_2026_LandingAcceptance'
        compiled=app.studio.compile(definition)
        result['compiled_nodes']=len(compiled.to_dict()['nodes'])
        if flight:
            if record_comparison:
                from vehicle_autonomy.app.simulation.comparison_recording import CameraComparisonRecorder
                recorder=CameraComparisonRecorder(directory/'camera-comparison',child.camera_sources['gimbal-camera'],
                    child.camera_sources['stabilized'],binding=dict(target=child.target,world=owner.world,session=identifier))
            from vehicle_autonomy.app.bootstrap.mission_binding import live_instance
            with app._control_lock:
                item=app.studio.library.save(definition,0)
                compiled=app.studio.compile(item['definition'])
                publication=app.studio.library.publish(definition['mission_id'],item['definition']['revision'],compiled)
                started=app.studio.handle('studio-b.run.start',dict(publication=definition['mission_id']+'@1.0.0',
                    definition_hash=publication['definition_hash'],binding=live_instance(app,child.target),allow_send=True))
            result['mission_start']=started
            until=time.monotonic()+1500;preview_frames=[];saved=set()
            while time.monotonic()<until:
                view=app.missions.view(started['id'])
                world=driver.snapshot()
                current=dict(state=view['state'],actions=app.runtime.views(),
                    pose=None if world is None or world.localization is None else to_json_value(world.localization.pose),
                    objects=[] if world is None else to_json_value(world.objects))
                if recorder:recorder.update_phase(view['state'],current['actions'])
                from vehicle_autonomy.world.mapping.grid import atomic_json
                atomic_json(directory/'latest.json',current)
                preview=child.camera_sources['yolo']
                if preview.health()['online']:
                    try:metadata,jpeg=preview.packet()
                    except (OSError,ValueError):pass
                    else:
                        if not preview_frames or preview_frames[-1]['sequence']!=metadata['sequence']:
                            preview_frames.append(metadata)
                            # Use the actual drop-region view as bucket image
                            # evidence; the model can mislabel the small home H.
                            labels={d['label'] for d in metadata['detections']
                                if d['label']=='bucket' and metadata['rectification']['origin_enu'][1]>25
                                or d['label']=='H' and d['detector']=='h_marker'}
                            for label in labels:
                                if label not in saved:
                                    (directory/('annotated-'+label+'.jpg')).write_bytes(jpeg);saved.add(label)
                            atomic_json(directory/'nadir-frames.json',preview_frames)
                if view['state'] in ('SUCCEEDED','FAILED','UNKNOWN','CANCELLED','TIMED_OUT'):
                    result['mission']=view;break
                time.sleep(.5)
            else:raise TimeoutError('rescue mission native deadline')
            if result['mission']['state']!='SUCCEEDED':raise AssertionError('native mission '+result['mission']['state']+': '+str(result['mission'].get('error')))
            result['nadir_preview']=dict(frames=len(preview_frames),labels=sorted(saved),
                reference_ids=sorted({f['rectification']['reference_id'] for f in preview_frames}),
                minimum_attitude_rate_hz=min(f['rectification']['attitude_rate_hz'] for f in preview_frames),
                minimum_valid_fraction=min(f['rectification']['valid_fraction'] for f in preview_frames))
            assert {'bucket','H'}<=saved and len(result['nadir_preview']['reference_ids'])==1,result['nadir_preview']
        result['status']='PASS'
    except Exception as exc:
        result['error']=type(exc).__name__+': '+str(exc);traceback.print_exc()
    finally:
        result['actions']=app.runtime.views()
        if recorder:
            try:
                time.sleep(.5)
                result['camera_recording']=recorder.close()
            except Exception as exc:result.update(status='FAIL',recording_error=str(exc))
        try:app.close()
        except Exception as exc:result['status']='FAIL';result['cleanup_error']=str(exc)
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps({k:result.get(k) for k in ('status','error','cleanup_error','compiled_nodes')},ensure_ascii=False),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--flight',action='store_true');p.add_argument('--landing-only',action='store_true');p.add_argument('--record-camera-comparison',action='store_true');args=p.parse_args()
    if args.record_camera_comparison and not args.flight:p.error('comparison recording requires the explicit owned simulation --flight run')
    raise SystemExit(0 if run(args.directory,flight=args.flight,landing_only=args.landing_only,record_comparison=args.record_camera_comparison)['status']=='PASS' else 1)

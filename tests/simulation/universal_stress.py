"""Repeated native epoch replacement plus replay of captured signed old ingress.

Only original registered Actions request vehicle commands. Replay injection is
receive-only inside the test's owned SoftwareFaultLink; it never writes MAVLink.
"""
import argparse
import json
from pathlib import Path
import time
import traceback

from vehicle_autonomy.app.web.mission_control import MissionControl


def run(directory,scenes):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    app=MissionControl({},directory/'application',simulation_allow_send=True)
    manager=app.simulation_manager
    result=dict(status='FAIL',rounds=[],error=None,scope='real owned Rover epochs; captured signed ACK/telemetry replay at receive boundary')
    def wait(predicate,timeout=150):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            value=predicate()
            if value:return value
            time.sleep(.05)
        raise TimeoutError('native stress observation')
    def rss():return int(Path('/proc/self/statm').read_text().split()[1])*4096/1024**2
    def finish_action(identifier):
        value=app.runtime.view(identifier)
        if value['state'] in {'FAILED','UNKNOWN','REJECTED','TIMED_OUT','CANCELLED'}:raise AssertionError(value)
        return value if value['state']=='SUCCEEDED' and value['safety']['release_safe'] else None
    def quiescent(owner):
        for session in [owner.session,*[child.session for child in owner.vehicles.values()]]:
            assert all(p.poll() is not None for p,_,_ in session.processes)
            assert not session.manifest.get('remaining_process_groups')
        for child in owner.vehicles.values():assert child.session.manifest.get('credentials_removed')
    try:
        value=manager.create(dict(scene_id=scenes[0],vehicle='rover',parameters={'obstacle_count':0}))
        manager.start(value['id']);manager.wait_ready(value['id'],150)
        current=value['id'];previous_target=previous_epoch=previous_generation=None;fingerprint=None
        for index,scene in enumerate(scenes):
            if index:
                old=manager.owners[current]
                manager.handle('simulation.switch',dict(id=current,scene_id=scene,parameters={'obstacle_count':0}))
                def switched():
                    item=manager.sample(current)['switch']
                    if item['state']=='FAILED':raise AssertionError(item)
                    return item['new_session_id'] if item['state']=='SUCCEEDED' else None
                current=wait(switched,200)
                quiescent(old)
            owner=manager.owners[current];child=next(iter(owner.vehicles.values()))
            info,world=child.driver.read_view()
            entry=dict(index=index,scene_id=scene,id=current,target=child.target,session_id=info['session_id'],
                generation=str(world.version.generation_id),fingerprint=child.prepared['fingerprint'],
                parameter_readback=child.session.manifest['fixed_parameters_readback'],rss_mib=rss(),
                old_ingress_rejected=None)
            assert child.target!=previous_target and info['session_id']!=previous_epoch and entry['generation']!=previous_generation
            assert not info['system_send'] and not info['action_send'] and not info['lease_active']
            if fingerprint is not None:assert fingerprint==entry['fingerprint']
            fingerprint=entry['fingerprint']
            if index:
                rejected=child.proof.receive_signing.rejected
                before=dict(rejected)
                child.link.inject_received(old_bytes)
                wait(lambda:sum(rejected.values())>sum(before.values()),3)
                entry['old_ingress_rejected']=dict(rejected)
                info,world=child.driver.read_view()
                assert info['connected'] and not info['system_send'] and world.vehicle.health.quality.value=='VALID'
                assert not world.vehicle.operation.armed
            child.link.begin_capture()
            action=app.handle('manual.action',dict(target=child.target,name='SetMode',parameters={'mode':'HOLD'},allow_send=True))
            wait(lambda:finish_action(action['id']),20)
            time.sleep(.25)
            captured=child.link.end_capture()
            from pymavlink.dialects.v20 import ardupilotmega as dialect
            parser=dialect.MAVLink(None);parser.robust_parsing=True
            messages=parser.parse_buffer(captured) or []
            acknowledgements=[bytes(m.get_msgbuf()) for m in messages if m.get_type()=='COMMAND_ACK']
            telemetry=[bytes(m.get_msgbuf()) for m in messages if m.get_type() in {'ATTITUDE','LOCAL_POSITION_NED','GLOBAL_POSITION_INT','HEARTBEAT'}]
            assert acknowledgements and telemetry,'actual signed ACK and telemetry capture required'
            old_bytes=b''.join(acknowledgements+telemetry[:4])
            entry.update(captured_old_ack=len(acknowledgements),captured_old_telemetry=len(telemetry),status='PASS')
            previous_target,previous_epoch,previous_generation=child.target,info['session_id'],entry['generation']
            result['rounds'].append(entry)
            (directory/'progress.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(index,scene,'PASS',round(entry['rss_mib'],1),flush=True)
        manager.stop(current);manager.threads[current].join(70)
        assert manager.sample(current)['cleanup']=='COMPLETE'
        quiescent(manager.owners[current])
        result['status']='PASS'
    except Exception as exc:
        result['error']=type(exc).__name__+': '+str(exc);traceback.print_exc()
    finally:
        try:app.close()
        except Exception as exc:result['cleanup_error']=str(exc);result['status']='FAIL'
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--scenes',nargs='+',default=['R01','R04','R06','R03','R01','R04']);args=p.parse_args()
    raise SystemExit(run(args.directory,args.scenes)['status']!='PASS')

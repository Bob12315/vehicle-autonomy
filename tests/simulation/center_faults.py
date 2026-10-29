"""Actual owned-SITL receive fault: signed duplicates cannot refresh state.

Disarmed, SEND-off only. This probes the new software fault link, not simulated
GPS/IMU fusion or a claim of physical stopping after loss of telemetry.
"""
import argparse
import json
from pathlib import Path
import time

from vehicle_autonomy.app.web.mission_control import MissionControl
from tests.simulation.launch import install_signal_cleanup


def run(directory):
    directory=directory.resolve();directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    app=MissionControl({},directory/'application')
    manager=app.simulation_manager;identifier=None
    result=dict(status='FAIL',scope='real owned Rover SITL -> SoftwareFaultLink -> existing Driver; no SEND or motion')
    try:
        record=manager.create(dict(scene_id='R01',vehicle='rover',parameters={'obstacle_count':0}))
        identifier=record['id'];manager.start(identifier);manager.wait_ready(identifier,140)
        owner=manager.owners[identifier]
        time.sleep(45)  # same native sensor/EKF warmup as the existing motion acceptance
        before=owner.driver.info()
        assert before['connected'] and not before['system_send'] and not before['action_send']
        stamp_before=owner.driver.snapshot().vehicle.reported_pose.captured_at.monotonic_ns
        # Real incoming data is delayed and dropped on this stream only.
        manager.handle('simulation.fault',dict(id=identifier,settings={'delay_ms':20}))
        time.sleep(1)
        baseline_drops=owner.link.dropped
        manager.handle('simulation.fault',dict(id=identifier,settings={'loss':1}))
        deadline=time.monotonic()+2.5
        while owner.link.dropped==baseline_drops and time.monotonic()<deadline:
            time.sleep(.01)
        dropped=owner.link.dropped-baseline_drops
        manager.handle('simulation.fault',dict(id=identifier,settings={}))
        assert dropped>0,'configured packet loss produced no observed drops'
        time.sleep(1.2)
        fresh=owner.driver.snapshot()
        assert fresh and fresh.vehicle and fresh.vehicle.reported_pose.captured_at.monotonic_ns>stamp_before
        assert not owner.driver.info().get('fault'),owner.driver.info()
        result['bounded_delay_loss']=dict(status='PASS',delay_ms=20,loss_probability=1,
            observed_dropped_chunks=dropped,note='one observed receive loss, then explicit reset before prolonged interruption')
        manager.handle('simulation.fault',dict(id=identifier,settings={'freeze':True}))
        accepted=owner.proof.receive_signing.accepted
        deadline=time.monotonic()+16
        while time.monotonic()<deadline:
            info=owner.driver.info()
            if info.get('fault') or not info.get('connected'):break
            time.sleep(.1)
        else:raise TimeoutError('frozen signed telemetry failed to fence Driver')
        assert not info['system_send'] and not info['action_send']
        result['frozen_duplicate_fence']=dict(status='PASS',driver_fault=info.get('fault'),
            accepted_before=accepted,accepted_after=owner.proof.receive_signing.accepted,
            signature_rejections=dict(owner.proof.receive_signing.rejected),system_send=info['system_send'],action_send=info['action_send'],physical_stop='UNCONFIRMED')
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            report=manager.sample(identifier)
            if report['state'] in ('FAILED','FINISHED'):break
            time.sleep(.1)
        assert report['state']=='FAILED' and report['cleanup']=='COMPLETE',report.get('error')
        result['session_report']=report;result['status']='PASS'
    except Exception as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        if identifier and identifier in manager.owners:
            current=manager.owners[identifier]
            result['diagnostics']=None if current.link is None else current.link.diagnostics()
            result['driver_info']=None if current.driver is None else current.driver.info()
    finally:
        try:app.close()
        except Exception as exc:result['cleanup_error']=str(exc);result['status']='FAIL'
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True)
    args=p.parse_args();install_signal_cleanup();value=run(args.run_dir)
    print(json.dumps({k:v for k,v in value.items() if k!='session_report'},ensure_ascii=False))
    return int(value['status']!='PASS')


if __name__=='__main__':raise SystemExit(main())

"""Object absence/loss business failures from formal App with independent truth."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
from app.control import request
from tests.simulation.launch import ROOT, OwnedSimulation, install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle
from tests.simulation.object_fixture import add_objects,service


def run(directory,kind):
    directory.mkdir(parents=True,exist_ok=False)
    owned=OwnedSimulation(directory,kind)
    endpoint=directory/'app.sock'
    report={'passed':False,'checks':{}}
    sensor=None
    evidence=(directory/'status.jsonl').open('w')
    try:
        sensor=add_objects(owned)
        owned.start()
        oracle=GazeboTruthOracle(owned.world,owned.model)

        config=directory/'profile.toml'
        config.write_text((ROOT/f'simulation/profiles/{kind}.toml').read_text().replace('port = 5760',f'port = {owned.port}'))
        started=time.monotonic()
        app=owned.start_process('application',[sys.executable,'-m','app.main','run','--profile',kind+'_sim','--config',str(config),'--control-socket',str(endpoint),'--allow-send','--sim-sensor-config',str(sensor),'--sim-payload'])
        def status():
            owned.assert_alive()
            state=request(endpoint,'status')['result']
            truth=oracle.latest()
            if state['task'] is not None and (truth is None or time.monotonic_ns()-truth.host_received_ns>1_000_000_000):raise RuntimeError('oracle stale')
            evidence.write(json.dumps({'host_ns':time.monotonic_ns(),'status':state,'truth':None if truth is None else [truth.x_m,truth.y_m,truth.z_m],'speed':oracle.recent_speed_mps()})+'\n');evidence.flush()
            return state
        def ctl(operation,*flags):
            deadline=time.monotonic()+3
            while True:
                result=subprocess.run([sys.executable,'-m','app.main','ctl','--profile',f'{kind}_sim',
                    '--control-socket',str(endpoint),operation,*flags],capture_output=True,text=True,timeout=4)
                response=json.loads(result.stdout)
                if not result.returncode and response['ok']:return response['result']
                # This exact error precedes Run/lease creation and any Arm request.
                if operation=='start' and response.get('error')=='reported local/global origin evidence unavailable' and time.monotonic()<deadline:
                    time.sleep(.1);continue
                raise RuntimeError(response)

        def wait(predicate,timeout):
            until=time.monotonic()+timeout
            while time.monotonic()<until:
                if endpoint.exists():
                    state=status()
                    if predicate(state):return state
                time.sleep(.1)
            raise TimeoutError('public state deadline')
        wait(lambda s:s['state']=='READY' and time.monotonic()>started+46,70)
        # No objects: explicit failure after bounded acquisition, no payload mutation.
        for index in range(1,4):service(owned,'remove','gz.msgs.Entity',f'name: "target_{index}" type: MODEL')
        wait(lambda s:not s['objects'],6)
        ctl('start','--mission','cuadc_demo')
        failed=wait(lambda s:s['task']['status']=='FAILED',90)
        assert failed['task']['error']=='target_acquisition_deadline'
        assert not failed['system_send'] and not failed['action_send'] and not failed['payload']['released']
        assert oracle.recent_speed_mps()<=.15
        report['checks']['no_target_failed']=True
        ctl('start','--mission','safe_recovery');wait(lambda s:s['task']['status']=='SUCCEEDED',40)
        # Restore an explicitly test-owned target then remove it during approach.
        model='<sdf version="1.9"><model name="target_1"><static>true</static><pose>1 1.7 0.05 0 0 0</pose><link name="marker"><visual name="v"><geometry><sphere><radius>0.1</radius></sphere></geometry></visual></link></model></sdf>'
        service(owned,'create','gz.msgs.EntityFactory','sdf: '+json.dumps(model))
        wait(lambda s:any(o['label']=='bucket_1' for o in s['objects']),8)
        ctl('start','--mission','cuadc_demo')
        wait(lambda s:s['task']['step']=='approach_release' and any(v and v['phase']=='TRANSMITTED' for key,v in s['task']['effects'].items() if s['task']['requests'][key]['effect_type']=='PoseTargetEffect' and ':approach_release:' in s['task']['requests'][key]['action_id']),60)
        service(owned,'remove','gz.msgs.Entity','name: "target_1" type: MODEL')
        failed=wait(lambda s:s['task']['status']=='FAILED',10)
        assert failed['task']['error']=='target_lost_or_expired',failed['task']['error']
        assert not failed['system_send'] and not failed['action_send'] and not failed['payload']['released']
        assert oracle.recent_speed_mps()<=.15
        assert any(v and v['phase']=='COMPLETED' for key,v in failed['task']['effects'].items() if failed['task']['requests'][key]['effect_type']=='StopMotionEffect' and ':approach_release:' in failed['task']['requests'][key]['action_id'])
        report['checks']['target_loss_stopped']=True
        ctl('start','--mission','safe_recovery');wait(lambda s:s['task']['status']=='SUCCEEDED',40)
        ctl('shutdown')
        assert app.wait(timeout=8)==0 and not endpoint.exists()
        owned.stop_process(app)
        report['passed']=True
    except Exception as exc:report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        try:owned.close()
        except Exception as exc:report['cleanup_error']=str(exc);report['passed']=False
        evidence.close()
        (directory/'summary.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--kind',choices=('copter',),required=True);parser.add_argument('--allow-send',action='store_true');parser.add_argument('--run-dir',type=Path)
    args=parser.parse_args()
    if not args.allow_send:parser.error('--allow-send required')
    install_signal_cleanup()
    result=run(args.run_dir or ROOT/'artifacts/simulation'/f'business-faults-{args.kind}-{uuid4().hex[:8]}',args.kind)
    print(json.dumps(result));return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())

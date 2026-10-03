"""Public Mission cancellation/stale-state fences with independent physical truth."""
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
from tests.simulation.faults import TcpFaultProxy


def run(directory,kind):
    directory.mkdir(parents=True,exist_ok=False)
    owned=OwnedSimulation(directory,kind)
    endpoint=directory/'app.sock'
    report={'passed':False,'checks':{}}
    proxy=None
    evidence=(directory/'status.jsonl').open('w')
    try:
        owned.start()
        oracle=GazeboTruthOracle(owned.world,owned.model)
        proxy=TcpFaultProxy(owned.port,directory/'proxy.jsonl')
        config=directory/'profile.toml'
        config.write_text((ROOT/f'simulation/profiles/{kind}.toml').read_text().replace('port = 5760',f'port = {proxy.port}'))
        started=time.monotonic()
        app=owned.start_process('application',[sys.executable,'-m','app.main','run','--profile',kind+'_sim','--config',str(config),'--control-socket',str(endpoint),'--allow-send'])
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
        def moving(s):
            return s['task']['step']=='goto_a' and any(v and v['phase']=='TRANSMITTED' for k,v in s['task']['effects'].items() if s['task']['requests'][k]['effect_type'] in ('PoseTargetEffect','TwistTargetEffect'))
        ctl('start','--mission','basic_route')
        wait(moving,50)
        ctl('cancel')
        stopped=wait(lambda s:s['task']['status'] in ('FAILED','CANCELLED'),8)
        assert stopped['task']['status']=='CANCELLED',stopped['task']['error']
        assert not stopped['system_send'] and not stopped['action_send']
        assert oracle.recent_speed_mps() <= (.1 if kind=='rover' else .15)
        assert any(v and v['phase']=='COMPLETED' for k,v in stopped['task']['effects'].items() if stopped['task']['requests'][k]['effect_type']=='StopMotionEffect')
        report['checks']['cancel_confirmed']=True
        ctl('start','--mission','safe_recovery')
        wait(lambda s:s['task']['status']=='SUCCEEDED',40)
        ctl('start','--mission','basic_route')
        moving_state=wait(moving,50)
        generation=moving_state['world_version']['generation']
        proxy.inject(drop_rx={'LOCAL_POSITION_NED','GLOBAL_POSITION_INT','ATTITUDE'})
        failed=wait(lambda s:s['task']['status']=='FAILED',12)
        assert not failed['system_send'] and not failed['action_send']
        report['checks']['stale_failed']=failed['task']['error']
        old_id=failed['task']['task_id']
        time.sleep(.3)
        tx_count=len(proxy.tx())
        proxy.inject(drop_rx=set())
        reconnected=wait(lambda s:s['state']=='READY' and s['world_version']['generation']!=generation,30)
        assert reconnected['task']['task_id']==old_id and reconnected['task']['status']=='FAILED'
        assert not reconnected['system_send'] and not reconnected['action_send']
        assert len(proxy.tx())==tx_count,'old run emitted after reconnect'
        report['checks']['reconnect_readonly']=True
        report['checks']['stop_results']=failed['task']['stops']
        ctl('start','--mission','safe_recovery')
        wait(lambda s:s['task']['status']=='SUCCEEDED',40)
        ctl('shutdown')
        assert app.wait(timeout=8)==0 and not endpoint.exists()
        owned.stop_process(app)
        report['passed']=True
    except Exception as exc:report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if proxy:proxy.close()
        try:owned.close()
        except Exception as exc:report['cleanup_error']=str(exc);report['passed']=False
        evidence.close()
        (directory/'summary.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--kind',choices=('copter','rover'),required=True);parser.add_argument('--allow-send',action='store_true');parser.add_argument('--run-dir',type=Path)
    args=parser.parse_args()
    if not args.allow_send:parser.error('--allow-send required')
    install_signal_cleanup()
    result=run(args.run_dir or ROOT/'artifacts/simulation'/f'mission-faults-{args.kind}-{uuid4().hex[:8]}',args.kind)
    print(json.dumps(result));return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())

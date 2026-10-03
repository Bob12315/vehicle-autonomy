"""Public App/CLI motion acceptance; independent Gazebo physical evidence."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
from app.control import request
from environments.resources import Environment
from tests.simulation.launch import ROOT, OwnedSimulation, install_signal_cleanup
from tests.simulation.oracle import GazeboTruthOracle


def run(directory,kind,mission='action_probe',repeats=1,*,objects=False):
    directory.mkdir(parents=True,exist_ok=False)
    owned=OwnedSimulation(directory,kind)
    endpoint=directory/'app.sock'
    evidence=(directory/'application-status.jsonl').open('w')
    report={'passed':False,'runs':[]}
    try:
        flags=[]
        if objects:
            from tests.simulation.object_fixture import add_objects
            sensor_path=add_objects(owned)
            flags += ['--sim-sensor-config',str(sensor_path)]
        if mission=='cuadc_demo':flags+=['--sim-payload']
        owned.start()
        oracle=GazeboTruthOracle(owned.world,owned.model)
        target_oracle=GazeboTruthOracle(owned.world,'target_1') if objects else None
        config=directory/'profile.toml'
        config.write_text((ROOT/f'simulation/profiles/{kind}.toml').read_text().replace('port = 5760',f'port = {owned.port}'))
        environment=Environment.load(ROOT/f'simulation/environments/{kind}.toml')
        bounds=json.loads((ROOT/'simulation/scenarios/acceptance-v1.json').read_text())[kind]
        started=time.monotonic()
        app=owned.start_process('application',[sys.executable,'-m','app.main','run','--profile',f'{kind}_sim',
            '--config',str(config),'--control-socket',str(endpoint),'--allow-send',*flags])

        def status():
            state=request(endpoint,'status')['result']
            truth=oracle.latest()
            if truth is not None:
                if time.monotonic_ns()-truth.host_received_ns>1_000_000_000:
                    raise RuntimeError('physical oracle stale')
                if abs(truth.x_m)>4.5 or abs(truth.y_m)>4.5:
                    raise RuntimeError('physical fence exceeded')
            evidence.write(json.dumps({'host_ns':time.monotonic_ns(),'status':state,
                'truth':None if truth is None else [truth.x_m,truth.y_m,truth.z_m,truth.yaw_rad],
                'truth_speed':oracle.recent_speed_mps() if truth else None})+'\n')
            evidence.flush()
            return state,truth

        def cli(operation,*flags):
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

        until=time.monotonic()+70
        latest=None
        while time.monotonic()<until:
            owned.assert_alive()
            if endpoint.exists():
                latest,truth=status()
                if latest['state']=='READY' and latest['localization'] and latest['environment']['origin_verified'] and latest['motion_warmup_remaining_ns']==0 and time.monotonic()>started+owned.profile.warmup_ns/1e9+1:
                    break
            time.sleep(.2)
        else:raise TimeoutError(f'fresh motion warmup: {latest}')
        origin=oracle.latest()
        initial_pose=latest['vehicle']['pose']['position']
        if origin is None:raise RuntimeError('independent truth unavailable')
        assert cli('status')['environment']['home_source']
        for iteration in range(repeats):
            task=cli('start','--mission',mission)
            entry={'task_id':task['task_id'],'steps':{},'effects':{}}
            report['runs'].append(entry)
            deadline=time.monotonic()+280
            while time.monotonic()<deadline:
                owned.assert_alive()
                state,truth=status()
                task=state['task']
                if task['status'] in ('FAILED','CANCELLED'):raise RuntimeError(f"{task['status']} step={task['step']} error={task['error']}")
                for step in task['steps']:
                    name=step['step']
                    if name in entry['steps']:continue
                    if step['reason']!='SUCCEEDED' or truth is None:raise RuntimeError(step)
                    record={'truth':[truth.x_m,truth.y_m,truth.z_m],'vehicle':state['vehicle'],'reason':step['reason']}
                    if name=='takeoff':
                        rise=truth.z_m-origin.z_m
                        if abs(rise-1.5)>bounds['takeoff_max_error_m']:raise RuntimeError(f'takeoff truth {rise}')
                        record['truth_rise_m']=rise
                    if name in ('goto_a','goto_b','home','search'):
                        point=next(p for p in environment.points if p.name==(
                            'A' if name in ('goto_a','search') else 'B' if name=='goto_b' else 'HOME_AIR' if kind=='copter' else 'HOME'))
                        target=(origin.x_m+point.position.x-initial_pose[0],origin.y_m+point.position.y-initial_pose[1])
                        error=math.hypot(truth.x_m-target[0],truth.y_m-target[1])
                        if error>bounds['goto_max_horizontal_error_m']:raise RuntimeError(f'{name} truth error {error}')
                        record['truth_error_m']=error
                    if name in ('goto_a','goto_b','home','hold','stop','search','inspect','approach_release'):
                        speed=oracle.recent_speed_mps()
                        if speed is None or speed>bounds['stop_max_horizontal_speed_mps']:
                            raise RuntimeError(f'{name} physical Stop {speed}')
                        record['truth_stop_speed_mps']=speed
                        stops=[value for key,value in task['effects'].items() if
                            task['requests'][key]['action_id']==f'{task["task_id"]}:{name}:1' and
                            task['requests'][key]['effect_type']=='StopMotionEffect']
                        if not stops or stops[-1]['phase']!='COMPLETED':raise RuntimeError('missing stop feedback barrier')
                    if name in ('inspect','approach_release'):
                        target_truth=target_oracle.latest()
                        error=math.hypot(truth.x_m-target_truth.x_m,truth.y_m-target_truth.y_m)
                        if error>(.3 if kind=='copter' else .75):raise RuntimeError(f'object approach truth error {error}')
                        record['object_truth_error_m']=error
                        if name=='approach_release':
                            completed=[v for key,v in task['effects'].items() if task['requests'][key]['effect_type']=='ReleasePayloadEffect' and v['phase']=='COMPLETED']
                            markers=[o for o in state['objects'] if o['label']=='sim_payload_released']
                            if len(completed)!=1 or len(markers)!=1 or not state['payload']['released']:raise RuntimeError('payload physical simulation state missing')
                            record['payload_state']=state['payload'];record['marker']=markers[0]
                    if name=='land'  and (state['vehicle']['armed'] or truth.z_m>origin.z_m+.2):
                        raise RuntimeError('land ground/disarm unconfirmed')
                    entry['steps'][name]=record
                if task['status']=='SUCCEEDED':
                    if state['system_send'] or state['action_send'] or state['vehicle']['armed']:
                        raise RuntimeError('finished mission retained authority or armed state')
                    entry['effects']=task['effects']
                    entry['requests']=task['requests']
                    if not entry['steps']:raise RuntimeError('empty completed mission')
                    break
                time.sleep(.2)
            else:raise TimeoutError(f'{mission} deadline')
        if mission=='cuadc_demo':
            result=subprocess.run([sys.executable,'-m','app.main','ctl','--profile',kind+'_sim','--control-socket',str(endpoint),'start','--mission','cuadc_demo'],capture_output=True,text=True,timeout=4)
            if result.returncode==0:raise RuntimeError('consumed payload was silently reset')
            report['consumed_payload_rejected']=True
        cli('shutdown')
        if app.wait(timeout=8)!=0 or endpoint.exists():raise RuntimeError('application cleanup failed')
        owned.stop_process(app)
        report['passed']=True
    except Exception as exc:
        report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        try:owned.close()
        except Exception as exc:report['cleanup_error']=str(exc);report['passed']=False
        evidence.close()
        (directory/'summary.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--kind',choices=('copter','rover'),required=True)
    parser.add_argument('--mission',default='action_probe')
    parser.add_argument('--objects',action='store_true')
    parser.add_argument('--repeats',type=int,choices=(1,2),default=1)
    parser.add_argument('--allow-send',action='store_true')
    parser.add_argument('--run-dir',type=Path)
    args=parser.parse_args()
    if not args.allow_send:parser.error('--allow-send required')
    install_signal_cleanup()
    result=run(args.run_dir or ROOT/'artifacts/simulation'/f'autonomy-{args.kind}-{uuid4().hex[:8]}',
               args.kind,args.mission,args.repeats,objects=args.objects)
    print(json.dumps({'passed':result['passed'],'error':result.get('error'),'runs':len(result['runs'])}))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

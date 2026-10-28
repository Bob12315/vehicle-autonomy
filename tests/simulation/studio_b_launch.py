"""Full launcher smoke: registered Agent and templates, without any Run/SEND."""
import argparse,json,subprocess,sys,time
from pathlib import Path
from urllib.request import Request,urlopen


def run(path,port):
    if path.exists():raise ValueError('fresh launch evidence directory required')
    path.parent.mkdir(parents=True,exist_ok=True);log=path.parent/(path.name+'.launcher.log')
    result=dict(passed=False,environment='actual visualization launcher + owned SITL/Gazebo + Desktop Agent; deployment SEND disabled')
    process=None
    with log.open('w') as output:
        try:
            process=subprocess.Popen([sys.executable,'-m','vehicle_autonomy.app.visualization.launch','--kind','copter','--studio-demo',
                '--web-port',str(port),'--run-dir',str(path)],stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            deadline=time.monotonic()+140;ready=False
            def api(route):
                key=(path/'simulation/web-token.private').read_text().strip()
                with urlopen(Request('http://127.0.0.1:'+str(port)+route,headers={'Authorization':'Bearer '+key}),timeout=4) as response:return json.load(response)['result']
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('launcher stopped before readiness; inspect retained launcher log')
                try:
                    catalog=api('/api/studio-b/catalog');library=api('/api/studio-b/library');snapshot=api('/api/studio/state')
                    console=api('/api/console/state');agents=(console.get('tools') or {}).get('agents',[])
                    ready=any(a.get('connected') for a in agents)
                    if ready:break
                except (OSError,ValueError):pass
                time.sleep(.2)
            if not ready:raise TimeoutError('full stack/Agent readiness deadline')
            if not any(a['name']=='Sim.PreflightCheck' for a in catalog['actions']) or 'CUADC_MultiTarget_Simulation' not in library['templates']:raise AssertionError('software example flag did not reach the actual backend')
            if snapshot['actions'] or snapshot['missions']:raise AssertionError('startup unexpectedly executed an Action/Mission')
            if any(v.get('deployment_send') for v in snapshot['vehicles']):raise AssertionError('default deployment SEND unexpectedly enabled')
            result.update(passed=True,registered_agent_count=sum(a.get('connected',False) for a in agents),mission_count=0,action_count=0,templates=list(library['templates']))
        except BaseException as exc:result['error']=type(exc).__name__+': '+str(exc);raise
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=40)
                except subprocess.TimeoutExpired:
                    # The owning launcher handles its own child manifests. A
                    # failed cleanup stays a failed test, never a PASS marker.
                    result['passed']=False;result['cleanup_error']='owning launcher did not exit';process.kill();process.wait(timeout=5)
            result['launcher_exit_code']=None if process is None else process.returncode
            if path.exists():(path/'studio-launch-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    if not result['passed']:raise AssertionError('launcher cleanup failed')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True,type=Path);parser.add_argument('--port',default=18881,type=int)
    args=parser.parse_args();print(json.dumps(run(args.run_dir.resolve(),args.port)))

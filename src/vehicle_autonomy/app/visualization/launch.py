"""One owned simulation + current Web + automatically connected Desktop Agent.

No tool, mission, Arm or movement is automatically launched. The Web operator
chooses RViz/Workspace and confirms vehicle actions separately. Default read-only.
"""
import argparse,json,os,signal,socket,subprocess,sys,time
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from uuid import uuid4

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.web.server import load_token
from vehicle_autonomy.app.tools.builtins import ROS_KEYS,registry
from vehicle_autonomy.app.tools.schema import context,manifest
from .registry import configure
from .source import NoRedirect


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kind',choices=('rover','copter','plane'),required=True)
    p.add_argument('--run-dir',type=Path);p.add_argument('--allow-send',action='store_true');p.add_argument('--web-port',type=int)
    p.add_argument('--domain-id',type=int,default=91);p.add_argument('--namespace');p.add_argument('--ros-wrapper',type=Path)
    p.add_argument('--duration',type=float,help='optional finite diagnostic run, measured after backend startup')
    a=p.parse_args();root=resource_root();port=a.web_port or {'rover':8780,'copter':8781,'plane':8782}[a.kind]
    if not 1024<=port<=65535 or a.duration is not None and a.duration<=0:p.error('bounded port and positive duration required')
    ctx=context(dict(vehicle_id=a.kind,vehicle_type=a.kind,environment='simulation',ros_namespace=a.namespace or '/'+a.kind,
        ros_domain_id=a.domain_id,mavlink_profile='monitor'))
    wrapper=a.ros_wrapper or root/'scripts/with_ros2.sh'
    result=subprocess.run([str(wrapper.resolve()),'/usr/bin/env','-0'],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
    if len(result.stdout)>131072:raise ValueError('ROS environment budget exceeded')
    full=dict(s.decode().split('=',1) for s in result.stdout.split(b'\0') if b'=' in s);ros={k:full[k] for k in ROS_KEYS if k in full}
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',port))  # Fail before spawning, never kill an existing listener.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));agent_port=probe.getsockname()[1]
    directory=(a.run_dir or Path('runtime/visualization')/f'{a.kind}-{uuid4().hex[:12]}').expanduser().resolve();directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    simulation=directory/'simulation';feed=directory/'visualization.private';agent_key=directory/'desktop.private';load_token(feed);load_token(agent_key)
    cfg=directory/'source.json';cfg.write_text(json.dumps(dict(schema=1,url='http://127.0.0.1:'+str(port),token_file=str(feed),use_sim_time=False)))
    allow=directory/'agents.json';allow.write_text(json.dumps(dict(schema=1,agents=dict(desktop=dict(token_file=str(agent_key))))))
    value=configure(registry(ros_env=ros),cfg,ros,owned_simulation=simulation/'manifest.json')
    for tool in value['tools']:manifest(tool)
    registry_file=directory/'registry.json';registry_file.write_text(json.dumps(value))
    launcher=agent=None;logs=[];closed=False
    def stop(*_):
        nonlocal closed
        closed=True
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    http=build_opener(ProxyHandler({}),NoRedirect())
    def api(path,payload):
        key=(simulation/'web-token.private').read_text().strip()
        headers={'Authorization':'Bearer '+key,'X-VAF-CSRF':key,'X-VAF-Request-ID':uuid4().hex,'Content-Type':'application/json'}
        with http.open(Request('http://127.0.0.1:'+str(port)+path,json.dumps(payload).encode(),headers),timeout=3) as response:
            body=json.load(response)
            if not body['ok']:raise ValueError('configuration request rejected')
            return body['result']
    try:
        command=[sys.executable,'-m','vehicle_autonomy.app.bootstrap.qgc_simulation','--kind',a.kind,'--headless','--source-time-sync',
            '--web-port',str(port),'--tool-agents',str(allow),'--tool-port',str(agent_port),'--visualization-token-file',str(feed),'--run-dir',str(simulation),
            '--allow-send' if a.allow_send else '--read-only']
        log=(directory/'simulation.log').open('w');logs.append(log);launcher=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+100
        while not closed:
            if launcher.poll() is not None:raise RuntimeError('owned simulation startup failed; inspect simulation.log')
            try:
                ready=json.loads((simulation/'session.json').read_text()).get('ready')
                if ready:break
            except (OSError,ValueError):pass
            if time.monotonic()>deadline:raise TimeoutError('owned visualization simulation startup')
            time.sleep(.1)
        if closed:return
        api('/api/settings/context',ctx)
        log=(directory/'desktop-agent.log').open('w');logs.append(log)
        agent=subprocess.Popen([sys.executable,'-m','vehicle_autonomy.app.tools.agent','--id','desktop','--role','desktop','--backend','http://127.0.0.1:'+str(agent_port),
            '--token-file',str(agent_key),'--registry',str(registry_file),'--data-dir',str(directory/'agent-state')],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        # Preparing definitions is configuration, never a tool or vehicle launch.
        started=time.monotonic();saved=False
        print('Web: http://127.0.0.1:'+str(port)+'/control',flush=True)
        print('Login key file: '+str(simulation/'web-token.private'),flush=True)
        print('Desktop Agent connects automatically. Click Open RViz2; no automatic motion. Ctrl+C closes only this owned deployment.',flush=True)
        while not closed:
            if launcher.poll() is not None:raise RuntimeError('owned simulation exited; inspect simulation.log')
            if not saved:
                try:
                    # Template resolution after registration, so profiles/hosts
                    # are actual registered capabilities rather than placeholders.
                    with http.open(Request('http://127.0.0.1:'+str(port)+'/api/console/state',headers={'Authorization':'Bearer '+(simulation/'web-token.private').read_text().strip()}),timeout=2) as response:state=json.load(response)['result']
                    if any(v['connected'] for v in state['tools']['agents']):
                        for preset in ('simulation-visualization','rover-navigation' if a.kind=='rover' else 'uav-visualization'):
                            definition=api('/api/workspaces/template',dict(template_id=preset,context=ctx));api('/api/workspaces/save',dict(spec=definition))
                        saved=True;print('Matching Workspace definitions saved; launch is explicit in Web UI.',flush=True)
                except (OSError,ValueError,KeyError):pass
            if a.duration is not None and time.monotonic()-started>=a.duration:break
            time.sleep(.2)
    finally:
        # Agent disappearance never causes automatic vehicle cancellation while
        # this loop is running; shutdown here is an explicit owner exit.
        for process in (agent,launcher):
            if process and process.poll() is None:process.terminate()
        for process in (agent,launcher):
            if process:process.wait(45)
        for log in logs:log.close()
        feed.unlink(missing_ok=True);agent_key.unlink(missing_ok=True)
        (directory/'launcher-closed.json').write_text(json.dumps(dict(closed=True,temporary_visualization_and_agent_credentials_removed=True)))


if __name__=='__main__':main()

"""Build/install a wheel in a fresh venv and run both deployed CLIs from /tmp."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request,urlopen
from uuid import uuid4

from vehicle_autonomy.app.web.server import load_token
from .helpers import CTX,wait
from .test_workspaces import component,spec


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True)
    a=p.parse_args();root=a.run_dir.resolve();root.mkdir(parents=True,exist_ok=False,mode=0o700)
    source=Path(__file__).resolve().parents[2];report=dict(passed=False,source='fresh independent wheel venv; actual backend/Agent/Workspace/process; cwd=/tmp')
    env=dict(os.environ);env.pop('PYTHONPATH',None);env.pop('VAF_RESOURCE_ROOT',None)
    log=(root/'packaging.log').open('w');children=[];handles=[]
    def command(argv,**kw):return subprocess.run(argv,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180,**kw)
    def port():
        with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
    try:
        command([sys.executable,'-m','pip','wheel',str(source),'--no-deps','--wheel-dir',str(root/'wheels')],cwd='/tmp')
        wheel=next((root/'wheels').glob('*.whl'));command([sys.executable,'-m','venv',str(root/'env')],cwd='/tmp')
        python=root/'env/bin/python'
        command([str(python),'-m','pip','install',str(wheel)+'[mavlink]','-r',str(source/'requirements-vision.txt')],cwd='/tmp')
        check='''import json,sys
from pathlib import Path
import vehicle_autonomy
from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.tools.builtins import registry
from vehicle_autonomy.app.tools.agent import Agent
from vehicle_autonomy.app.web.mission_control import MissionControl
assert Path(vehicle_autonomy.__file__).is_relative_to(sys.prefix)
assert (resource_root()/'configs/tools/lab.sdf').is_file()
assert len(registry()['tools'])==6
assert 'rclpy' not in sys.modules
print(json.dumps({'origin':vehicle_autonomy.__file__,'resources':str(resource_root()),'ros_imported':False}))
'''
        result=subprocess.run([str(python),'-c',check],env=env,cwd='/tmp',text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=True)
        report['import']=json.loads(result.stdout)
        for name in ('vehicle-autonomy-console','vehicle-autonomy-tool-agent','vehicle-autonomy-tool-registry'):command([str(root/'env/bin'/name),'--help'],cwd='/tmp')
        web_port,agent_port=port(),port();token=load_token(root/'web.private');agent_token=load_token(root/'agent.private')
        (root/'allowlist.json').write_text(json.dumps(dict(schema=1,agents={'desktop':dict(token_file=str(root/'agent.private'))})))
        probe=dict(argv=[str(python),'-c','print("READY")'],contains=['READY'],timeout_s=1)
        fixture=dict(schema=1,id='wheel-fixture',name='wheel-fixture',type='service',version='fixture',supported_os=['linux'],dependencies=[],install_detection=[],stop_strategy='owned_process_group',integrations=[],agent_requirements=[],permissions=[],profiles={'default':dict(argv=[str(python),'-u','-c','import time;print("wheel fixture",flush=True);time.sleep(120) # '+uuid4().hex],env={},health=probe,ready=probe,connection=dict(kind='test',description='actual installed wheel process fixture'),stop_timeout_s=.2)})
        (root/'registry.json').write_text(json.dumps(dict(schema=1,tools=[fixture])))
        def spawn(name,args):
            handle=(root/(name+'.log')).open('w');handles.append(handle)
            child=subprocess.Popen([str(root/'env/bin'/name),*args],cwd='/tmp',env=env,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True);children.append(child)
        spawn('vehicle-autonomy-console',['--port',str(web_port),'--token-file',str(root/'web.private'),'--data-dir',str(root/'backend'),'--tool-agents',str(root/'allowlist.json'),'--tool-port',str(agent_port)])
        spawn('vehicle-autonomy-tool-agent',['--id','desktop','--token-file',str(root/'agent.private'),'--registry',str(root/'registry.json'),'--data-dir',str(root/'agent'),'--backend',f'http://127.0.0.1:{agent_port}'])
        base=f'http://127.0.0.1:{web_port}'
        def api(path,payload=None):
            headers={'Authorization':'Bearer '+token}
            if payload is not None:headers.update({'Content-Type':'application/json','X-VAF-CSRF':token,'X-VAF-Request-ID':uuid4().hex})
            with urlopen(Request(base+path,None if payload is None else json.dumps(payload).encode(),headers),timeout=3) as r:return json.load(r)['result']
        def registered():
            try:return api('/api/console/state')['tools']['agents']
            except Exception:return None
        wait(registered,20)
        for path in ('/console','/tool-console.js','/tool-console.css'):
            with urlopen(base+path,timeout=3) as response:assert response.status==200
        api('/api/workspaces/save',dict(spec=spec('wheel-workspace',components=[component('wheel-fixture',timeout_s=15)])))
        run=api('/api/workspaces/launch',dict(id='wheel-workspace'))
        wait(lambda:api('/api/console/state')['tools']['workspaces']['runs'][0]['state']=='READY',20)
        api('/api/workspaces/stop',dict(run_id=run['id']))
        wait(lambda:api('/api/console/state')['tools']['workspaces']['runs'][0]['state']=='STOPPED',20)
        report.update(passed=True,wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),wheel=str(wheel),cli_help=True,static_resources=True,workspace_lifecycle=True,vehicle_connections=0)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:child.wait(25)
                except subprocess.TimeoutExpired:child.kill();child.wait()
        for handle in handles:handle.close()
        log.close();(root/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':main()

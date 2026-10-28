"""Actual independent backend and Agent CLI processes, including crash/reboot."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import Request,urlopen
from uuid import uuid4

from vehicle_autonomy.app.web.server import load_token
from .helpers import CTX,tool,wait
from .test_workspaces import component,spec


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',required=True,type=Path)
    a=p.parse_args();root=a.run_dir.resolve();root.mkdir(parents=True,exist_ok=False,mode=0o700)
    def port():
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]
    web_port,agent_port=port(),port();web_token=load_token(root/'web.private');agent_token=load_token(root/'agent.private')
    (root/'allowlist.json').write_text(json.dumps(dict(schema=1,agents={'desktop':dict(token_file=str(root/'agent.private'))})))
    (root/'registry.json').write_text(json.dumps(dict(schema=1,tools=[tool()])))
    handles=[];children=[];report=dict(passed=False,source='independent CLI processes; real HTTP and owned process fixture')
    def spawn(name,command):
        handle=(root/(name+'.log')).open('w');handles.append(handle)
        child=subprocess.Popen([sys.executable,'-m',*command],stdout=handle,stderr=subprocess.STDOUT,start_new_session=True);children.append(child);return child
    def start_agent():return spawn('agent-'+uuid4().hex[:5],['vehicle_autonomy.app.tools.agent','--id','desktop','--backend',f'http://127.0.0.1:{agent_port}','--token-file',str(root/'agent.private'),'--registry',str(root/'registry.json'),'--data-dir',str(root/'agent-state')])
    def api(path,payload=None):
        headers={'Authorization':'Bearer '+web_token}
        if payload is not None:headers.update({'Content-Type':'application/json','X-VAF-CSRF':web_token,'X-VAF-Request-ID':uuid4().hex})
        with urlopen(Request(f'http://127.0.0.1:{web_port}'+path,None if payload is None else json.dumps(payload).encode(),headers),timeout=3) as response:return json.load(response)['result']
    try:
        backend_command=['vehicle_autonomy.app.web.mission_cli','--port',str(web_port),'--token-file',str(root/'web.private'),'--data-dir',str(root/'backend'),'--tool-agents',str(root/'allowlist.json'),'--tool-port',str(agent_port)]
        backend=spawn('backend',backend_command)
        def available():
            try:return api('/api/console/state')
            except Exception:return None
        wait(available)
        agent=start_agent();wait(lambda:api('/api/console/state')['tools']['agents'])
        api('/api/tools/operation',dict(agent_id='desktop',tool_id='fixture',profile_id='default',operation='launch',context=CTX))
        def ready():
            value=api('/api/console/state')['tools']['agents'][0]['tools'][0]['instance']
            return value if value and value['ready'] else None
        instance=wait(ready);old_boot=api('/api/console/state')['tools']['agents'][0]['boot_id']
        value=spec('persistent-workspace',components=[component('fixture',timeout_s=15)])
        api('/api/workspaces/save',dict(spec=value));run=api('/api/workspaces/launch',dict(id=value['id']))
        wait(lambda:api('/api/console/state')['tools']['workspaces']['runs'][0]['state']=='READY')
        backend.terminate();backend.wait(20)
        assert Path(f"/proc/{instance['pid']}").exists(),'backend shutdown stopped a live Agent tool'
        backend=spawn('backend-restarted',backend_command)
        def synced():
            state=available()
            return state if state and state['tools']['agents'] and state['tools']['agents'][0]['connected'] else None
        state=wait(synced,12);recovered=state['tools']['workspaces']['runs'][0]
        assert recovered['state']=='UNKNOWN' and recovered['recovering']
        assert state['tools']['agents'][0]['tools'][0]['instance']['instance_id']==instance['instance_id']
        api('/api/workspaces/reconcile',dict(run_id=run['id'],decision='resume',instances={'fixture':instance['instance_id']}))
        wait(lambda:api('/api/console/state')['tools']['workspaces']['runs'][0]['state']=='READY')
        api('/api/workspaces/stop',dict(run_id=run['id']))
        wait(lambda:api('/api/console/state')['tools']['workspaces']['runs'][0]['state']=='STOPPED')
        assert Path(f"/proc/{instance['pid']}").exists(),'Workspace stopped a manual baseline service'
        # Kill the private supervisor, while the Agent remains alive. The
        # per-instance marker/pidfd recovery must clean the actual owned tool.
        supervisor=int(Path(f"/proc/{instance['pid']}/stat").read_text().rsplit(')',1)[1].split()[1])
        assert int(Path(f'/proc/{supervisor}/stat').read_text().rsplit(')',1)[1].split()[1])==agent.pid
        os.kill(supervisor,signal.SIGKILL)
        wait(lambda:(lambda i:i and i['state']=='FAILED' and i['cleanup_confirmed'])(api('/api/console/state')['tools']['agents'][0]['tools'][0]['instance']))
        wait(lambda:not Path(f"/proc/{instance['pid']}").exists())
        api('/api/tools/operation',dict(agent_id='desktop',tool_id='fixture',profile_id='default',operation='restart',context=CTX))
        instance=wait(ready)
        agent.kill();agent.wait(3);wait(lambda:not Path(f"/proc/{instance['pid']}").exists())
        wait(lambda:not api('/api/console/state')['tools']['agents'][0]['connected'])
        replacement=start_agent()
        wait(lambda:(lambda v:v['connected'] and v['boot_id']!=old_boot)(api('/api/console/state')['tools']['agents'][0]))
        state=api('/api/console/state');assert state['vehicles']==[] and state['tools']['agents'][0]['tools'][0]['instance'] is None
        report.update(passed=True,backend_restart_preserved_tool=True,workspace_reconciled=True,manual_baseline_preserved=True,
            supervisor_sigkill_cleanup=True,crash_cleanup=True,new_boot_reconnected=True,no_auto_restart=True,vehicle_actions=0)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:child.wait(15)
                except subprocess.TimeoutExpired:child.kill();child.wait()
        for handle in handles:handle.close()
        for log in root.glob('*.log'):
            assert web_token not in log.read_text() and agent_token not in log.read_text()
        (root/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':main()

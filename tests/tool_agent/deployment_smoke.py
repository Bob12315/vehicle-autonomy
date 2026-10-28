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
        backend=spawn('backend',['vehicle_autonomy.app.web.mission_cli','--port',str(web_port),'--token-file',str(root/'web.private'),'--data-dir',str(root/'backend'),'--tool-agents',str(root/'allowlist.json'),'--tool-port',str(agent_port)])
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
        agent.kill();agent.wait(3);wait(lambda:not Path(f"/proc/{instance['pid']}").exists())
        wait(lambda:not api('/api/console/state')['tools']['agents'][0]['connected'])
        replacement=start_agent()
        wait(lambda:(lambda v:v['connected'] and v['boot_id']!=old_boot)(api('/api/console/state')['tools']['agents'][0]))
        state=api('/api/console/state');assert state['vehicles']==[] and state['tools']['agents'][0]['tools'][0]['instance'] is None
        report.update(passed=True,crash_cleanup=True,new_boot_reconnected=True,no_auto_restart=True,vehicle_actions=0)
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

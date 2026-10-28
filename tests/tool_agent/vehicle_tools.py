"""One actual owned Rover Web center: telemetry, Tool Agent, Workspace and Mission."""
from tests.browser_auth import login
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request,urlopen
from uuid import uuid4

from vehicle_autonomy.app.web.server import load_token
from .helpers import tool,wait
from .test_workspaces import component,spec


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True)
    a=p.parse_args();root=a.run_dir.resolve();root.mkdir(parents=True,exist_ok=False,mode=0o700)
    def port(kind=socket.SOCK_STREAM):
        with socket.socket(socket.AF_INET,kind) as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
    web_port,agent_port,qgc_port=port(),port(),port(socket.SOCK_DGRAM)
    agent_token=load_token(root/'agent.private')
    (root/'allowlist.json').write_text(json.dumps(dict(schema=1,agents={'desktop':dict(token_file=str(root/'agent.private'))})))
    (root/'registry.json').write_text(json.dumps(dict(schema=1,tools=[tool()])))
    logs=[];children=[];report=dict(passed=False,source='actual signed Rover SITL/Gazebo Web + independent Agent + real process fixture; no hardware')
    def spawn(name,argv):
        handle=(root/(name+'.log')).open('w');logs.append(handle)
        process=subprocess.Popen([sys.executable,'-m',*argv],stdout=handle,stderr=subprocess.STDOUT,start_new_session=True);children.append(process);return process
    try:
        launcher=spawn('simulation',['vehicle_autonomy.app.bootstrap.qgc_simulation','--kind','rover','--headless','--read-only','--qgc-port',str(qgc_port),'--web-port',str(web_port),
            '--run-dir',str(root/'simulation'),'--tool-agents',str(root/'allowlist.json'),'--tool-port',str(agent_port),'--tool-data-dir',str(root/'persistent-tools')])
        def session_ready():
            if launcher.poll() is not None:raise RuntimeError('simulation launcher exited; see simulation.log')
            try:
                value=json.loads((root/'simulation/session.json').read_text());return value if value.get('ready') else None
            except (FileNotFoundError,json.JSONDecodeError):return None
        session=wait(session_ready,100);token=Path(session['token_file']).read_text().strip();base=f'http://127.0.0.1:{web_port}'
        def api(path,payload=None):
            headers={'Authorization':'Bearer '+token}
            if payload is not None:headers.update({'Content-Type':'application/json','X-VAF-CSRF':token,'X-VAF-Request-ID':uuid4().hex})
            with urlopen(Request(base+path,None if payload is None else json.dumps(payload).encode(),headers),timeout=4) as response:return json.load(response)['result']
        agent=spawn('agent',['vehicle_autonomy.app.tools.agent','--id','desktop','--token-file',str(root/'agent.private'),'--registry',str(root/'registry.json'),'--data-dir',str(root/'agent-state'),'--backend',f'http://127.0.0.1:{agent_port}'])
        wait(lambda:api('/api/console/state')['tools']['agents'])
        api('/api/workspaces/save',dict(spec=spec('vehicle-tools',components=[component('fixture',timeout_s=15)])))
        api('/api/workspaces/launch',dict(id='vehicle-tools'))
        wait(lambda:api('/api/console/state')['tools']['workspaces']['runs'][0]['state']=='READY',20)
        wait(lambda:api('/api/console/state')['vehicles'][0]['fresh'],30)
        initial=api('/api/console/state');vehicle=initial['vehicles'][0]
        assert vehicle['id']=='rover' and vehicle['environment']=='simulation' and vehicle['armed'] is False
        assert all(vehicle['authority'][k] is False for k in ('system_send','action_send','deployment_send'))
        report['initial']=initial
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(viewport={'width':1500,'height':1050});login(page,base,token,'/console')
                expect(page.locator('#metric-connection')).to_have_text('Connected')
                page.screenshot(path=str(root/'unified-dashboard.png'),full_page=True,mask=[],mask_color='#243d4a')
                page.locator('[data-view=tools]').click();expect(page.locator('[data-tool="desktop:fixture"] td:nth-child(4) .badge')).to_have_text('Ready')
                page.screenshot(path=str(root/'unified-tools.png'),full_page=True,mask=[],mask_color='#243d4a')
            finally:browser.close()
        graph=dict(schema_version=1,id='tool-loss-wait',name='Tool isolation wait',version='1.0.0',target='rover',root='wait',nodes=[dict(id='wait',type='Wait',duration_s=2.)])
        mission=api('/api/missions/start',dict(spec=graph,allow_send=False))
        wait(lambda:api('/api/studio/state')['missions'][-1]['state']=='RUNNING')
        tool_pid=api('/api/console/state')['tools']['agents'][0]['tools'][0]['instance']['pid']
        agent.kill();agent.wait(3);wait(lambda:not Path(f'/proc/{tool_pid}').exists())
        wait(lambda:api('/api/studio/state')['missions'][-1]['state']=='SUCCEEDED')
        wait(lambda:not api('/api/console/state')['tools']['agents'][0]['connected'])
        final=api('/api/console/state');vehicle=final['vehicles'][0]
        assert vehicle['fresh'] and vehicle['connected'] and vehicle['armed'] is False
        assert not vehicle['authority']['system_send'] and not vehicle['authority']['action_send'] and not vehicle['authority']['deployment_send']
        assert api('/api/studio/state')['actions']==[]
        report.update(passed=True,final=final,mission_state='SUCCEEDED',tool_crash_cleanup=True,vehicle_actions=0,send_gates=False,
            persistent_tool_state=(root/'persistent-tools/workspaces.json').is_file())
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:child.wait(30)
                except subprocess.TimeoutExpired:child.kill();child.wait()
        for handle in logs:handle.close()
        (root/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('passed','source','mission_state','tool_crash_cleanup','vehicle_actions','send_gates','persistent_tool_state')}))


if __name__=='__main__':main()

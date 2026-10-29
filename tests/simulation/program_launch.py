"""Actual one-click scripts, signed Web state, receive-only QGC and cleanup.

--motion additionally uses real Chrome and independent Gazebo pose truth for
Rover forward/turn/stop/Goto/ReturnHome. No test bypasses the Action SEND gate.
--tool-registry tests browser controls and a native ROS2 Tool Agent for any kind.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from urllib.request import Request, urlopen
from uuid import uuid4

from pymavlink.dialects.v20 import ardupilotmega as mav

ROOT = Path(__file__).resolve().parents[2]
TERMINAL = {'SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN'}


def run(kind, directory, *, motion=False, gui=False, read_only=False, http_controls=False, tool_registry=None,visualization=False,visualization_extended=False,visualization_lifecycle_only=False):
    if motion and kind != 'rover':raise ValueError('motion acceptance is currently Rover only')
    directory = directory.resolve();directory.parent.mkdir(parents=True,exist_ok=True)
    port = {'rover':18880,'copter':18881,'plane':18882}[kind]
    if (motion or http_controls or tool_registry) and read_only:raise ValueError('motion requires explicit deployment authorization')
    result = dict(kind=kind,motion=motion,gui=gui,read_only=read_only,passed=False)
    launcher = None;tools = None
    if tool_registry:
        from tests.simulation.web_ui_controls import ToolAcceptance
        if visualization:
            from tests.simulation.visualization import VisualizationAcceptance
            tools=VisualizationAcceptance(directory.parent/(directory.name+'-tools'),tool_registry,kind,extended=visualization_extended,lifecycle_only=visualization_lifecycle_only)
        else:tools = ToolAcceptance(directory.parent/(directory.name+'-tools'),tool_registry)
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as monitor:
        monitor.bind(('127.0.0.1',0));monitor.settimeout(.05)
        qgc_port = monitor.getsockname()[1]
        command = [str(ROOT/f'scripts/start_{kind}_sim.sh'),'--run-dir',str(directory),
                   '--web-port',str(port),'--qgc-port',str(qgc_port)]
        if not gui:command.append('--headless')
        if read_only:command.append('--read-only')
        if tools:command.extend(tools.arguments())
        with (directory.parent/(directory.name+'-launcher.log')).open('w') as log:
            try:
                launcher = subprocess.Popen(command,cwd='/tmp',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                end = time.monotonic()+100
                while True:
                    if launcher.poll() is not None:raise RuntimeError('launcher exited before Web startup')
                    try:
                        manifest = json.loads((directory/'session.json').read_text())
                        if manifest.get('ready'):break
                    except (FileNotFoundError,json.JSONDecodeError):pass
                    if time.monotonic()>end:raise TimeoutError('one-click Web startup')
                    time.sleep(.1)
                token = Path(manifest['token_file']).read_text().strip()
                base = f'http://127.0.0.1:{port}'
                def api(path,payload=None):
                    headers = {'Authorization':'Bearer '+token}
                    data = None
                    if payload is not None:
                        headers.update({'Content-Type':'application/json','X-VAF-CSRF':token,'X-VAF-Request-ID':str(uuid4())})
                        data=json.dumps(payload).encode()
                    with urlopen(Request(base+path,data,headers),timeout=5) as response:value=json.load(response)
                    if not value['ok']:raise AssertionError(value['error'])
                    return value['result']
                # Real initialized state, not merely an HTTP listener or interface.
                end = time.monotonic()+60
                while True:
                    snapshot = api('/api/studio/state');vehicle=snapshot['vehicles'][0]
                    assert not vehicle['fault'] and not snapshot['fault']
                    if vehicle['fresh_vehicle_state'] and vehicle['verified_frames']>0:break
                    if time.monotonic()>end:raise TimeoutError('fresh authenticated vehicle state')
                    time.sleep(.1)
                assert vehicle['kind']==kind and vehicle['owned_simulation']
                assert vehicle['deployment_send']==(not read_only) and not vehicle['system_send'] and not vehicle['action_send']
                assert not snapshot['actions'] and not snapshot['missions'] and not manifest['phase5']
                result['initial_state']={k:vehicle[k] for k in ('kind','session_id','verified_frames','fresh_vehicle_state','system_send','action_send','deployment_send')}
                assert {p['name'] for p in json.loads((directory/'manifest.json').read_text())['processes']}=={'sitl','gazebo'}
                # Reject a command without its individual SEND, despite deployment
                # authorization. The framework must never enter a writing scope.
                denied=api('/api/manual/action',dict(name='Arm',target=kind,parameters={}))
                end=time.monotonic()+5
                while True:
                    final=next(a for a in api('/api/instances') if a['id']==denied['id'])
                    if final['state'] in TERMINAL:break
                    if time.monotonic()>end:raise TimeoutError('default Action SEND rejection')
                    time.sleep(.1)
                assert final['state']=='REJECTED'
                result['default_action_send']='REJECTED'
                if read_only:
                    denied=api('/api/manual/action',dict(name='Arm',target=kind,parameters={},allow_send=True))
                    end=time.monotonic()+5
                    while True:
                        final=next(a for a in api('/api/instances') if a['id']==denied['id'])
                        if final['state'] in TERMINAL:break
                        if time.monotonic()>end:raise TimeoutError('deployment SEND rejection')
                        time.sleep(.1)
                    assert final['state']=='REJECTED'
                    result['read_only_action_send']='REJECTED'
                parser=mav.MAVLink(None);parser.robust_parsing=True
                seen=set();source=None;end=time.monotonic()+4
                while time.monotonic()<end:
                    try:raw,source=monitor.recvfrom(65535)
                    except socket.timeout:continue
                    for message in parser.parse_buffer(raw) or []:
                        if message.get_type()=='BAD_DATA':continue
                        assert message.get_srcSystem()==manifest['system_id']
                        wire=message.get_msgbuf()
                        assert wire[0]==0xfd and wire[2]&1  # wire signed, display parser has no secret key
                        seen.add(message.get_type())
                    if {'HEARTBEAT','ATTITUDE','GLOBAL_POSITION_INT'}<=seen:break
                assert {'HEARTBEAT','ATTITUDE','GLOBAL_POSITION_INT'}<=seen
                # Valid read request would receive PARAM_VALUE on a writable GCS
                # link. It must have no route through this monitor back to AP.
                peer=mav.MAVLink(None,srcSystem=255,srcComponent=190)
                monitor.sendto(peer.param_request_read_encode(manifest['system_id'],1,b'ARMING_CHECK',-1).pack(peer),source)
                leaked=False;end=time.monotonic()+1.5
                while time.monotonic()<end:
                    try:raw,_=monitor.recvfrom(65535)
                    except socket.timeout:continue
                    for message in parser.parse_buffer(raw) or []:
                        if message.get_type()=='PARAM_VALUE' and message.param_id=='ARMING_CHECK':leaked=True
                assert not leaked
                result['qgc_monitor']=dict(system_id=manifest['system_id'],signed_types=sorted(seen),request_forwarded=False)
                if motion or http_controls or tools:
                    os.environ.update(GZ_IP='127.0.0.1',GZ_PARTITION=manifest['partition'])
                    from tests.simulation.oracle import GazeboTruthOracle
                    oracle=GazeboTruthOracle(manifest['world'],manifest['model'])
                    # Preserve the established 45-second native initialization.
                    ready=time.monotonic()+45
                    while time.monotonic()<ready:time.sleep(.1)
                    if tools:
                        tools.start()
                        result['physical']=tools.exercise(kind,base,token,api,oracle,directory)
                    elif http_controls:
                        from tests.simulation.web_controls import exercise
                        result['physical']=exercise(kind,api,oracle,directory)
                    else:result['physical']=rover_browser(base,token,api,oracle,directory)
                for name in ['gazebo']+(['gui'] if gui else []):
                    content=(directory/(name+'.log')).read_text(errors='replace').lower()
                    for error in ('failed to load system plugin','error while loading the library','unable to find uri','unable to find file'):
                        assert error not in content,'Gazebo resource/plugin failure: '+error
                result['gazebo_resource_errors']=False
                result['passed']=True
            finally:
                if tools:tools.close()
                if launcher is not None and launcher.poll() is None:
                    os.killpg(launcher.pid,signal.SIGTERM)
                    launcher.wait(timeout=100)
                    assert launcher.returncode==0,'launcher did not exit cleanly'
                if (directory/'session.json').is_file():
                    closed=json.loads((directory/'session.json').read_text())
                    result['cleanup']={k:closed.get(k) for k in ('remaining_process_groups','cleanup_errors','credentials_removed')}
                    assert result['cleanup']==dict(remaining_process_groups=[],cleanup_errors=[],credentials_removed=True)
                    assert not (directory/'receive-signing.private').exists()
                    assert not (directory/'sitl_state').exists()
                    assert not (directory/'web-token.private').exists()
                    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in closed['inputs_sha256'].items())
                (directory.parent/(directory.name+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


def rover_browser(base,token,api,oracle,directory):
    """The --motion entry uses the same current console as native-tool checks."""
    from playwright.sync_api import sync_playwright,expect
    from tests.browser_auth import login
    from tests.simulation.web_ui_controls import BrowserControlCheck
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            page=browser.new_page(viewport={'width':1680,'height':1100})
            page.on('pageerror',lambda error:errors.append(str(error)))
            login(page,base,token,'/control')
            page.locator('#acquire-control').click();expect(page.locator('#top-authority')).to_have_text('开启指令发送')
            check=BrowserControlCheck('rover',api,oracle,directory,page)
            check.perform('Arm',allow_send=False,expected='REJECTED')
            result=check.run()
            page.locator('#release-control').click();expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
            page.screenshot(path=str(directory/'basic-controls.png'),full_page=True)
            assert not errors;result['javascript_errors']=errors
            return result
        finally:browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind',choices=('rover','copter','plane'),required=True)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--motion',action='store_true');parser.add_argument('--gui',action='store_true')
    parser.add_argument('--read-only',action='store_true')
    parser.add_argument('--http-controls',action='store_true')
    parser.add_argument('--tool-registry',type=Path,help='Run real browser controls and native ROS2 tool UI using this trusted registry')
    parser.add_argument('--visualization',action='store_true',help='With --tool-registry: real desktop RViz, vehicle bridge and native ROS observations')
    parser.add_argument('--visualization-extended',action='store_true',help='Rover motion + actual RViz goal selection and tool/Workspace lifecycle; full controls are a separate run')
    parser.add_argument('--visualization-lifecycle-only',action='store_true',help='Rover native tools, Wait Mission and owned SITL blackout; no vehicle Actions')
    args=parser.parse_args()
    if args.visualization and not args.tool_registry:parser.error('--visualization requires an explicit trusted native --tool-registry')
    if args.visualization_extended and (not args.visualization or args.kind!='rover'):parser.error('--visualization-extended requires --visualization --kind rover')
    result=run(args.kind,args.run_dir,motion=args.motion,gui=args.gui,read_only=args.read_only,http_controls=args.http_controls,tool_registry=args.tool_registry,visualization=args.visualization,visualization_extended=args.visualization_extended,visualization_lifecycle_only=args.visualization_lifecycle_only)
    if args.http_controls or args.tool_registry:
        result={k:result[k] for k in ('kind','passed','cleanup')}
        result['evidence']=str(args.run_dir/'web-control-result.json')
    print(json.dumps(result,ensure_ascii=False))

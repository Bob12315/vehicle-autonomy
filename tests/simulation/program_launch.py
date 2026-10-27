"""Actual one-click scripts, signed Web state, receive-only QGC and cleanup.

--motion additionally uses real Chrome and independent Gazebo pose truth for
Rover forward/turn/stop/Goto/ReturnHome. No test bypasses the Action SEND gate.
"""
import argparse
import hashlib
import json
import math
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


def run(kind, directory, *, motion=False, gui=False, read_only=False, http_controls=False):
    if motion and kind != 'rover':raise ValueError('motion acceptance is currently Rover only')
    directory = directory.resolve();directory.parent.mkdir(parents=True,exist_ok=True)
    port = {'rover':18880,'copter':18881,'plane':18882}[kind]
    if motion and read_only:raise ValueError('motion requires explicit deployment authorization')
    result = dict(kind=kind,motion=motion,gui=gui,read_only=read_only,passed=False)
    launcher = None
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as monitor:
        monitor.bind(('127.0.0.1',0));monitor.settimeout(.05)
        qgc_port = monitor.getsockname()[1]
        command = [str(ROOT/f'scripts/start_{kind}_sim.sh'),'--run-dir',str(directory),
                   '--web-port',str(port),'--qgc-port',str(qgc_port)]
        if not gui:command.append('--headless')
        if read_only:command.append('--read-only')
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
                if motion or http_controls:
                    os.environ.update(GZ_IP='127.0.0.1',GZ_PARTITION=manifest['partition'])
                    from tests.simulation.oracle import GazeboTruthOracle
                    oracle=GazeboTruthOracle(manifest['world'],manifest['model'])
                    # Preserve the established 45-second native initialization.
                    ready=time.monotonic()+45
                    while time.monotonic()<ready:time.sleep(.1)
                    if http_controls:
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
    from playwright.sync_api import sync_playwright
    checks={};errors=[]
    def truth():
        sample=oracle.latest()
        if sample is None or time.monotonic_ns()-sample.host_received_ns>500_000_000:raise AssertionError('fresh independent Gazebo truth missing')
        return sample
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            page=browser.new_page(viewport={'width':1680,'height':1100})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/control');page.locator('#token').fill(token);page.locator('#connect').click()
            page.locator('#action option').first.wait_for(state='attached')
            def wait(predicate,seconds=30):
                end=time.monotonic()+seconds
                while time.monotonic()<end:
                    truth();value=predicate()
                    if value:return value
                    page.wait_for_timeout(60)
                raise TimeoutError('browser operation: '+page.locator('#notice').inner_text()[:250])
            def instances():return api('/api/instances')
            def state(identifier):return next(a for a in instances() if a['id']==identifier)
            def finish(a,expected='SUCCEEDED',seconds=40):
                final=wait(lambda:state(a['id']) if state(a['id'])['state'] in TERMINAL else None,seconds)
                assert final['state']==expected,(final['name'],final['state'],final['error'])
                assert final['safety']['release_safe']
                return final
            def perform(name,parameters=None,seconds=40):
                before={a['id'] for a in instances()}
                page.locator('#action').select_option(name+'@1.0.0')
                for key,value in (parameters or {}).items():
                    field=page.locator(f'#parameters [name="{key}"]')
                    if field.evaluate('(e)=>e.tagName')=='SELECT':field.select_option(json.dumps(value))
                    else:field.fill(str(value));field.press('Tab')
                page.locator('#send').check();page.locator('#execute').click()
                action=wait(lambda:next((a for a in instances() if a['id'] not in before),None),8)
                return finish(action,seconds=seconds)
            initial=truth();perform('SetMode',{'mode':'GUIDED'});perform('Arm')
            checks['managed_inputs']=[]
            for key,name,threshold in [('w','forward',.35),('a','turn',.3)]:
                perform('SetMode',{'mode':'GUIDED'})
                start=truth();before={a['id'] for a in instances()}
                page.locator('#manual-send').check()
                if key=='w':
                    page.locator('#manual-send').focus();page.keyboard.down(key)
                else:page.locator(f'[data-key="{key}"]').hover();page.mouse.down()
                action=wait(lambda:next((a for a in instances() if a['id'] not in before),None),5)
                def measured():
                    current=truth()
                    return (math.hypot(current.x_m-start.x_m,current.y_m-start.y_m) if key=='w' else
                        abs(math.atan2(math.sin(current.yaw_rad-start.yaw_rad),math.cos(current.yaw_rad-start.yaw_rad))))
                try:wait(lambda:measured()>=threshold,12);motion=measured()
                finally:
                    if key=='w':page.keyboard.up(key)
                    else:page.mouse.up()
                final=finish(action,'CANCELLED',20)
                speed=oracle.recent_speed_mps();yaw_rate=oracle.recent_yaw_rate_rad_s()
                assert speed is not None and speed<=.1
                assert yaw_rate is not None and abs(yaw_rate)<=.1
                checks['managed_inputs'].append(dict(name=name,measured=motion,state=final['state'],stop_speed_mps=speed,stop_yaw_rate_rad_s=yaw_rate))
            perform('SetMode',{'mode':'GUIDED'});perform('Goto',{'x_m':2,'y_m':0},seconds=60)
            target=truth();checks['goto_error_m']=math.hypot(target.x_m-initial.x_m-2,target.y_m-initial.y_m)
            assert checks['goto_error_m']<=.75
            perform('Stop');assert oracle.recent_speed_mps()<=.1
            perform('ReturnHome',seconds=80);perform('Disarm')
            home=truth();checks['home_error_m']=math.hypot(home.x_m-initial.x_m,home.y_m-initial.y_m)
            checks['home_speed_mps']=oracle.recent_speed_mps()
            assert checks['home_error_m']<=.75 and checks['home_speed_mps']<=.1
            assert not errors;checks['javascript_errors']=errors
            page.screenshot(path=str(directory/'basic-controls.png'),full_page=True,mask=[page.locator('#token')])
        finally:browser.close()
    return checks


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind',choices=('rover','copter','plane'),required=True)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--motion',action='store_true');parser.add_argument('--gui',action='store_true')
    parser.add_argument('--read-only',action='store_true')
    parser.add_argument('--http-controls',action='store_true')
    args=parser.parse_args();result=run(args.kind,args.run_dir,motion=args.motion,gui=args.gui,read_only=args.read_only,http_controls=args.http_controls)
    if args.http_controls:
        result={k:result[k] for k in ('kind','passed','cleanup')}
        result['evidence']=str(args.run_dir/'web-control-result.json')
    print(json.dumps(result,ensure_ascii=False))

"""Actual systemd Control Center, password login, native camera and Web shutdown.

Uses a new private VAF_RUNTIME_ROOT; never resets an existing operator password
or takes over a running Control Center. Opens no physical camera or vehicle.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import traceback
from urllib.request import Request,urlopen
from uuid import uuid4

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.control_center.supervisor import service_state,unit_name,process_table,process_identity
from vehicle_autonomy.app.web.passwords import set_password


def run(path):
    from playwright.sync_api import sync_playwright,expect
    from tests.browser_auth import login
    root=resource_root();path=path.resolve();path.mkdir(mode=0o700,parents=True,exist_ok=False)
    report=dict(status='FAIL',checks={});launcher=None;log=None;current=None;key=None
    runtime=path/'private-runtime';port=None
    def save():(path/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    def wait(predicate,timeout=150):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=predicate()
            if value:return value
            time.sleep(.2)
        raise TimeoutError('camera Control Center acceptance timeout')
    def api(route,payload=None):
        headers={'Authorization':'Bearer '+key};data=None
        if payload is not None:
            data=json.dumps(payload).encode();headers.update({'Content-Type':'application/json','X-VAF-CSRF':key,'X-VAF-Request-ID':uuid4().hex})
        with urlopen(Request(f'http://127.0.0.1:{port}'+route,data,headers),timeout=20) as response:r=json.load(response)
        assert r['ok'],r
        return r['result']
    try:
        if service_state(unit_name(root)).get('ActiveState') in ('active','activating','deactivating'):
            report.update(status='BLOCKED',reason='another Control Center owns the service; not taken over');return report
        password=secrets.token_urlsafe(24);password_path=runtime/'state/control-center/password.json';password_path.parent.mkdir(parents=True,mode=0o700);set_password(password_path,password)
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        log=(path/'launcher.log').open('w');env=dict(os.environ,VAF_RUNTIME_ROOT=str(runtime))
        launcher=subprocess.Popen([sys.executable,'-m','vehicle_autonomy.app.control_center.launcher','--no-browser','--read-only','--port',str(port)],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
        def ready():
            if launcher.poll() is not None:raise RuntimeError('launcher exited; see launcher.log')
            try:
                state=json.loads((runtime/'state/control-center/current.json').read_text())
                return state if state['state']=='READY' else None
            except (OSError,ValueError):return None
        current=wait(ready,60);key=Path(current['token_file']).read_text().strip();report['center']={k:current[k] for k in ('session_id','pid','cgroup','unit','deployment_send')}
        session=api('/api/simulation/create',dict(scene_id='R01',vehicle='rover',parameters={'obstacle_count':0}))
        api('/api/simulation/start',dict(id=session['id']))
        def ready_world():
            record=api('/api/simulation/report',dict(id=session['id']))
            if record['state']=='FAILED':raise AssertionError(record.get('error'))
            return record if record['state']=='RUNNING' and record.get('vehicles') and record['vehicles'][0]['state']=='RUNNING' else None
        world=wait(ready_world);target=world['vehicles'][0]['target']
        camera=wait(lambda:next((c for c in api('/api/cameras?target='+target)['cameras'] if c['online']),None),20)
        report['camera']=camera
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(viewport={'width':1480,'height':1080});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                login(page,f'http://127.0.0.1:{port}',password,'/control#'+target)
                expect(page.locator('#camera-video')).to_be_visible(timeout=10000)
                page.wait_for_function("() => document.querySelector('#camera-video').naturalWidth===640")
                page.screenshot(path=str(path/'real-control-center-camera.png'),full_page=True)
                source=api('/api/control/state')['vehicles'][0]
                assert not source['system_send'] and not source['action_send'] and source['writer']['attempts']==0
                report['readonly_writer']=source['writer'];report['checks']['actual Center password login / live MJPEG / no SEND']='PASS'
                # Collect native HTTP receive facts separately from UI screenshots.
                conn=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
                conn.request('GET','/api/cameras/'+camera['camera_id']+'/snapshot?target='+target,headers={'Authorization':'Bearer '+key})
                response=conn.getresponse();assert response.status==200;jpeg=response.read();received=time.monotonic_ns();conn.close();(path/'native-snapshot.jpg').write_bytes(jpeg)
                report['snapshot']=dict(headers=dict(response.getheaders()),web_received_ns=received,sha256=hashlib.sha256(jpeg).hexdigest())
                before=api('/api/center/state');report['processes_before']=before['processes'];assert any('camera' in str(row) for row in before['processes'])
                page.goto(f'http://127.0.0.1:{port}/center');expect(page.locator('#shutdown')).to_be_enabled(timeout=10000);page.locator('#shutdown').click()
                launcher.wait(135);assert launcher.returncode==0
                report['browser_errors']=errors;assert not errors,errors
            finally:browser.close()
        directory=Path(current['run_dir']);state=json.loads((directory/'state.json').read_text());audit=json.loads((directory/'os-cleanup.json').read_text())
        assert state['state']=='STOPPED' and not state['cleanup_errors'],state
        assert not process_table(current['cgroup']) and not audit['remaining_owned_processes'] and not audit['credential_errors'],audit
        for row in report['processes_before']:
            try:assert process_identity(row['pid'])!=row['start_ticks'],row
            except OSError:pass
        sim=json.loads((directory/'application/simulation'/session['id']/'report.json').read_text());assert sim['cleanup']=='COMPLETE',sim.get('error')
        report['cleanup']=dict(state=state['state'],simulation=sim['cleanup'],remaining_processes=process_table(current['cgroup']),os_audit=audit)
        report['checks']['Web shutdown / actual systemd cgroup camera SITL Gazebo cleanup']='PASS';report['status']='PASS'
    except Exception:
        report['error']=traceback.format_exc();print(report['error'],flush=True)
    finally:
        if launcher and launcher.poll() is None:
            launcher.terminate()
            try:launcher.wait(135)
            except subprocess.TimeoutExpired:report['cleanup_error']='owned launcher shutdown timed out'
        if log:log.close()
        save()
    print(json.dumps({k:v for k,v in report.items() if k not in ('camera','processes_before')},ensure_ascii=False),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True,type=Path);args=p.parse_args()
    raise SystemExit(0 if run(args.run_dir)['status']=='PASS' else 1)

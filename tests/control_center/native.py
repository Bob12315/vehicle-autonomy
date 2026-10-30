"""Real desktop + systemd lifecycle acceptance. Starts only owned local SITL.

Run as a desktop user with systemd --user, Gazebo Harmonic, ROS/RViz and QGC.
No GUI/telemetry/OS cleanup is mocked. Does not arm or fly the vehicle.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import traceback
from urllib.request import Request,urlopen
from uuid import uuid4

from tests.browser_auth import login
from vehicle_autonomy.app.control_center.supervisor import process_identity,service_state,unit_name,process_table
from vehicle_autonomy.app.control_center.registry import inspect_host,qt_environment
from vehicle_autonomy.app.control_center.desktop import windows

ROOT=Path(__file__).resolve().parents[2]


def run(directory):
    from playwright.sync_api import sync_playwright,expect
    from PIL import ImageGrab
    directory=Path(directory).resolve();directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    result=dict(status='FAIL',checks={},epochs=[],javascript_errors=[],screenshots=[],errors=[])
    launches=[];logs=[];external=None;external_log=None;page=None
    key=None;current=None
    def save(): (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def api(path,payload=None):
        headers={'Authorization':'Bearer '+key};data=None
        if payload is not None:
            headers.update({'Content-Type':'application/json','X-VAF-CSRF':key,'X-VAF-Request-ID':uuid4().hex});data=json.dumps(payload).encode()
        with urlopen(Request('http://127.0.0.1:8780'+path,data,headers),timeout=30) as response:value=json.load(response)
        if not value['ok']:raise AssertionError(value)
        return value['result']
    def wait(predicate,seconds=100):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            value=predicate()
            if value:return value
            if page:page.wait_for_timeout(250)
            else:time.sleep(.25)
        raise TimeoutError('native acceptance timed out')
    def launch(number):
        nonlocal current,key
        path=directory/f'launcher-{number}.log';log=path.open('w');logs.append(log)
        previous=current['session_id'] if current else None
        # Default command really opens the local browser, outside the cgroup.
        process=subprocess.Popen([str(ROOT/'control-center')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        launches.append(process)
        def ready():
            if process.poll() is not None:raise RuntimeError(path.read_text())
            try:
                value=json.loads((ROOT/'runtime/control-center/current.json').read_text())
                if value['state']=='READY' and value['session_id']!=previous:return value
            except (OSError,ValueError):pass
        current=wait(ready,60);key=Path(current['token_file']).read_text().strip();result['epochs'].append(current)
        state=api('/api/center/state');assert not api('/api/simulation/sessions');assert all(t['instance'] is None for t in state['tools'])
        return process
    def ready_world(identifier):
        r=api('/api/simulation/report',dict(id=identifier))
        if r['state']=='FAILED':raise AssertionError(r.get('error'))
        return r if r['state'] in ('READY','RUNNING') and all(v['state'] in ('READY','RUNNING') for v in r.get('vehicles',[])) else None
    def create_world_ui(scene='C01',kind='copter'):
        page.goto('http://127.0.0.1:8780/simulation');page.locator('#search').fill(scene);page.locator('[data-scene="'+scene+'"]').click()
        page.locator('#config-vehicle').select_option(kind)
        if page.locator('#parameter-obstacle_count').count():page.locator('#parameter-obstacle_count').fill('0')
        known={r['id'] for r in api('/api/simulation/sessions')};page.locator('#create-session').click()
        record=wait(lambda:next((r for r in api('/api/simulation/sessions') if r['id'] not in known),None),20)
        page.locator('[data-operation=start]').click();return wait(lambda:ready_world(record['id']),160)
    def center_page():
        page.goto('http://127.0.0.1:8780/center');page.wait_for_function("() => document.querySelector('#connection').textContent.includes('已连接')")
    def tool_info(tool_id):return next(t for t in api('/api/center/state')['tools'] if t['manifest']['id']==tool_id)
    def gui_ready(tool_id):
        t=tool_info(tool_id);i=t['instance'];s=api('/api/center/state')
        if s.get('operation',{}).get('state')=='FAILED':raise AssertionError(s['operation'])
        if i and i['state'] in ('FAILED','UNKNOWN'):raise AssertionError(i)
        return t if i and i['ready'] and i['windows'] else None
    def button(tool_id,action):
        page.locator('[data-tool="'+tool_id+'"] [data-action="'+action+'"]').click()
        wait(lambda:api('/api/center/state')['operation']['state']!='RUNNING',45)
    def capture(tool_id,label):
        t=gui_ready(tool_id);w=t['instance']['windows'][0]
        # Observer-only window activation. No clicks/commands in flight tools.
        lib=ctypes.CDLL('libX11.so.6');lib.XOpenDisplay.restype=ctypes.c_void_p;lib.XOpenDisplay.argtypes=[ctypes.c_char_p]
        lib.XRaiseWindow.argtypes=[ctypes.c_void_p,ctypes.c_ulong];lib.XFlush.argtypes=[ctypes.c_void_p];lib.XCloseDisplay.argtypes=[ctypes.c_void_p]
        display=lib.XOpenDisplay(None);lib.XRaiseWindow(display,int(w['id'],16));lib.XFlush(display);lib.XCloseDisplay(display)
        page.wait_for_timeout(1300)
        path=directory/(label+'.png');ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(path)
        result['screenshots'].append(str(path));return t
    def remember(name):
        state=api('/api/center/state');result[name]=state;save();return state['processes']
    def cleaned(records,cgroup,ports):
        def gone():
            for r in records:
                try:
                    if process_identity(r['pid'])==r['start_ticks']:return False
                except OSError:pass
            if process_table(cgroup):return False
            for port,kind in ports:
                try:
                    with socket.socket(socket.AF_INET,kind) as s:
                        s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
                except OSError:return False
            return True
        wait(gone,135)
        audit=json.loads((Path(current['run_dir'])/'os-cleanup.json').read_text())
        assert not audit['remaining_owned_processes'] and not audit['credential_errors'],audit
        assert not list((Path(current['run_dir'])/'application/simulation').glob('*/vehicle-*/receive-signing.private'))
        result.setdefault('cleanup_audits',[]).append(audit)
    def personal_hashes():
        base=Path.home()/'.config/QGroundControl'
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in base.rglob('*') if p.is_file()}
    before=personal_hashes()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=False,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(viewport={'width':1600,'height':1000});page.on('pageerror',lambda exc:result['javascript_errors'].append(str(exc)))
                launcher=launch(1);login(page,'http://127.0.0.1:8780',key,'/center')
                expect(page.locator('h1')).to_have_text('本地控制台');result['checks']['single_command_browser_no_autostart']='PASS'
                duplicate=subprocess.run([str(ROOT/'control-center'),'--no-browser'],capture_output=True,text=True,timeout=10)
                assert duplicate.returncode!=0 and '已在运行' in duplicate.stderr;result['checks']['duplicate_launch_rejected']='PASS'
                world=create_world_ui();identifier=world['id'];vehicle=world['vehicles'][0]
                result['world']=dict(id=identifier,vehicle=vehicle,epoch=current['session_id'])
                page.locator('#open-gazebo-gui').click();wait(lambda:gui_ready('gazebo-gui'),70)
                page.wait_for_timeout(5000)
                first=capture('gazebo-gui','gazebo-first');assert first['binding']['world_id']==identifier
                center_page();button('gazebo-gui','stop');wait(lambda:not tool_info('gazebo-gui')['instance']['process_running'],35)
                after=ready_world(identifier);assert after and after['vehicles'][0]['id']==vehicle['id']
                assert after['vehicles'][0]['target']==vehicle['target'];result['checks']['gui_close_preserves_server_sitl_identity']='PASS'
                button('gazebo-gui','start');wait(lambda:gui_ready('gazebo-gui'),70)
                second=capture('gazebo-gui','gazebo-reconnected');assert first['instance']['pid']!=second['instance']['pid']
                assert first['binding']==second['binding'];result['checks']['gui_reconnect_same_world']='PASS'
                page.goto('http://127.0.0.1:8780/control#'+vehicle['target'])
                expect(page.locator('#open-rviz')).to_be_enabled(timeout=20000);page.locator('#open-rviz').click();wait(lambda:gui_ready('rviz2'),70)
                result['checks']['existing_control_page_rviz_entry']='PASS'
                center_page();page.locator('#target').select_option(vehicle['target'])
                capture('rviz2','rviz-copter')
                button('qgroundcontrol','start');wait(lambda:gui_ready('qgroundcontrol'),70)
                page.wait_for_timeout(18000);capture('qgroundcontrol','qgc-live-copter')
                qgc=tool_info('qgroundcontrol');qgc_log=Path(qgc['instance']['log_path']).read_text(errors='replace')
                (directory/'qgc-connect.log').write_text(qgc_log)
                # Actual QGC consumes this sysid's HEARTBEAT, not a synthetic feed.
                assert re.search(r'Adding new vehicle.*(?:%s)' % vehicle['system_id'],qgc_log,re.I),qgc_log[-2000:]
                result['checks']['qgc_real_sitl']=dict(status='PASS',system_id=vehicle['system_id'],log=str(directory/'qgc-connect.log'))
                state=api('/api/center/state');assert all(t['instance']['ready'] for t in state['tools']);remember('three_tools_running')
                result['checks']['three_real_windows_together']='PASS'
                page.screenshot(path=str(directory/'console-three-tools.png'),full_page=True)
                query=api('/api/simulation/test',dict(id=identifier,vehicle_id=vehicle['id'],name='GetVehicleState',parameters={},allow_send=False,timeout_s=30))
                wait(lambda:next((a for a in api('/api/control/state')['actions'] if a['id']==(query.get('action_id') or query.get('id')) and a['state']=='SUCCEEDED'),None),35)
                result['checks']['original_action_query']='PASS'
                button('rviz2','stop');wait(lambda:not tool_info('rviz2')['instance']['process_running'],40)
                assert gui_ready('qgroundcontrol') and gui_ready('gazebo-gui');button('rviz2','start');wait(lambda:gui_ready('rviz2'),60)
                button('qgroundcontrol','stop');wait(lambda:not tool_info('qgroundcontrol')['instance']['process_running'],40)
                assert gui_ready('rviz2') and gui_ready('gazebo-gui');button('qgroundcontrol','start');wait(lambda:gui_ready('qgroundcontrol'),70)
                result['checks']['independent_tool_stop_restart']='PASS'
                page.locator('#stop-all').click()
                wait(lambda:api('/api/center/state')['operation']['state']!='RUNNING',90)
                assert all(not t['instance']['process_running'] for t in api('/api/center/state')['tools'])
                assert ready_world(identifier)['vehicles'][0]['id']==vehicle['id']
                result['checks']['close_all_tools_preserves_simulation']='PASS'
                for tool_id in ('gazebo-gui','rviz2','qgroundcontrol'):
                    button(tool_id,'start');wait(lambda tool_id=tool_id:gui_ready(tool_id),75)
                page.locator('#stop-simulation').click();wait(lambda:api('/api/simulation/report',dict(id=identifier))['state'] in ('FINISHED','FAILED','CANCELLED'),100)
                assert api('/api/simulation/report',dict(id=identifier))['cleanup']=='COMPLETE'
                assert api('/api/center/state')['state']=='READY';result['checks']['stop_simulation_keep_console']='PASS'
                records=remember('before_web_shutdown');group=current['cgroup'];page.locator('#shutdown').click();launcher.wait(timeout=140)
                cleaned(records,group,[(8780,socket.SOCK_STREAM),(14550,socket.SOCK_DGRAM)]);result['checks']['web_shutdown_cleans_all']='PASS'
                # Outside the Center cgroup: same native executable must survive.
                host=inspect_host(ROOT);env=dict(os.environ,**qt_environment(host['ros']))
                extdir=directory/'external-rviz';extdir.mkdir();external_log=(extdir/'log').open('w')
                external=subprocess.Popen([host['tools']['rviz2']['executable'],'-d',str(ROOT/'configs/rviz/navigation-readonly.rviz')],env=env,cwd=extdir,stdout=external_log,stderr=subprocess.STDOUT,start_new_session=True)
                wait(lambda:windows([external.pid]),30)
                launcher=launch(2);login(page,'http://127.0.0.1:8780',key,'/center')
                world=create_world_ui();identifier=world['id'];vehicle=world['vehicles'][0]
                center_page();page.locator('#target').select_option(vehicle['target'])
                for tool_id in ('gazebo-gui','rviz2','qgroundcontrol'):
                    button(tool_id,'start');wait(lambda tool_id=tool_id:gui_ready(tool_id),75)
                records=remember('before_backend_sigkill');group=current['cgroup'];old_epoch=current['session_id']
                ports=[(8780,socket.SOCK_STREAM),(14550,socket.SOCK_DGRAM)]
                for v in world['vehicles']:
                    ports.extend((p,socket.SOCK_DGRAM if k in ('fdm','udp') else socket.SOCK_STREAM) for k,p in v['ports'].items() if isinstance(p,int))
                os.kill(current['pid'],signal.SIGKILL);launcher.wait(timeout=140);cleaned(records,group,ports)
                assert external.poll() is None and windows([external.pid]);result['checks']['sigkill_kernel_cgroup_cleanup']='PASS';result['checks']['external_same_program_untouched']='PASS'
                launcher=launch(3);login(page,'http://127.0.0.1:8780',key,'/center');assert current['session_id']!=old_epoch
                try:api('/api/center/tool',dict(session_id=old_epoch,action='start',tool_id='rviz2'));raise AssertionError('stale epoch accepted')
                except Exception as exc:
                    from urllib.error import HTTPError
                    assert isinstance(exc,HTTPError) and exc.code==409
                result['checks']['restart_clean_and_stale_epoch_rejected']='PASS'
                world=create_world_ui(kind='none');identifier=world['id'];center_page();button('gazebo-gui','start');wait(lambda:gui_ready('gazebo-gui'),70)
                records=remember('before_ctrl_c');group=current['cgroup'];launcher.send_signal(signal.SIGINT);launcher.wait(timeout=140);cleaned(records,group,[(8780,socket.SOCK_STREAM)])
                result['checks']['ctrl_c_graceful_cleanup']='PASS'
                launcher=launch(4);login(page,'http://127.0.0.1:8780',key,'/center');world=create_world_ui(kind='none')
                records=remember('before_launcher_sigkill');group=current['cgroup'];launcher.kill();launcher.wait(timeout=10);cleaned(records,group,[(8780,socket.SOCK_STREAM)])
                result['checks']['launcher_sigkill_watchdog_cleanup']='PASS'
                assert external.poll() is None;assert personal_hashes()==before;assert not result['javascript_errors'],result['javascript_errors']
                result['checks']['personal_qgc_configuration_unchanged']='PASS';result['status']='PASS'
            finally:browser.close()
    except Exception as exc:
        result['errors'].append(type(exc).__name__+': '+str(exc));traceback.print_exc()
    finally:
        for process in launches:
            if process.poll() is None:process.send_signal(signal.SIGTERM);process.wait(timeout=140)
        subprocess.run(['systemctl','--user','stop',unit_name(ROOT)],capture_output=True,timeout=140)
        if external:
            try:os.killpg(external.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            external.wait(timeout=15)
        if external_log:external_log.close()
        for log in logs:log.close()
        save()
    print(json.dumps(dict(status=result['status'],checks=result['checks'],errors=result['errors']),ensure_ascii=False),flush=True)
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory');args=parser.parse_args();raise SystemExit(run(args.directory))

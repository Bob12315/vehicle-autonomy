"""Browser-selected Scene -> real SITL -> original HTTP Actions -> cleanup.

This uses the existing three-vehicle motion oracle and permission boundaries.
No raw vehicle command port is called. Each run owns fresh credentials/state.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from threading import Thread
import time
from urllib.request import Request, urlopen
from uuid import uuid4

from tests.browser_auth import login
from tests.simulation.web_controls import ControlCheck
from vehicle_autonomy.app.web.mission_control import MissionControl, MissionControlServer
from vehicle_autonomy.app.web.server import load_token


def run(directory, kind):
    from playwright.sync_api import sync_playwright,expect
    directory=directory.resolve();directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    token_path=directory/'web-token.private';token=load_token(token_path)
    app=MissionControl({},directory/'application',simulation_allow_send=True)
    server=MissionControlServer(('127.0.0.1',0),app,token,directory/'http-audit.jsonl')
    thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.1},daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_address[1]);identifier=None
    scene={'rover':'R01','copter':'C01','plane':'F01'}[kind]
    report=dict(scene_id=scene,kind=kind,status='FAIL',levels={f'L{i}':'NOT_TESTED' for i in range(1,7)},checks={},javascript_errors=[])
    def api(path,payload=None):
        data=None;headers={'Authorization':'Bearer '+token}
        if payload is not None:
            data=json.dumps(payload).encode();headers.update({'Content-Type':'application/json','X-VAF-CSRF':token,'X-VAF-Request-ID':uuid4().hex})
        with urlopen(Request(base+path,data,headers),timeout=12) as reply:value=json.load(reply)
        if not value.get('ok'):raise AssertionError(value)
        return value['result']
    def wait(predicate,seconds=140):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            result=predicate()
            if result:return result
            time.sleep(.15)
        raise TimeoutError('simulation center vehicle acceptance')
    def session():return api('/api/simulation/report',{'id':identifier})
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(viewport={'width':1680,'height':1080},accept_downloads=True)
                page.on('pageerror',lambda error:report['javascript_errors'].append(str(error)))
                login(page,base,token,'/simulation')
                page.locator('#search').fill(scene)
                page.locator('[data-scene="'+scene+'"]').click()
                page.locator('#config-vehicle').select_option(kind)
                # Keep the validated takeoff/drive corridor clear of random obstacles.
                page.locator('#parameter-obstacle_count').fill('0')
                page.locator('#create-session').click()
                wait(lambda:api('/api/simulation/sessions'))
                identifier=api('/api/simulation/sessions')[-1]['id'];report['id']=identifier
                expect(page.locator('#sessions-view')).to_be_visible(timeout=10000)
                page.locator('[data-operation=start]').click()
                def ready():
                    item=session()
                    if item['state']=='FAILED':raise AssertionError(item['error'])
                    return item if item['state']=='RUNNING' else None
                current=wait(ready)
                owner=app.simulation_manager.owners[identifier]
                os.environ.update(GZ_IP='127.0.0.1',GZ_PARTITION=owner.partition)
                from tests.simulation.oracle import GazeboTruthOracle
                oracle=GazeboTruthOracle(owner.world,owner.model.name)
                wait(lambda:oracle.latest(),20)
                # Preserve the original actual EKF warmup and fresh signed cut.
                until=time.monotonic()+45
                while time.monotonic()<until:page.wait_for_timeout(100)
                state=api('/api/studio/state')['vehicles'][0]
                assert state['fresh_vehicle_state'] and state['verified_frames']>0,state.get('fault')
                assert not state['system_send'] and not state['action_send']
                report['checks']['browser_scene_and_vehicle_start']='PASS'
                page.locator('#query-test').click()
                wait(lambda:session()['tests'])
                check=ControlCheck(kind,api,oracle,directory,target=current['target'],expected_system_id=owner.model.system_id)
                report['physical']=check.run()
                report['checks']['original_http_motion_and_safe_exit']='PASS'
                # Query-only Mission exercises the same bound target without granting SEND.
                mission=dict(schema_version=1,id='center-query',name='仿真状态查询',version='1.0.0',target=current['target'],root='query',timeout_s=10,nodes=[dict(id='query',type='Action',action='GetVehicleState',parameters={})])
                submitted=api('/api/missions/start',dict(spec=mission,allow_send=False))
                final=wait(lambda:next((m for m in api('/api/studio/state')['missions'] if m['id']==submitted['id'] and m['state'] in ('SUCCEEDED','FAILED','UNKNOWN','REJECTED','TIMED_OUT')),None),15)
                assert final['state']=='SUCCEEDED',final
                report['mission']=final
                page.locator('#session-report').click()
                expect(page.locator('#report-levels div')).to_have_count(6)
                with page.expect_download() as download:page.locator('#export-report').click()
                download.value.save_as(str(directory/'browser-report.json'))
                assert identifier in (directory/'browser-report.json').read_text()
                page.screenshot(path=str(directory/'browser-running-report.png'),full_page=True)
                page.locator('[data-tab=sessions]').click()
                page.locator('[data-operation=stop]').click()
                stopped=wait(lambda:session() if session()['state'] in ('FINISHED','FAILED','CANCELLED') else None,60)
                assert stopped['state']=='FINISHED' and stopped['cleanup']=='COMPLETE',stopped
                assert not report['javascript_errors'],report['javascript_errors']
                report['checks']['browser_report_export_and_process_cleanup']='PASS'
                report['session_report']=stopped
                report['levels']={f'L{i}':'PASS' for i in range(1,7)}
                report['status']='PASS'
                page.screenshot(path=str(directory/'browser-finished.png'),full_page=True)
            finally:browser.close()
    except Exception as exc:
        report['error']=type(exc).__name__+': '+str(exc)
        if identifier:report['session_report']=session()
    finally:
        server.shutdown();server.server_close();thread.join(3)
        try:app.close()
        except Exception as exc:report['cleanup_error']=str(exc);report['status']='FAIL'
        token_path.unlink(missing_ok=True)
        (directory/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


def main():
    from tests.simulation.launch import install_signal_cleanup
    install_signal_cleanup()
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kind',choices=('rover','copter','plane'),required=True)
    p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--allow-send',action='store_true')
    args=p.parse_args()
    if not args.allow_send:p.error('explicit --allow-send required for owned local simulation acceptance')
    value=run(args.run_dir,args.kind)
    print(json.dumps({key:value.get(key) for key in ('scene_id','kind','status','levels','checks','error','cleanup_error')},ensure_ascii=False))
    return int(value['status']!='PASS')


if __name__=='__main__':raise SystemExit(main())

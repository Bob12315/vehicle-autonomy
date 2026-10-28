"""Published schema-2 Missions through HTTP, owned signed AP and Gazebo truth."""
import argparse,json,math,time
from pathlib import Path
from tests.simulation.launch import install_signal_cleanup
from tests.simulation.mission_fixture import MissionFixture
from vehicle_autonomy.app.mission_designer.studio_examples import rover_inspection,copter_inspection,plane_inspection


def run(path,kind,*,browser_ui=False):
    f=MissionFixture(path,kind);result=dict(passed=False,kind=kind,environment='owned signed native ArduPilot SITL + Gazebo + Studio HTTP')
    browser=pw=page=None;browser_errors=[]
    try:
        print(kind,'starting owned environment',flush=True);f.start()
        definition={'rover':rover_inspection,'copter':copter_inspection,'plane':plane_inspection}[kind](kind)
        result['definition']=definition;identifier=definition['mission_id']
        if browser_ui:
            from playwright.sync_api import sync_playwright,expect
            from tests.browser_auth import login
            pw=sync_playwright().start();browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            page=browser.new_page(viewport={'width':1680,'height':1050});page.on('pageerror',lambda error:browser_errors.append(str(error)))
            login(page,f.base,f.token,'/studio');page.locator('[data-tab=templates]').click()
            page.locator('.mission-card').filter(has_text=kind.title()).get_by_role('button',name='从模板创建',exact=True).click()
            page.locator('#publish').click();expect(page.locator('#notice')).to_contain_text('已发布不可变版本')
            page.screenshot(path=str(path/'browser-native-editor.png'),full_page=True)
            page.locator('[data-tab=runner]').click();page.locator('#send').check();page.locator('#run-start').click();page.locator('#dialog-confirm').click()
            until=time.monotonic()+10
            while not f.lab.missions.views() and time.monotonic()<until:page.wait_for_timeout(50)
            if not f.lab.missions.views():raise AssertionError('browser Run request not admitted')
            mission=f.lab.missions.views()[-1];result['environment']='Chrome UI + owned signed native ArduPilot SITL + Gazebo';result['definition']=mission['studio']['definition']
        else:
            saved=f.api('/api/studio-b/draft/save',dict(definition=definition,expected_revision=0))
            revision=saved['definition']['revision'];result['validation']=f.api('/api/studio-b/draft/validate',dict(mission_id=identifier,revision=revision))
            publication=f.api('/api/studio-b/draft/publish',dict(mission_id=identifier,revision=revision))
            mission=f.api('/api/studio-b/run/start',dict(publication=publication['key'],allow_send=True,debug=False))
        result['run_id']=mission['id']
        result['checkpoints']={};until=time.monotonic()+(960 if kind=='plane' else 210);last=None
        while time.monotonic()<until:
            f.truth();v=f.lab.missions.view(mission['id'])
            running=[n['id'] for n in v['nodes'] if n['state']=='RUNNING']
            if running!=last:print(kind,'state',v['state'],'active',running,flush=True);last=running
            for action_id in v['action_ids']:
                a=f.lab.runtime.view(action_id)
                if a['state']=='SUCCEEDED' and a['id'] not in result['checkpoints']:
                    t=f.truth();result['checkpoints'][a['id']]=dict(name=a['name'],position=[t.x_m,t.y_m,t.z_m],speed_mps=f.oracle.recent_speed_mps(),action=a)
            if v['state'] in ('SUCCEEDED','FAILED','UNKNOWN','CANCELLED','TIMED_OUT','REJECTED'):
                result['mission']=v
                if v['state']!='SUCCEEDED':raise AssertionError('Studio Mission '+v['state']+': '+str(v['error']))
                break
            if page:page.wait_for_timeout(50)
            else:time.sleep(.05)
        else:raise TimeoutError('Studio native outer deadline')
        t=f.truth();home_error=math.hypot(t.x_m-f.initial.x_m,t.y_m-f.initial.y_m);speed=f.oracle.recent_speed_mps()
        if not v['release_safe'] or home_error>(80 if kind=='plane' else .75) or speed is None or speed>(1 if kind=='plane' else .1 if kind=='rover' else .15):raise AssertionError('independent final home/stop evidence failed')
        goals=[c for c in result['checkpoints'].values() if c['name']=='Goto']
        if kind!='plane' and (not goals or math.dist(goals[0]['position'][:2],[f.initial.x_m+1,f.initial.y_m])>.75):raise AssertionError('native inspection waypoint not corroborated by Gazebo')
        if kind=='copter':
            takeoff=next(c for c in result['checkpoints'].values() if c['name']=='Takeoff')
            if takeoff['position'][2]-f.initial.z_m<1.15 or t.z_m-f.initial.z_m>.2:raise AssertionError('native climb/landing not corroborated')
        if kind=='plane':
            takeoff=next(c for c in result['checkpoints'].values() if c['name']=='Takeoff')
            rollout=[p for p in f.trajectory if p['position'][2]-f.initial.z_m<1 and (p['speed'] or 0)>8]
            if takeoff['position'][2]-f.initial.z_m<45 or not rollout or max(math.dist(p['position'][:2],[f.initial.x_m,f.initial.y_m]) for p in rollout)<10:raise AssertionError('native Plane rollout/climb not corroborated')
            if t.z_m-f.initial.z_m>.25 or abs(t.y_m-f.initial.y_m)>15:raise AssertionError('native Plane landing outside existing runway contract')
            for c in result['checkpoints'].values():
                if c['name'] in ('SetGuidedTarget','Loiter','RTL') and c['action']['result']['physical_arrival_claim']:raise AssertionError('configuration ACK falsely claimed arrival')
        result.update(passed=True,physical=dict(home_error_m=home_error,final_speed_mps=speed,final_height_m=t.z_m-f.initial.z_m),writer_calls=len(f.writer))
        if page:
            expect(page.locator('#run-state')).to_contain_text('SUCCEEDED',timeout=6000);page.locator('[data-inspect=diagnostics]').click();page.screenshot(path=str(path/'browser-native-complete.png'),full_page=True)
            if browser_errors:raise AssertionError('browser errors: '+str(browser_errors))
            result['browser_errors']=browser_errors
        print(kind,'Studio native PASS',flush=True)
    except Exception as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        if f.lab:result.update(actions=f.lab.runtime.views(),missions=f.lab.missions.views(),driver_info=f.driver.info())
        raise
    finally:
        if browser:browser.close()
        if pw:pw.stop()
        try:f.close()
        finally:(path/'studio-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--kind',choices=('rover','copter','plane'),required=True);parser.add_argument('--run-dir',type=Path,required=True);parser.add_argument('--browser',action='store_true')
    args=parser.parse_args();install_signal_cleanup();run(args.run_dir.resolve(),args.kind,browser_ui=args.browser)

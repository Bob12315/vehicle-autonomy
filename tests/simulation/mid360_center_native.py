"""Real browser / systemd Center acceptance; private runtime, simulation only.

No motion or physical endpoints. Refuses an existing operator Center. Preserves
finalized bags across fresh backend runs; SIGKILL targets only this test owner.
"""
import argparse,json,os,secrets,signal,socket,subprocess,sys,time,traceback
from pathlib import Path
from urllib.request import Request,urlopen
from uuid import uuid4

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.host_environment import HostEnvironment
from vehicle_autonomy.app.control_center.supervisor import service_state,unit_name,process_table,process_identity
from vehicle_autonomy.app.web.passwords import set_password


def run(directory,*,slam=False):
    from playwright.sync_api import sync_playwright,expect
    from tests.browser_auth import login
    from tests.visualization.desktop import goal
    root=resource_root();directory=Path(directory).resolve();directory.mkdir(parents=True,mode=0o700,exist_ok=False)
    runtime=directory/'private-runtime';report=dict(status='FAIL',checks={},runs=[]);launcher=log=None;current=None;key=None;port=None
    env=dict(os.environ,VAF_RUNTIME_ROOT=str(runtime));password=secrets.token_urlsafe(24)
    def wait(predicate,timeout=150):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=predicate()
            if value:return value
            time.sleep(.2)
        raise TimeoutError('MID-360 Center native acceptance timeout')
    def api(route,payload=None):
        headers={'Authorization':'Bearer '+key};data=None
        if payload is not None:
            data=json.dumps(payload).encode();headers.update({'Content-Type':'application/json','X-VAF-CSRF':key,'X-VAF-Request-ID':uuid4().hex})
        with urlopen(Request(f'http://127.0.0.1:{port}'+route,data,headers),timeout=30) as response:r=json.load(response)
        assert r['ok'],r
        return r['result']
    def launch():
        nonlocal launcher,log,current,key,port
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        log=(directory/('launcher-'+str(len(report['runs'])+1)+'.log')).open('w')
        launcher=subprocess.Popen([sys.executable,'-m','vehicle_autonomy.app.control_center.launcher','--no-browser','--read-only','--port',str(port)],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
        def ready():
            if launcher.poll() is not None:raise RuntimeError('owned launcher exited; inspect log')
            try:
                state=json.loads((runtime/'state/control-center/current.json').read_text())
                return state if state['state']=='READY' and state.get('url','').endswith(':'+str(port)+'/center') else None
            except (OSError,ValueError):return None
        current=wait(ready,60);key=Path(current['token_file']).read_text().strip()
        report['runs'].append({k:current[k] for k in ('session_id','pid','cgroup','unit','run_dir','deployment_send')})
    def mid(sid,vid,action='status',**kwargs):return api('/api/simulation/mid360',dict(id=sid,vehicle_id=vid,action=action,**kwargs))
    def observe(sid,vid,label):
        state=mid(sid,vid)
        sources=list((runtime/'sessions/control-center').glob('cc-*/application/simulation/'+sid+'/'+vid+'/mid360/source.json'))
        assert len(sources)==1,sources
        source=sources[0]
        # Restored records keep their original owned paths, no browser path input.
        if not source.exists():raise AssertionError('saved source configuration missing')
        command,ros=HostEnvironment(root).ros_command(['/usr/bin/env','ROS_DOMAIN_ID='+str(state['domains']['replay']),sys.executable,
            '-m','vehicle_autonomy.world.sensors.lidar.mid360_probe','--config',str(source)])
        ros.update(ROS_LOCALHOST_ONLY='1',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
        result=subprocess.run(command,env=ros,capture_output=True,text=True,timeout=15)
        (directory/(label+'-probe.json')).write_text(result.stdout+result.stderr);assert result.returncode==0,result.stdout+result.stderr
    def button(page,action):
        item=page.locator('[data-mid360="'+action+'"]');expect(item).to_be_enabled(timeout=20000);item.click()
    def rviz(page,sid,vid,label):
        button(page,'rviz_start');state=wait(lambda:(s if (s:=mid(sid,vid))['tools'].get('rviz2',{}).get('ready') else None),100)
        pid=state['tools']['rviz2']['pid'];goal(pid,capture=directory/(label+'.png'),select=False);return pid
    def finalized(page,sid,vid):
        button(page,'record_stop')
        state=wait(lambda:(s if not (s:=mid(sid,vid))['recording'] and any(b['complete'] for b in s['bags']) else None),30)
        bag=next(b for b in reversed(state['bags']) if b['complete']);assert len(bag['message_counts'])>=(10 if slam else 8),bag;return bag
    def slam_ui(page,sid,vid,label,*,save=False):
        expect(page.locator('#slam-panel')).to_be_visible(timeout=20000)
        page.locator('[data-slam="start"]').click()
        status=lambda:api('/api/simulation/slam',dict(id=sid,vehicle_id=vid,action='status'))
        wait(lambda:status()['online'],70)
        page.locator('[data-slam="rviz_start"]').click()
        view=wait(lambda:(s if (s:=mid(sid,vid))['tools'].get('slam-rviz',{}).get('ready') else None),100)
        goal(view['tools']['slam-rviz']['pid'],capture=directory/(label+'-slam.png'),select=False)
        assert page.locator('#slam-panel canvas').count()==0
        if save:
            page.locator('[data-slam="pause"]').click();wait(lambda:status()['state']['map']['paused'],10)
            page.locator('[data-slam="resume"]').click();wait(lambda:not status()['state']['map']['paused'],10)
            page.locator('#slam-map-name').fill(label+' UI map')
            with page.expect_response(lambda r:'/api/simulation/slam' in r.url and r.request.method=='POST' and r.request.post_data_json.get('action')=='save') as saved:
                page.locator('[data-slam="save"]').click()
            response=saved.value.json();assert response['ok'],response
            identity=response['result']['id'];page.locator('#slam-map-id').select_option(identity)
            page.locator('[data-slam="load"]').click();page.locator('[data-slam="loaded_rviz_start"]').click()
            view=wait(lambda:(s if (s:=mid(sid,vid))['tools'].get('slam-rviz',{}).get('ready') and s['tools']['slam-rviz']['context']['ros_domain_id']!=s['domains'].get('live') else None),100)
            goal(view['tools']['slam-rviz']['pid'],capture=directory/(label+'-saved-map.png'),select=False)
        page.locator('#slam-panel').screenshot(path=str(directory/(label+'-slam-web.png')))
        report['checks'][label+'_SLAM_UI_actual_view']='PASS'
        return status()
    def audit(before,abnormal=False):
        launcher.wait(135);log.close()
        path=Path(current['run_dir']);state=json.loads((path/'state.json').read_text());cleanup=json.loads((path/'os-cleanup.json').read_text())
        assert state['state']==('CRASHED' if abnormal else 'STOPPED'),state
        assert not cleanup['remaining_owned_processes'] and not cleanup['credential_errors'],cleanup
        assert not process_table(current['cgroup'])
        for row in before:
            try:assert process_identity(row['pid'])!=row['start_ticks'],row
            except OSError:pass
        report['runs'][-1].update(final_state=state['state'],os_audit=cleanup,processes_before=before)
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
    try:
        if service_state(unit_name(root)).get('ActiveState') in ('active','activating','deactivating'):
            report.update(status='BLOCKED',error='existing operator Center is not taken over');return report
        password_path=runtime/'state/control-center/password.json';password_path.parent.mkdir(parents=True,mode=0o700);set_password(password_path,password)
        launch()
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(viewport=dict(width=1520,height=1100));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                login(page,f'http://127.0.0.1:{port}',password,'/simulation')
                page.locator('[data-scene="L01"]').click();page.locator('#config-vehicle').select_option('rover');page.locator('#enable-mid360').check()
                if slam:page.locator('#enable-mid360-lio').check()
                page.locator('#add-config-vehicle').click();page.locator('#vehicle-instances fieldset label select').first.select_option('copter')
                with page.expect_response(lambda r:'/api/simulation/create' in r.url and r.request.method=='POST') as created:page.locator('#create-session').click()
                response=created.value.json();assert response['ok'],response;sid=response['result']['id']
                page.locator('[data-operation="start"]').click()
                def ready_world():
                    s=api('/api/simulation/report',dict(id=sid))
                    if s['state']=='FAILED':raise AssertionError(s['error'])
                    return s if s['state']=='RUNNING' and len(s.get('vehicles',[]))==2 and all(v['state']=='RUNNING' for v in s['vehicles']) else None
                world=wait(ready_world,180);vehicles=world['vehicles'];report['world']=world
                for v in vehicles:wait(lambda:mid(sid,v['id'])['online'],30)
                page.locator('#open-gazebo-gui').click()
                def gui():
                    s=api('/api/center/state');t=next(t for t in s['tools'] if t['manifest']['id']=='gazebo-gui');return t['instance'] if t.get('instance',{} ) and t['instance']['ready'] else None
                def mapped_gui():
                    s=api('/api/center/state');t=next(t for t in s['tools'] if t['manifest']['id']=='gazebo-gui')
                    return t['instance'] if t.get('instance') and t['instance'].get('windows') else None
                pending=wait(mapped_gui,30);goal(pending['pid'],capture=directory/'center-gazebo-before-readiness.png',select=False)
                gz=wait(gui,100);goal(gz['pid'],capture=directory/'center-gazebo.png',select=False)
                bags={}
                for v in vehicles:
                    vid=v['id'];kind=v['kind'];page.locator('#current-vehicle').select_option(vid)
                    expect(page.locator('#mid360-panel')).to_be_visible();button(page,'record_start');wait(lambda:mid(sid,vid)['recording'],15)
                    start_scan=mid(sid,vid)['health'].get('sequence',0)
                    first=rviz(page,sid,vid,kind+'-center-live');button(page,'rviz_stop');wait(lambda:not mid(sid,vid)['tools']['rviz2']['process_running'],20)
                    second=rviz(page,sid,vid,kind+'-center-reopened');assert first!=second and mid(sid,vid)['online']
                    button(page,'rviz_stop')
                    if slam:
                        slam_ui(page,sid,vid,kind+'-live',save=True)
                        page.locator('[data-slam="stop"]').click();wait(lambda:not api('/api/simulation/slam',dict(id=sid,vehicle_id=vid,action='status'))['running'],30)
                        # Single-pass playback needs an actual acquisition
                        # interval long enough for raw-view + LIO/GUI startup.
                        # Count real 10 Hz captures; wall sleeps cannot prove
                        # duration when the renderer runs below real time.
                        wait(lambda:mid(sid,vid)['health'].get('sequence',0)-start_scan>=500,180)
                    bags[vid]=finalized(page,sid,vid)
                    if slam:
                        ns=mid(sid,vid)['namespace']
                        assert bags[vid]['message_counts'].get(ns+'/custom',0)>=450,bags[vid]
                    page.locator('#mid360-panel').screenshot(path=str(directory/(kind+'-web-panel.png')))
                    report['checks'][kind+'_UI_selection_live_rviz_reopen_record']='PASS'
                report['bags']=bags
                # The Center deployment remains receive-only throughout.
                control=api('/api/control/state')
                for vehicle in control['vehicles']:
                    assert not vehicle['system_send'] and not vehicle['action_send'] and vehicle['writer']['attempts']==0,vehicle
                page.locator('[data-operation="stop"]').click();wait(lambda:api('/api/simulation/report',dict(id=sid))['cleanup']=='COMPLETE',100)
                for v in vehicles:assert mid(sid,v['id'])['live_closed'] and not mid(sid,v['id'])['online']
                rover=next(v for v in vehicles if v['kind']=='rover');vid=rover['id']
                page.locator('#current-vehicle').select_option(vid);page.locator('#mid360-source').select_option('replay');button(page,'replay_once' if slam else 'replay_start')
                wait(lambda:mid(sid,vid)['replay_source']=='rosbag2',20);observe(sid,vid,'stopped-world-replay');rviz(page,sid,vid,'stopped-world-replay')
                if slam:assert slam_ui(page,sid,vid,'stopped-world-replay')['source']=='replay'
                report['checks']['stopped_world_UI_replay']='PASS'
                before=api('/api/center/state')['processes'];page.goto(f'http://127.0.0.1:{port}/center');expect(page.locator('#shutdown')).to_be_enabled();page.locator('#shutdown').click();audit(before)
                report['checks']['normal_backend_cleanup']='PASS'
                # A completely new Control Center application directory.
                launch();login(page,f'http://127.0.0.1:{port}',password,'/simulation')
                page.locator('[data-tab="sessions"]').click();page.locator('[data-session="'+sid+'"]').click();page.locator('#current-vehicle').select_option(vid)
                assert mid(sid,vid)['live_closed'] and not mid(sid,vid)['tools']
                page.locator('#mid360-source').select_option('replay');button(page,'replay_once' if slam else 'replay_start');observe(sid,vid,'restarted-backend-replay');rviz(page,sid,vid,'restarted-backend-replay')
                if slam:assert slam_ui(page,sid,vid,'restarted-backend-replay')['source']=='replay'
                report['checks']['fresh_backend_UI_recording_recovery']='PASS'
                # Add another owned live simulation while the old replay runs.
                crash=api('/api/simulation/create',dict(scene_id='L01',vehicles=[dict(kind='rover',spawn=dict(id='center'),sensors=dict(mid360=True,**({'mid360_lio':True} if slam else {})))],parameters=dict(obstacle_count=0)))
                api('/api/simulation/start',dict(id=crash['id']))
                def crash_ready():
                    s=api('/api/simulation/report',dict(id=crash['id']))
                    if s['state']=='FAILED':raise AssertionError(s['error'])
                    return s if s['state']=='RUNNING' and s.get('vehicles') and s['vehicles'][0]['state']=='RUNNING' else None
                fresh=wait(crash_ready,180);fresh_vid=fresh['vehicles'][0]['id'];wait(lambda:mid(crash['id'],fresh_vid)['online'],30)
                mid(crash['id'],fresh_vid,'record_start');time.sleep(5)
                if slam:
                    api('/api/simulation/slam',dict(id=crash['id'],vehicle_id=fresh_vid,action='start'))
                    wait(lambda:api('/api/simulation/slam',dict(id=crash['id'],vehicle_id=fresh_vid,action='status'))['online'],70)
                    # The earlier single pass can have naturally finished
                    # while the new World started. Create a fresh replay cut
                    # and prove BOTH dependencies are live before SIGKILL.
                    mid(sid,vid,'replay_once',bag_id=bags[vid]['id'])
                    api('/api/simulation/slam',dict(id=sid,vehicle_id=vid,action='start',source='replay'))
                    wait(lambda:api('/api/simulation/slam',dict(id=sid,vehicle_id=vid,action='status'))['online'],40)
                    assert api('/api/simulation/slam',dict(id=crash['id'],vehicle_id=fresh_vid,action='status'))['online']
                before=api('/api/center/state')['processes'];assert any('mid360_worker' in str(p) for p in before) and any('ros2 bag record' in str(p) for p in before)
                os.kill(current['pid'],signal.SIGKILL);audit(before,abnormal=True)
                report['checks']['abnormal_backend_cgroup_cleanup']='PASS'
                launch();login(page,f'http://127.0.0.1:{port}',password,'/simulation');page.locator('[data-tab="sessions"]').click();page.locator('[data-session="'+sid+'"]').click();page.locator('#current-vehicle').select_option(vid)
                page.locator('#mid360-source').select_option('replay');button(page,'replay_once' if slam else 'replay_start');observe(sid,vid,'crash-recovered-replay');rviz(page,sid,vid,'crash-recovered-replay')
                if slam:assert slam_ui(page,sid,vid,'crash-recovered-replay')['source']=='replay'
                report['checks']['crash_restart_finalized_recording_recovery']='PASS'
                report['browser_errors']=errors;assert not errors,errors
                before=api('/api/center/state')['processes'];page.goto(f'http://127.0.0.1:{port}/center');expect(page.locator('#shutdown')).to_be_enabled();page.locator('#shutdown').click();audit(before)
                report['checks']['final_cleanup']='PASS';report['status']='PASS'
            finally:browser.close()
    except Exception:report['error']=traceback.format_exc();print(report['error'],flush=True)
    finally:
        if launcher and launcher.poll() is None:
            launcher.terminate()
            try:launcher.wait(135)
            except subprocess.TimeoutExpired:report['cleanup_error']='owned launcher cleanup timed out'
        if log and not log.closed:log.close()
        (directory/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps(dict(status=report['status'],checks=report['checks']),ensure_ascii=False),flush=True);return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True,type=Path);parser.add_argument('--slam',action='store_true');args=parser.parse_args()
    raise SystemExit(0 if run(args.run_dir,slam=args.slam)['status']=='PASS' else 1)

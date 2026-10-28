"""Native desktop RViz + ROS observations + real Web vehicle controls.

Only the owned local SITL launched by program_launch is controlled. The ROS
observer has no vehicle port and the optional candidate publisher is labelled.
"""
import json,os,signal,subprocess,sys,time
from pathlib import Path

from tests.browser_auth import login
from tests.simulation.web_ui_controls import ToolAcceptance,BrowserControlCheck
from vehicle_autonomy.app.web.server import load_token
from vehicle_autonomy.app.visualization.registry import configure
from vehicle_autonomy.app.tools.builtins import registry


class VisualizationAcceptance(ToolAcceptance):
    def __init__(self,directory,native_registry,kind,*,extended=False,lifecycle_only=False):
        super().__init__(directory,native_registry);self.kind=kind;self.extended=extended;self.lifecycle_only=lifecycle_only;self.observer=None;self.observer_log=None
        native=json.loads(Path(native_registry).read_text());self.environment=next(t for t in native['tools'] if t['id']=='ros2')['profiles']['default']['env']
        self.credential=directory/'visualization.private';load_token(self.credential)
        self.config=directory/'source.json';port={'rover':18880,'copter':18881,'plane':18882}[kind]
        self.config.write_text(json.dumps(dict(schema=1,url='http://127.0.0.1:'+str(port),token_file=str(self.credential),use_sim_time=False)))
        manifest=directory.parent/directory.name.removesuffix('-tools')/'manifest.json'
        value=configure(registry(ros_env=self.environment),self.config,self.environment,owned_simulation=manifest)
        value['tools']=[t for t in value['tools'] if t['id'] in ('visualization-bridge','rviz2','ros2','gazebo','sitl')]
        (directory/'registry.json').write_text(json.dumps(value))
    def arguments(self):return super().arguments()+['--visualization-token-file',str(self.credential),'--source-time-sync']
    def close(self):
        if self.observer and self.observer.poll() is None:self.observer.terminate();self.observer.wait(5)
        if self.observer_log:self.observer_log.close()
        super().close();self.credential.unlink(missing_ok=True)
    def exercise(self,kind,base,token,api,oracle,directory):
        from playwright.sync_api import sync_playwright,expect
        namespace='/visual_'+kind;domain={'rover':171,'copter':172,'plane':173}[kind]
        context=dict(vehicle_id=kind,vehicle_type=kind,environment='simulation',ros_namespace=namespace,ros_domain_id=domain,mavlink_profile='monitor')
        # Configuration only; every vehicle mutation below is an actual UI operation.
        api('/api/settings/context',context)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            c=browser.new_context(viewport={'width':1680,'height':1100});page=c.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            def wait(fn,seconds=90):
                end=time.monotonic()+seconds
                while time.monotonic()<end:
                    value=fn()
                    if value:return value
                    page.wait_for_timeout(150)
                raise TimeoutError('native RViz/ROS condition')
            try:
                login(page,base,token,'/control');expect(page.locator('#open-rviz')).to_be_enabled(timeout=20000)
                initial={a['id'] for a in api('/api/instances')};page.locator('#open-rviz').click()
                def actual():
                    agents=api('/api/console/state')['tools']['agents'];tools={t['manifest']['id']:t for a in agents for t in a['tools']}
                    return tools if all((tools.get(k,{}).get('instance') or {}).get('ready') for k in ('visualization-bridge','rviz2')) else None
                tools=wait(actual,120);print(kind+': native RViz + matching live bridge Ready',flush=True)
                assert {a['id'] for a in api('/api/instances')}==initial
                env=dict(os.environ,**self.environment,ROS_DOMAIN_ID=str(domain),ROS_NAMESPACE=namespace)
                output=directory/'ros-observation.json';self.observer_log=(directory/'observer.log').open('w')
                self.observer=subprocess.Popen([sys.executable,'-m','tests.visualization.observer','--namespace',namespace,'--output',str(output)],env=env,stdout=self.observer_log,stderr=subprocess.STDOUT)
                def observed():
                    if self.observer.poll() is not None:raise RuntimeError('native ROS observer exited')
                    try:r=json.loads(output.read_text())
                    except (FileNotFoundError,json.JSONDecodeError):return None
                    return r if r['counts'].get('odom',0)>5 and r['counts'].get('tf',0)>5 else None
                observed=wait(observed,20);assert observed['tf_publishers']==1,observed
                assert observed['gps']['altitude'] is None
                proof=dict(source='native RViz2 desktop + live signed SITL data; no fake vehicle data',profile=kind,
                    bridge_pid=tools['visualization-bridge']['instance']['pid'],rviz_pid=tools['rviz2']['instance']['pid'],context=context,initial=observed)
                try:
                    from tests.visualization.desktop import goal
                    proof['native_window']=goal(tools['rviz2']['instance']['pid'],capture=directory/'rviz-window.png',select=False)
                    proof['desktop_screenshot']=True
                except Exception as exc:proof['desktop_screenshot']=False;proof['screenshot_error']=type(exc).__name__
                if self.lifecycle_only:
                    assert kind=='rover'
                    result=dict(passed=True,scenario='native tool lifecycle and real telemetry loss; no additional vehicle Actions',visualization=proof,
                        visualization_lifecycle=self.lifecycle_test(page,base,api,actual,wait,context,directory))
                    assert {a['id'] for a in api('/api/instances')}==initial and not errors,errors
                    (directory/'web-control-result.json').write_text(json.dumps(result,indent=2));return result
                page.locator('#acquire-control').click();expect(page.locator('#top-authority')).to_have_text('Manual Control')
                acceptance=self
                class Check(BrowserControlCheck):
                    def hover_or_ground(inner):
                        if kind=='rover' and acceptance.extended:
                            inner.result['scenario']='Rover forward/stop + actual RViz goal + lifecycle; full control sequence is separate evidence'
                            inner.perform('SetMode',dict(mode='GUIDED'));inner._held(dict(speed_mps=.3,yaw_rate_rad_s=0.),('distance',.5))
                            acceptance.goal_test(inner,api,page,actual,wait)
                        else:super().hover_or_ground()
                check=Check(kind,api,oracle,directory,page);check.perform('Arm',allow_send=False,expected='REJECTED');result=check.run()
                final=json.loads(output.read_text());assert final['max_path']>20 and final['counts']['odom']>30 and final['tf_publishers']==1
                records=[json.loads(line) for line in output.with_suffix('.jsonl').read_text().splitlines()]
                displacement=max(sum((p-q)**2 for p,q in zip(v['position'],records[0]['position']))**.5 for v in records)
                assert displacement>(.5 if kind!='plane' else 30),displacement
                assert all(v['frame']==namespace.lstrip('/')+'/viz/odom' and v['child']==namespace.lstrip('/')+'/viz/base_link' for v in records)
                assert all(a['stamp_ns']<b['stamp_ns'] for a,b in zip(records,records[1:]))
                proof.update(final=final,observed_displacement_m=displacement,monotonic_stamps=True,one_tf_authority=True)
                result['visualization']=proof;result['javascript_errors']=errors;assert not errors;check.save()
                page.locator('#release-control').click();expect(page.locator('#top-authority')).to_have_text('Observer');page.screenshot(path=str(directory/'vehicle-control-rviz.png'),full_page=True)
                if kind=='rover' and self.extended:
                    result['visualization_lifecycle']=self.lifecycle_test(page,base,api,actual,wait,context,directory)
                    check.save()
                return result
            except Exception:
                (directory/'rviz-javascript-errors.json').write_text(json.dumps(errors))
                page.screenshot(path=str(directory/'rviz-failure-web.png'),full_page=True)
                (directory/'rviz-failure-state.json').write_text(json.dumps(api('/api/console/state'),indent=2))
                (directory/'rviz-failure-control.json').write_text(json.dumps(api('/api/control/state'),indent=2))
                raise
            finally:browser.close()

    def goal_test(self,check,api,page,actual,wait):
        from playwright.sync_api import expect
        from tests.visualization.desktop import goal
        check.perform('SetMode',dict(mode='GUIDED'))
        if api('/api/studio/state')['vehicles'][0]['world']['vehicle']['operation']['armed'] is False:check.perform('Arm')
        tools=wait(actual,25)
        before={a['id'] for a in api('/api/instances')};previous={g['id'] for g in api('/api/visualization/candidates?target=rover')}
        mouse=goal(tools['rviz2']['instance']['pid'])
        selected=wait(lambda:next((g for g in api('/api/visualization/candidates?target=rover') if g['id'] not in previous),None),8)
        assert before=={a['id'] for a in api('/api/instances')},'RViz selection executed without confirmation'
        row=page.locator('[data-goal="'+selected['id']+'"]');row.get_by_role('button',name='核对并提交').click()
        expect(page.locator('#command-confirm')).to_be_visible();expect(page.locator('#confirm-submit')).to_be_disabled()
        assert before=={a['id'] for a in api('/api/instances')}
        page.locator('#confirm-send').check();page.locator('#confirm-submit').click()
        action=wait(lambda:next((a for a in api('/api/instances') if a['id'] not in before),None),8)
        final=check.finish(action,65);truth=check.truth()
        check.result['rviz_pending_goal']=dict(source='actual owned native RViz SetGoal mouse drag, then Web confirmation',mouse=mouse,candidate=selected,
            no_action_before_confirmation=True,action=dict(id=final['id'],name=final['name'],state=final['state']),truth=[truth.x_m,truth.y_m,truth.z_m])
        check.perform('Disarm');print('rover: native RViz pending goal → Web confirmation → existing Goto physically completed',flush=True)

    def lifecycle_test(self,page,base,api,actual,wait,context,directory):
        from playwright.sync_api import expect
        snapshot=api('/api/console/state');run=next(r for r in snapshot['tools']['workspaces']['runs'] if r['spec']['id'].startswith('visualization-') and r['state'] not in ('STOPPED','FAILED'))
        # A real Wait Mission is independent of visual tools and has no vehicle writes.
        spec=dict(schema_version=1,id='rviz-independent-wait',name='Visualization lifecycle isolation',version='1.0.0',timeout_s=60.,target='rover',root='wait',nodes=[dict(id='wait',type='Wait',duration_s=20.,timeout_s=50.)])
        mission=api('/api/missions/start',dict(spec=spec));mission_id=mission['id'];before={a['id'] for a in api('/api/instances')}
        os.kill(self.process.pid,signal.SIGSTOP)
        try:
            wait(lambda:not api('/api/console/state')['tools']['agents'][0]['connected'],12)
            unknown=wait(lambda:next((r for r in api('/api/console/state')['tools']['workspaces']['runs'] if r['id']==run['id'] and r['state']=='UNKNOWN' and r['recovering']),None),5)
        finally:os.kill(self.process.pid,signal.SIGCONT)
        wait(lambda:api('/api/console/state')['tools']['agents'][0]['connected'],10)
        page.goto(base+'/console#workspaces');assert '/login' not in page.url
        row=page.locator('.workspace-row').filter(has_text=run['spec']['id']);row.get_by_role('button',name='按当前实例恢复记录',exact=True).click()
        wait(lambda:next((r for r in api('/api/console/state')['tools']['workspaces']['runs'] if r['id']==run['id'] and r['state']=='READY'),None),25)
        pids={k:v['instance']['pid'] for k,v in actual().items() if k in ('rviz2','visualization-bridge')}
        row.get_by_role('button',name='Stop Workspace',exact=True).click()
        wait(lambda:next((r for r in api('/api/console/state')['tools']['workspaces']['runs'] if r['id']==run['id'] and r['state']=='STOPPED'),None),35)
        assert all(not Path('/proc',str(pid)).exists() for pid in pids.values())
        state=next(m for m in api('/api/studio/state')['missions'] if m['id']==mission_id);assert state['state'] not in ('CANCELLED','FAILED','UNKNOWN')
        page.goto(base+'/console#tools');bridge=page.locator('[data-tool="desktop:visualization-bridge"]');rviz=page.locator('[data-tool="desktop:rviz2"]')
        bridge.locator('select').select_option('rover');bridge.get_by_role('button',name='Launch',exact=True).click()
        wait(lambda:next((t for a in api('/api/console/state')['tools']['agents'] for t in a['tools'] if t['manifest']['id']=='visualization-bridge' and t['instance'] and t['instance']['ready']),None),60)
        rviz.locator('select').select_option('rover');rviz.get_by_role('button',name='Launch',exact=True).click();first=wait(actual,90)
        old=first['rviz2']['instance']['pid'];stable=first['visualization-bridge']['instance']['pid']
        rviz.get_by_role('button',name='Logs',exact=True).click();expect(page.locator('#tool-detail pre')).not_to_have_text('')
        rviz.get_by_role('button',name='Restart',exact=True).click()
        second=wait(lambda:(v if (v:=actual()) and v['rviz2']['instance']['pid']!=old else None),90)
        assert not Path('/proc',str(old)).exists() and second['visualization-bridge']['instance']['pid']==stable
        # The Simulation preset validates the *same* running owned simulator;
        # these non-owning observers never start a second SITL or kill it.
        definition=api('/api/workspaces/template',dict(template_id='simulation-visualization',context=context));api('/api/workspaces/save',dict(spec=definition))
        page.goto(base+'/console#workspaces');sim=page.locator('.workspace-row').filter(has_text=definition['id']);sim.get_by_role('button',name='Launch Workspace',exact=True).click()
        prepared=wait(lambda:next((r for r in api('/api/console/state')['tools']['workspaces']['runs'] if r['spec']['id']==definition['id'] and r['state']=='READY'),None),90)
        sim.get_by_role('button',name='Stop Workspace',exact=True).click();wait(lambda:next((r for r in api('/api/console/state')['tools']['workspaces']['runs'] if r['id']==prepared['id'] and r['state']=='STOPPED'),None),30)
        assert actual()['visualization-bridge']['instance']['pid']==stable
        assert before=={a['id'] for a in api('/api/instances')}
        wait(lambda:next((m for m in api('/api/studio/state')['missions'] if m['id']==mission_id and m['state']=='SUCCEEDED'),None),30)
        assert api('/api/studio/state')['vehicles'][0]['connected']
        # Stop only this run's owned, already disarmed SITL temporarily. This is
        # an actual transport blackout, not a synthetic stale timestamp.
        owned=json.loads((directory/'manifest.json').read_text());sitl=next(p['pid'] for p in owned['processes'] if p['name']=='sitl')
        os.kill(sitl,signal.SIGSTOP)
        try:
            output=directory/'ros-observation.json'
            lost=wait(lambda:(r if (r:=json.loads(output.read_text())).get('status',{}).get('valid') is False and r.get('path_length')==0 else None),12)
            count=lost['counts']['odom'];page.wait_for_timeout(1600);after=json.loads(output.read_text());assert after['counts']['odom']==count and after['delete_seen']
            from tests.visualization.desktop import goal
            goal(second['rviz2']['instance']['pid'],capture=directory/'rviz-source-disconnected.png',select=False)
        finally:os.kill(sitl,signal.SIGCONT)
        rviz_pid=second['rviz2']['instance']['pid'];page.goto(base+'/console#tools');rviz=page.locator('[data-tool="desktop:rviz2"]');rviz.locator('select').select_option('rover');rviz.get_by_role('button',name='Stop',exact=True).click()
        wait(lambda:not Path('/proc',str(rviz_pid)).exists(),20)
        page.screenshot(path=str(directory/'tool-lifecycle.png'),full_page=True)
        return dict(actual_native_rviz_restart=True,logs=True,old_pid=old,new_pid=rviz_pid,bridge_pid_unchanged=stable,
            actual_agent_heartbeat_loss=True,explicit_reconciliation=True,no_second_login=True,simulation_workspace_ready=True,
            shared_manual_bridge_survived_workspace_stop=True,wait_mission_succeeded=True,no_vehicle_actions_from_lifecycle=True,
            actual_owned_sitl_blackout=True,stale_pose_not_republished=True,live_markers_deleted=True,path_cleared=True)

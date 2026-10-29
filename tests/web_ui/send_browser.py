"""Actual browser/HTTP SEND switch tests with explicit state/Action fixtures.

No physical vehicle or SITL command is emitted. Action fixtures advance the
displayed state so real UI eligibility and server reservation checks are tested.
"""
import argparse,json,time
from dataclasses import replace,asdict
from pathlib import Path


def run(directory):
    from playwright.sync_api import sync_playwright,expect
    from tests.browser_auth import login
    from tests.web_ui.helpers import Harness
    from vehicle_autonomy.actions.common.standard import Empty,ModeParameters
    from vehicle_autonomy.actions.copter.standard import TakeoffParameters,VelocityParameters
    from vehicle_autonomy.contracts.action import ActionKind
    from vehicle_autonomy.contracts.decision import ActionSpec,ActionDecision,ActionOutcome,ExitDecision
    h=Harness(directory/'server',kinds=('copter','rover','plane'));model={k:dict(armed=False,mode=0,height=0.) for k in h.drivers};errors=[];requests=[];updates=[]
    for kind,driver in h.drivers.items():
        original=driver.snapshot
        def snapshot(original=original,kind=kind):
            world=original();v=world.vehicle;m=model[kind]
            pose=replace(v.reported_pose,value=replace(v.reported_pose.value,position=replace(v.reported_pose.value.position,z=m['height'])))
            return replace(world,vehicle=replace(v,reported_pose=pose,operation=replace(v.operation,armed=m['armed'],native_mode='ARDUPILOT_CUSTOM_'+str(m['mode']))))
        driver.snapshot=snapshot
    class FixtureAction:
        def __init__(self,name,p,kind):self.name=name;self.p=p;self.kind=kind
        def tick(self,world):
            m=model[self.kind]
            if self.name=='SetMode':m['mode']={'GUIDED':4,'LOITER':5,'HOLD':4,'MANUAL':0}[self.p.mode]
            if self.name in ('Arm','Disarm'):m['armed']=self.name=='Arm'
            if self.name=='Takeoff':m['height']=self.p.height_m
            if self.name=='Land':m.update(height=0.,armed=False)
            return ActionDecision(ActionOutcome.RUNNING if self.name=='SetVelocity' else ActionOutcome.SUCCEEDED)
        def update_input(self,p):self.p=p;updates.append(asdict(p))
        def exit(self,world,reason):return ExitDecision(True)
    class Factory:
        supports_input_updates=True
        def __init__(self,name):self.name=name
        def validate_context(self,p,w,c):
            if self.name=='SetVelocity' and (not w.vehicle.operation.armed or w.vehicle.operation.native_mode!='ARDUPILOT_CUSTOM_4'):raise ValueError('fixture requires armed GUIDED state')
        def start(self,p,w):return FixtureAction(self.name,p,w.vehicle.vehicle_id)
    for name,params in [('Arm',Empty),('Disarm',Empty),('SetMode',ModeParameters),('Takeoff',TakeoffParameters),('Land',Empty),('SetVelocity',VelocityParameters)]:
        h.lab.registry.register_typed(ActionSpec(name,params,kind=ActionKind.CONTINUOUS if name=='SetVelocity' else ActionKind.ONE_SHOT),Factory(name))
    directory.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                context=b.new_context(viewport={'width':1440,'height':1100});page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:requests.append((r.url.split(h.base)[-1],r.post_data_json)) if r.method=='POST' and '/api/' in r.url else None)
                login(page,h.base,h.token,'/control');expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
                expect(page.locator('[data-action="Arm"]')).to_be_disabled();assert not h.lab.runtime.views()
                page.get_by_role('button',name='开启指令发送',exact=True).click();expect(page.locator('#top-authority')).to_have_text('开启指令发送')
                assert not h.lab.runtime.views(),'switch itself created an Action'
                def action(button):
                    before=len(h.lab.runtime.views());button.click()
                    expect(page.locator('#command-confirm')).not_to_be_visible()
                    end=time.monotonic()+5
                    while time.monotonic()<end:
                        actions=h.lab.runtime.views()
                        if len(actions)>before and actions[-1]['state']=='SUCCEEDED':break
                        page.wait_for_timeout(50)
                    else:raise AssertionError([(a['name'],a['state'],a['error']) for a in actions])
                    expect(page.locator('#top-authority')).to_have_text('开启指令发送')
                page.locator('#mode').select_option('GUIDED');action(page.locator('#set-mode'))
                action(page.locator('[data-action="Arm"]'));page.locator('#takeoff-height').fill('1.5');action(page.locator('#takeoff'))
                panel=page.locator('#copter-advanced');panel.locator('summary').click()
                def wait(fn):
                    end=time.monotonic()+5
                    while time.monotonic()<end:
                        value=fn()
                        if value:return value
                        page.wait_for_timeout(30)
                    raise AssertionError('persistent stream condition timed out')
                switch=page.locator('#copter-motion-toggle');key=page.locator('#copter-stream [data-key="w"]')
                expect(key).to_be_disabled();before=len(h.lab.runtime.views());switch.click()
                stream=wait(lambda:next((a for a in h.lab.runtime.views()[before:] if a['name']=='SetVelocity' and a['state']=='RUNNING'),None));stream_id=stream['id']
                wait(lambda:updates and updates[-1]['vx_mps']==0)
                for _ in range(2):
                    mark=len(updates);expect(key).to_be_enabled();key.hover();page.mouse.down()
                    try:
                        wait(lambda:any(p['vx_mps']>0 for p in updates[mark:]))
                    finally:page.mouse.up()
                    wait(lambda:updates[-1]['vx_mps']==0);sequence=h.lab.runtime.view(stream_id)['input_sequence']
                    page.wait_for_timeout(750)
                    assert h.lab.runtime.view(stream_id)['state']=='RUNNING' and h.lab.runtime.view(stream_id)['input_sequence']>sequence
                    assert len(h.lab.runtime.views())==before+1
                page.locator('#copter-manual-stop').click();page.wait_for_timeout(500)
                assert h.lab.runtime.view(stream_id)['state']=='RUNNING' and updates[-1]['vx_mps']==0
                # Rapid changes must not violate the server's 20Hz input fence.
                for _ in range(5):
                    key.hover();page.mouse.down();page.wait_for_timeout(20);page.mouse.up();page.wait_for_timeout(20)
                page.wait_for_timeout(500);assert h.lab.runtime.view(stream_id)['state']=='RUNNING'
                assert not any(p=='/api/manual/stop' for p,b in requests)
                switch.click();wait(lambda:h.lab.runtime.view(stream_id)['state']=='CANCELLED');expect(switch).to_have_attribute('aria-pressed','false')
                # Losing both update and stop transport still triggers the
                # independent real backend deadman, without automatic restart.
                before=len(h.lab.runtime.views());switch.click();lost=wait(lambda:next((a for a in h.lab.runtime.views()[before:] if a['state']=='RUNNING'),None))
                blocker=lambda route:route.abort();page.route('**/api/manual/update',blocker);page.route('**/api/manual/stop',blocker)
                try:wait(lambda:h.lab.runtime.view(lost['id'])['state']=='TIMED_OUT')
                finally:page.unroute('**/api/manual/update',blocker);page.unroute('**/api/manual/stop',blocker)
                expect(switch).to_have_attribute('aria-pressed','false');count=len(h.lab.runtime.views());page.wait_for_timeout(600);assert len(h.lab.runtime.views())==count
                # A real browser tab focus change must exit, even at zero speed.
                before=len(h.lab.runtime.views());switch.click();blurred=wait(lambda:next((a for a in h.lab.runtime.views()[before:] if a['state']=='RUNNING'),None))
                focus=page.context.new_cdp_session(page);focus.send('Emulation.setFocusEmulationEnabled',{'enabled':False});page.bring_to_front();other=page.context.new_page();other.bring_to_front()
                try:wait(lambda:h.lab.runtime.view(blurred['id'])['state']=='CANCELLED')
                finally:other.close();page.bring_to_front();focus.send('Emulation.setFocusEmulationEnabled',{'enabled':True});focus.detach()
                expect(switch).to_have_attribute('aria-pressed','false')
                action(page.locator('[data-action="Land"]'))
                assert len([p for p,b in requests if p=='/api/control/acquire'])==1
                sent=[body for path,body in requests if path in ('/api/manual/action','/api/manual/start')];assert len(sent)==7 and all(p['allow_send'] is True for p in sent)
                assert all(p['timeout_s']==60 for p in sent if p['name']=='SetVelocity')
                assert page.locator('#send,#manual-send,#copter-manual-send,#confirm-send').count()==0
                page.get_by_role('button',name='关闭指令发送',exact=True).click();expect(page.locator('#top-authority')).to_have_text('关闭指令发送');expect(page.locator('[data-action="Arm"]')).to_be_disabled()
                for kind in ('rover','plane'):
                    page.locator('#target').select_option(kind);expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
                    page.get_by_role('button',name='开启指令发送',exact=True).click();expect(page.locator('#top-authority')).to_have_text('开启指令发送');action(page.locator('[data-action="Arm"]'));action(page.locator('[data-action="Disarm"]'))
                    page.get_by_role('button',name='关闭指令发送',exact=True).click();expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
                page.set_viewport_size({'width':390,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(directory/'send-switch-mobile.png'),full_page=True)
                assert not errors and not any(d.writes for d in h.drivers.values())
            except Exception:
                debug=dict(errors=errors,notice=page.locator('#notice').inner_text(),requests=requests,
                    actions=[{k:a.get(k) for k in ('name','state','error','input_sequence')} for a in h.lab.runtime.views()],
                    page=page.evaluate('({velocityEnabled,session,input,pending,updating,manual:manual(),fresh:selected()?.fresh_vehicle_state,focus:document.hasFocus(),hidden:document.hidden})'))
                (directory/'failure.json').write_text(json.dumps(debug,indent=2));raise
            finally:b.close()
    finally:h.close()
    report=dict(passed=True,source=__doc__,one_send_on_for_mode_arm_takeoff_two_held_inputs_and_land=True,three_types=True,
        one_velocity_action_across_release_hold_and_resume=True,neutral_heartbeats_keep_same_session=True,rapid_input_keeps_session=True,
        explicit_off_exits=True,independent_watchdog_exits=True,real_browser_blur_exits=True,no_auto_restart=True,stream_timeout_s=60,
        no_per_action_dialog_or_checkbox=True,off_disables_commands=True,no_action_from_toggle=True,zero_vehicle_writes=True,javascript_errors=errors)
    (directory/'summary.json').write_text(json.dumps(report,indent=2));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);print(json.dumps(run(p.parse_args().run_dir)))

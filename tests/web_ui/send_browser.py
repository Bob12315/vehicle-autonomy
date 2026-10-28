"""Actual browser/HTTP SEND switch tests with explicit state/Action fixtures.

No physical vehicle or SITL command is emitted. Action fixtures advance the
displayed state so real UI eligibility and server reservation checks are tested.
"""
import argparse,json,time
from dataclasses import replace
from pathlib import Path


def run(directory):
    from playwright.sync_api import sync_playwright,expect
    from tests.browser_auth import login
    from tests.web_ui.helpers import Harness
    from vehicle_autonomy.actions.common.standard import Empty,ModeParameters
    from vehicle_autonomy.actions.copter.standard import TakeoffParameters,VelocityParameters
    from vehicle_autonomy.contracts.action import ActionKind
    from vehicle_autonomy.contracts.decision import ActionSpec,ActionDecision,ActionOutcome,ExitDecision
    h=Harness(directory/'server',kinds=('copter','rover','plane'));model={k:dict(armed=False,mode=0,height=0.) for k in h.drivers};errors=[];requests=[]
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
        def update_input(self,p):self.p=p
        def exit(self,world,reason):return ExitDecision(True)
    class Factory:
        supports_input_updates=True
        def __init__(self,name):self.name=name
        def start(self,p,w):return FixtureAction(self.name,p,w.vehicle.vehicle_id)
    for name,params in [('Arm',Empty),('Disarm',Empty),('SetMode',ModeParameters),('Takeoff',TakeoffParameters),('Land',Empty),('SetVelocity',VelocityParameters)]:
        h.lab.registry.register_typed(ActionSpec(name,params,kind=ActionKind.CONTINUOUS if name=='SetVelocity' else ActionKind.ONE_SHOT),Factory(name))
    directory.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            b=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=b.new_page(viewport={'width':1440,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:requests.append((r.url.split(h.base)[-1],r.post_data_json)) if r.method=='POST' and '/api/' in r.url else None)
                login(page,h.base,h.token,'/control');expect(page.locator('#top-authority')).to_have_text('SEND OFF')
                expect(page.locator('[data-action="Arm"]')).to_be_disabled();assert not h.lab.runtime.views()
                page.get_by_role('button',name='SEND ON',exact=True).click();expect(page.locator('#top-authority')).to_have_text('SEND ON')
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
                    expect(page.locator('#top-authority')).to_have_text('SEND ON')
                page.locator('#mode').select_option('GUIDED');action(page.locator('#set-mode'))
                action(page.locator('[data-action="Arm"]'));page.locator('#takeoff-height').fill('1.5');action(page.locator('#takeoff'))
                panel=page.locator('#copter-advanced');panel.locator('summary').click()
                for _ in range(2):
                    before=len(h.lab.runtime.views());key=page.locator('#copter-stream [data-key="w"]');expect(key).to_be_enabled();key.hover();page.mouse.down()
                    try:
                        end=time.monotonic()+4
                        while len(h.lab.runtime.views())==before and time.monotonic()<end:page.wait_for_timeout(30)
                        assert len(h.lab.runtime.views())==before+1
                    finally:page.mouse.up()
                    end=time.monotonic()+4
                    while h.lab.runtime.views()[-1]['state']!='CANCELLED' and time.monotonic()<end:page.wait_for_timeout(30)
                    assert h.lab.runtime.views()[-1]['state']=='CANCELLED'
                action(page.locator('[data-action="Land"]'))
                assert len([p for p,b in requests if p=='/api/control/acquire'])==1
                sent=[body for path,body in requests if path in ('/api/manual/action','/api/manual/start')];assert len(sent)==6 and all(p['allow_send'] is True for p in sent)
                assert page.locator('#send,#manual-send,#copter-manual-send,#confirm-send').count()==0
                page.get_by_role('button',name='SEND OFF',exact=True).click();expect(page.locator('#top-authority')).to_have_text('SEND OFF');expect(page.locator('[data-action="Arm"]')).to_be_disabled()
                for kind in ('rover','plane'):
                    page.locator('#target').select_option(kind);expect(page.locator('#top-authority')).to_have_text('SEND OFF')
                    page.get_by_role('button',name='SEND ON',exact=True).click();expect(page.locator('#top-authority')).to_have_text('SEND ON');action(page.locator('[data-action="Arm"]'));action(page.locator('[data-action="Disarm"]'))
                    page.get_by_role('button',name='SEND OFF',exact=True).click();expect(page.locator('#top-authority')).to_have_text('SEND OFF')
                page.set_viewport_size({'width':390,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.screenshot(path=str(directory/'send-switch-mobile.png'),full_page=True)
                assert not errors and not any(d.writes for d in h.drivers.values())
            finally:b.close()
    finally:h.close()
    report=dict(passed=True,source=__doc__,one_send_on_for_mode_arm_takeoff_two_held_inputs_and_land=True,three_types=True,
        no_per_action_dialog_or_checkbox=True,off_disables_commands=True,no_action_from_toggle=True,zero_vehicle_writes=True,javascript_errors=errors)
    (directory/'summary.json').write_text(json.dumps(report,indent=2));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);print(json.dumps(run(p.parse_args().run_dir)))

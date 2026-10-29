"""Actual Chromium/HTTP UI with explicit fixture telemetry; not SITL evidence."""
import argparse,json,time
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from tests.browser_auth import login
from tests.web_ui.helpers import Harness,FixtureDriver
from tests.tool_agent.test_service import Harness as ToolHarness
from tests.tool_agent.helpers import tool


def run(directory):
 directory.mkdir(parents=True,exist_ok=False,mode=0o700)
 h=Harness(directory/'server',kinds=('rover','copter','plane'),standard=True);errors=[];report=dict(passed=False,source=__doc__)
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
   try:
    context=browser.new_context(viewport={'width':1680,'height':1100});page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    login(page,h.base,h.token,'/control');expect(page.locator('#vehicle-name')).to_contain_text('地面车')
    assert page.locator('#token').count()==0
    expect(page.locator('[data-action="Arm"]')).to_be_disabled()
    page.locator('#acquire-control').click();expect(page.locator('#top-authority')).to_have_text('开启指令发送')
    expect(page.locator('#command-confirm')).not_to_be_visible();assert not h.lab.runtime.views()
    page.locator('#release-control').click();expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
    expect(page.locator('[data-action="Arm"]')).to_be_disabled()
    page.screenshot(path=str(directory/'rover-desktop.png'),full_page=True)
    for kind in ('copter','plane','rover'):
     page.locator('#target').select_option(kind);expect(page.locator('#vehicle-name')).to_contain_text(kind,ignore_case=True)
     expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
     if kind=='plane':
      expect(page.locator('[data-for=plane]')).to_be_visible();expect(page.get_by_role('button',name='悬停 · 不支持',exact=True)).to_be_disabled()
      expect(page.locator('#vehicle-status')).to_contain_text('空速')
     if kind=='copter':
      expect(page.locator('#takeoff-height')).to_have_value('1.5');expect(page.locator('#takeoff')).to_be_disabled()
    for width in (1680,1280,1024,768,390):
     page.set_viewport_size({'width':width,'height':1000});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
     if width in (1024,390):page.screenshot(path=str(directory/f'control-{width}.png'),full_page=True)
    page.set_viewport_size({'width':1680,'height':1100})
    for path in ('/console#dashboard','/console#tools','/console#workspaces','/console#logs','/console#settings','/studio','/control','/'):
     page.goto(h.base+path);page.wait_for_function('window.VAFAuth && window.VAFAuth.session');assert '/login' not in page.url
     assert page.locator('#login-key').count()==0 and page.locator('#token').count()==0
    page.goto(h.base+'/control');page.reload();expect(page.locator('#vehicle-name')).to_contain_text('地面车');expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
    assert page.evaluate('Object.keys(localStorage).length')==0
    # Browser transport reconnect must restore data without acquiring control.
    page.locator('#acquire-control').click();expect(page.locator('#top-authority')).to_have_text('开启指令发送')
    context.set_offline(True);page.wait_for_timeout(2200);context.set_offline(False)
    expect(page.locator('#top-authority')).to_have_text('关闭指令发送',timeout=16000)
    expect(page.locator('#vehicle-name')).to_contain_text('地面车',timeout=15000)
    page.locator('[data-logout]').click();page.wait_for_url('**/login?next=**');expect(page.locator('#login-key')).to_be_visible()
    login(page,h.base,h.token,'/control');expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
    h.server.sessions.lifetime_s=.01;page.wait_for_url('**/login?next=**',timeout=6000)
    report.update(passed=not errors,javascript_errors=errors,three_types=True,send_switch=True,per_action_authorization=False,one_login_across_pages=True,refresh_restores_session=True,reconnect_stays_observer=True,logout=True,expiry=True,widths=[1680,1280,1024,768,390],vehicle_writes=sum(len(d.writes) for d in h.drivers.values()))
    assert not errors and report['vehicle_writes']==0
   finally:browser.close()
 finally:h.close()
 # Control-page shortcut -> same Tool Manager API -> actual owned test process.
 manifest=tool('rviz2');manifest['type']='gui';manifest['name']='RViz shortcut process fixture'
 th=ToolHarness(directory/'tools',[manifest],drivers={'copter':FixtureDriver('copter')})
 try:
  with sync_playwright() as pw:
   b=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
   try:
    p=b.new_page();login(p,th.base,th.web_token,'/control')
    p.locator('.tool-shortcut').get_by_role('button',name='打开窗口',exact=True).click()
    expect(p.locator('.tool-shortcut button')).to_have_text('已运行',timeout=12000)
    assert th.local.counter==1 and not th.lab.runtime.views()
    report['tool_shortcut_actual_process']=True
   finally:b.close()
 finally:th.close()
 (directory/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));return report

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True)
 print(json.dumps(run(p.parse_args().run_dir),ensure_ascii=False))

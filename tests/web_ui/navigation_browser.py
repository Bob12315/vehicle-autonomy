"""Chrome navigation and layout acceptance; --native also uses owned C01 SITL.

The fixture stages test absent/configured remote services. Native mode starts
./control-center, uses its password login and creates/stops a real Copter World.
No movement, SEND reservation, arm, or task is requested.
"""
import argparse
from contextlib import ExitStack
import getpass
import json
from pathlib import Path
import signal
import subprocess
import time
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from tests.browser_auth import login
from tests.web_ui.helpers import Harness
from tests.tool_agent.test_service import Harness as ToolHarness

ROOT = Path(__file__).resolve().parents[2]


def run(directory, *, native=False, password=None):
    from playwright.sync_api import sync_playwright, expect
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    report = dict(status='FAIL', stages=[], javascript_errors=[], no_vehicle_actions=True)
    process = None
    native_state = None
    errors = report['javascript_errors']
    def audit(page, base, credential, name, *, local=False, remote=False):
        page.on('pageerror', lambda error: errors.append(str(error)))
        stage = dict(name=name, local=local, remote=remote, pages=[], redirects=[])
        report['stages'].append(stage)
        login(page, base, credential)
        expected = ['dashboard', 'simulation', 'control', 'studio'] + (['center'] if local else [])
        canonical = None
        for path, selected in [('/console#dashboard', 'dashboard'), ('/simulation', 'simulation'),
                               ('/control', 'control'), ('/studio', 'studio')] + ([('/center', 'center')] if local else []) + [('/', 'actions')]:
            page.goto(base + path)
            expect(page.locator('[data-navigation] nav[aria-label="主导航"] a')).to_have_count(len(expected))
            expect(page.locator('[data-navigation] [aria-current=page]')).to_have_attribute('data-nav-id', selected)
            if selected=='center':
                expect(page.locator('#connection')).to_contain_text('已连接',timeout=20000)
                expect(page.locator('#tools [data-tool]')).to_have_count(3)
            menu = page.locator('[data-navigation] [data-nav-id]').evaluate_all('(links)=>links.map(a=>({id:a.dataset.navId,href:a.getAttribute("href"),text:a.textContent}))')
            if canonical is None: canonical = menu
            assert menu == canonical, (path, menu, canonical)
            assert [i['id'] for i in menu[:len(expected)]] == expected
            assert len({i['href'] for i in menu}) == len(menu)
            assert not page.locator('[data-navigation] a[href="/studio/legacy"]').count()
            for entry in menu:
                response = page.request.get(base + entry['href'].split('#')[0])
                assert response.status == 200, (entry, response.status)
            if not remote:
                assert not any(i['id'] in ('tools', 'workspaces', 'logs', 'settings') for i in menu)
            else:
                assert {'tools', 'workspaces', 'logs', 'settings'} <= {i['id'] for i in menu}
            for width in (1440, 1024, 768, 390):
                page.set_viewport_size(dict(width=width, height=1000))
                fits=page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                if not fits:
                    page.screenshot(path=str(directory/'layout-failure.png'),full_page=True)
                    report['overflow']=page.locator('body *').evaluate_all('(nodes)=>nodes.filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,id:e.id,cls:e.className,right:e.getBoundingClientRect().right,text:e.textContent.slice(0,120)})).slice(0,30)')
                assert fits, (name, path, width)
            page.set_viewport_size(dict(width=1440, height=1000))
            if local and selected in ('center', 'simulation', 'control', 'studio', 'actions'):
                page.screenshot(path=str(directory/(selected+'-desktop.png')), full_page=True)
            stage['pages'].append(path)
        stage['menu'] = canonical
        # Real clicks, not just href inspection; no control operations are clicked.
        page.locator('[data-navigation] a[data-nav-id="simulation"]').click()
        expect(page.locator('h1')).to_have_text('仿真中心')
        page.locator('[data-navigation] a[data-nav-id="studio"]').click()
        expect(page.locator('h1')).to_have_text('任务库')
        page.locator('[data-navigation] a[data-nav-id="dashboard"]').click()
        expect(page.locator('#page-title')).to_have_text('车辆总览')
        for old in ('tools', 'workspaces', 'logs', 'settings'):
            page.goto(base+'/console#'+old)
            if remote:
                expect(page.locator('[data-navigation] [aria-current=page]')).to_have_attribute('data-nav-id', old)
                expect(page.locator('[data-panel="'+old+'"]')).to_be_visible()
            else:
                expected_path = '/center' if local else '/console'
                page.wait_for_url(lambda url: urlsplit(url).path == expected_path and (local or urlsplit(url).fragment == 'dashboard'))
                expect(page.locator('[data-navigation] [aria-current=page]')).to_have_attribute('data-nav-id', 'center' if local else 'dashboard')
            stage['redirects'].append(page.url.removeprefix(base))
        if local:
            expect(page.locator('#connection')).to_contain_text('已连接',timeout=20000)
            expect(page.locator('#tools [data-tool]')).to_have_count(3)
            page.set_viewport_size(dict(width=390, height=1000))
            page.screenshot(path=str(directory/'center-mobile.png'), full_page=True)
        stage['status'] = 'PASS'

    try:
        with ExitStack() as stack:
            pw = stack.enter_context(sync_playwright())
            browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True,
                                         args=['--no-sandbox', '--disable-dev-shm-usage'])
            stack.callback(browser.close)
            h = Harness(directory/'no-remote', kinds=(), standard=True)
            stack.callback(h.close)
            audit(browser.new_page(), h.base, h.token, 'mission-without-remote')
            th = ToolHarness(directory/'remote')
            stack.callback(th.close)
            # A disconnected configured Agent remains a valid diagnostic page.
            th.service.remote_enabled = True
            audit(browser.new_page(), th.base, th.web_token, 'configured-remote', remote=True)
            assert not th.lab.runtime.views() and not h.lab.runtime.views()
            if native:
                if password is None: password = getpass.getpass('控制台登录密码：')
                current = ROOT/'runtime/state/control-center/current.json'
                if current.exists():
                    old = json.loads(current.read_text())
                    if old['state'] in ('STARTING', 'READY', 'STOPPING'):
                        raise RuntimeError('Existing control-center session must be left untouched; native acceptance refused.')
                log = stack.enter_context((directory/'launcher.log').open('w'))
                process = subprocess.Popen([str(ROOT/'control-center'), '--no-browser'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                def wait(predicate, seconds=90):
                    end = time.monotonic()+seconds
                    while time.monotonic()<end:
                        value = predicate()
                        if value:return value
                        if process.poll() is not None:raise RuntimeError('Control Center exited; see launcher.log')
                        time.sleep(.15)
                    raise TimeoutError('native UI acceptance timed out')
                def ready():
                    value = json.loads(current.read_text()) if current.exists() else {}
                    return value if value.get('state')=='READY' and value.get('started_at', 0)>started else None
                started = time.time()-1
                native_state = wait(ready, 60)
                base = native_state['url'].removesuffix('/center')
                key = Path(native_state['token_file']).read_text().strip()
                def api(path):
                    with urlopen(Request(base+path, headers={'Authorization':'Bearer '+key}), timeout=10) as response:
                        return json.load(response)['result']
                page = browser.new_page(viewport=dict(width=1440, height=1000))
                login(page, base, password, '/simulation')
                page.locator('#search').fill('C01');page.locator('[data-scene="C01"]').click()
                page.locator('#config-vehicle').select_option('copter')
                page.locator('#parameter-obstacle_count').fill('0')
                page.locator('#create-session').click()
                expect(page.locator('[data-operation=start]')).to_be_visible()
                page.locator('[data-operation=start]').click()
                def world():
                    records=api('/api/simulation/sessions')
                    assert not any(s['state']=='FAILED' for s in records),records
                    return next((s for s in records if s['state'] in ('READY','RUNNING') and s.get('vehicles') and all(v['state'] in ('READY','RUNNING') for v in s['vehicles'])),None)
                active=wait(world,120)
                report['native_world']=dict(id=active['id'], scene=active['scene_id'], state=active['state'])
                audit(page, base, password, 'real-control-center', local=True)
                state=api('/api/console/state')
                assert all(not v['actions'] and not v['missions'] for v in state['vehicles'])
                assert all(not v['authority']['system_send'] and not v['authority']['action_send'] and v['armed'] is False for v in state['vehicles'])
                page.goto(base+'/center')
                expect(page.locator('#connection')).to_contain_text('已连接',timeout=20000)
                expect(page.locator('#stop-simulation')).to_be_enabled()
                page.locator('#stop-simulation').click()
                wait(lambda:all(s['state'] in ('FINISHED','CANCELLED') for s in api('/api/simulation/sessions')),90)
                report['native_world']['stopped']=True
                page.locator('#shutdown').click()
                # Existing UI requires explicit human-facing confirmation.
                if page.locator('#confirm-shutdown').count():page.locator('#confirm-shutdown').click()
                process.wait(timeout=140)
                finished=json.loads(current.read_text())
                report['native_cleanup']=finished.get('os_cleanup')
                if not report['native_cleanup']:
                    audit_path=Path(native_state['run_dir'])/'os-cleanup.json'
                    report['native_cleanup']=wait(lambda:json.loads(audit_path.read_text()) if audit_path.exists() else None,10)
                assert not report['native_cleanup']['remaining_owned_processes'] and not report['native_cleanup']['credential_errors']
            assert not errors,errors
            report['status']='PASS'
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:process.wait(timeout=140)
            except subprocess.TimeoutExpired:
                # Signal only our launcher. Its supervisor owns OS cleanup.
                process.kill();process.wait(10)
        (directory/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--native', action='store_true')
    args=parser.parse_args()
    print(json.dumps(run(args.run_dir,native=args.native),ensure_ascii=False))

"""Chinese UI acceptance in Chrome; isolated fixtures, no vehicle transport."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
from threading import Thread

from tests.browser_auth import login
from tests.web_ui.helpers import Harness


def run(directory):
    from playwright.sync_api import sync_playwright, expect
    from tests.test_llm_proposals import Application
    from vehicle_autonomy.app.operator.service import OperatorService
    from vehicle_autonomy.app.web.server import ConsoleServer

    directory.mkdir(parents=True, exist_ok=False)
    errors = []
    report = dict(passed=False, source=__doc__)
    with ExitStack() as stack:
        h = Harness(directory/'mission', kinds=('rover', 'copter', 'plane'), standard=True)
        stack.callback(h.close)
        pw = stack.enter_context(sync_playwright())
        browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True,
                                    args=['--no-sandbox', '--disable-dev-shm-usage'])
        stack.callback(browser.close)
        page = browser.new_page(viewport={'width':1680, 'height':1050})
        page.on('pageerror', lambda error: errors.append(str(error)))
        try:
            page.goto(h.base+'/login')
            expect(page.get_by_role('heading', name='登录控制台')).to_be_visible()
            page.locator('#login-key').fill('invalid-access-key-for-browser-test-only')
            page.locator('#login-submit').click()
            expect(page.locator('#login-error')).to_contain_text('密钥')
            login(page, h.base, h.token)
            for name, title in [('dashboard','车辆总览'), ('tools','工具管理'),
                                ('workspaces','工作环境'), ('logs','日志与诊断'), ('settings','设置')]:
                page.goto(h.base+'/console#'+name)
                expect(page.locator('h1')).to_have_text(title)
                expect(page.locator('nav')).to_contain_text('任务编排')
                assert '/login' not in page.url
                if name in ('dashboard', 'settings'):
                    page.screenshot(path=str(directory/(name+'.png')), full_page=True)
            page.goto(h.base+'/control')
            for kind, title in [('rover','地面车'), ('copter','多旋翼'), ('plane','固定翼')]:
                page.locator('#target').select_option(kind)
                expect(page.locator('#vehicle-name')).to_have_text(kind+' / '+title)
                expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
                expect(page.locator('#vehicle-status')).to_contain_text('遥测新鲜度')
                assert page.locator('#target').input_value()==kind
                assert page.locator('[data-action="Arm"]').is_disabled()
                page.screenshot(path=str(directory/(kind+'.png')), full_page=True)
            page.locator('nav a[href="/studio"]').click()
            expect(page.locator('h1')).to_have_text('任务库')
            page.locator('#new-mission').click()
            # A user name matching an English interface label must remain original.
            page.get_by_label('任务名称', exact=True).fill('Mission Library')
            page.locator('#dialog-confirm').click()
            expect(page.locator('h1')).to_have_text('Mission Library')
            page.locator('#palette-search').fill('等待')
            expect(page.locator('#palette button')).to_have_count(1)
            page.locator('#palette button').click()
            expect(page.locator('.node-category').filter(has_text='等待')).to_have_count(1)
            page.locator('#save-draft').click()
            expect(page.locator('#save-state')).to_contain_text('已保存')
            definition = next(v['definition'] for v in h.lab.studio.library.snapshot()['drafts'].values()
                              if v['definition']['name']=='Mission Library')
            assert [n['type'] for n in definition['nodes']]==['Start', 'End', 'Wait']
            page.screenshot(path=str(directory/'editor.png'), full_page=True)
            # Every vocabulary entry must be stable across observer passes.
            assert page.evaluate('Object.values(VAFI18n.labels).every(v=>VAFI18n.text(v)===v)')
            page.evaluate('''() => {
                const root=document.createElement('section');root.id='locale-probe';
                root.innerHTML='<select><option>GUIDED</option></select><pre>RUNNING</pre>'+
                    '<textarea>Mission Library</textarea><span data-original-text>Mission Library</span>'+
                    '<button title="原始诊断：Action FAILED">Ready</button>';
                document.body.append(root);
            }''')
            expect(page.locator('#locale-probe option')).to_have_text('引导（GUIDED）')
            assert page.locator('#locale-probe select').input_value()=='GUIDED'
            expect(page.locator('#locale-probe pre')).to_have_text('RUNNING')
            expect(page.locator('#locale-probe textarea')).to_have_value('Mission Library')
            expect(page.locator('#locale-probe [data-original-text]')).to_have_text('Mission Library')
            expect(page.locator('#locale-probe button')).to_have_text('已就绪')
            assert page.locator('#locale-probe button').get_attribute('title')=='原始诊断：Action FAILED'
            page.locator('#locale-probe').evaluate('(node)=>node.remove()')
            page.goto(h.base+'/studio/legacy')
            expect(page.locator('h1')).to_have_text('任务编排')
            page.locator('#action-library').select_option('Goto@1.0.0')
            page.locator('#add-action').click()
            page.get_by_text('类型化观测参数绑定', exact=True).click()
            page.locator('#binding-field').select_option('x_m')
            page.locator('#binding-source').select_option('world')
            expect(page.locator('#binding-field option:checked')).to_have_text('东向位置（米）')
            page.locator('#binding-path').fill('vehicle.reported_pose.value.position.x')
            page.get_by_role('button', name='绑定参数', exact=True).click()
            legacy = json.loads(page.locator('#json').input_value())
            assert legacy['nodes'][0]['parameters']['x_m']['$query']['source']=='world'
            page.goto(h.base+'/')
            expect(page.locator('h1')).to_have_text('动作实验室')
            expect(page.locator('#connection')).to_have_text('API 已连接')
            page.locator('#vehicle').select_option('copter')
            expect(page.locator('#vehicle-info')).to_contain_text('copter')
            page.locator('#action').select_option('SetMode@1.0.0')
            expect(page.locator('#parameters')).to_contain_text('飞控模式')
            page.locator('#parameters select').select_option('"GUIDED"')
            assert page.locator('#parameters select').input_value()=='"GUIDED"'
            expect(page.locator('#parameters option:checked')).to_have_text('引导（GUIDED）')
            assert not h.lab.runtime.views() and not any(d.writes for d in h.drivers.values())

            # The separate receive-only operator console also shares the vocabulary.
            app = Application()
            app.state.update(mode='hardware_readonly', connected=False, system_send=False, action_send=False)
            service = OperatorService(app, directory/'operator', missions=['basic_route'])
            token = secrets.token_urlsafe(32)
            server = ConsoleServer(('127.0.0.1',0), service, token, directory/'operator.jsonl')
            thread = Thread(target=server.serve_forever, kwargs={'poll_interval':.02})
            thread.start()
            def close():
                server.shutdown(); thread.join(3); server.server_close()
            stack.callback(close)
            base = 'http://127.0.0.1:'+str(server.server_address[1])
            login(page, base, token, '/')
            page.locator('#connect').click()
            expect(page.locator('#summary')).to_contain_text('已就绪')
            expect(page.locator('#start')).to_have_text('实车只读 · 任务未授权')
            expect(page.locator('#start')).to_be_disabled()
            assert not app.starts
            page.screenshot(path=str(directory/'operator.png'), full_page=True)
            assert not errors, errors
            report.update(passed=True, javascript_errors=errors, all_pages=True, chinese_search=True,
                          original_values_preserved=True, option_wire_values_preserved=True,
                          user_names_preserved=True, zero_vehicle_writes=True)
        except BaseException as error:
            page.screenshot(path=str(directory/'failure.png'), full_page=True)
            report['error']=str(error)
            raise
        finally:
            (directory/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    print(json.dumps(run(parser.parse_args().run_dir), ensure_ascii=False))

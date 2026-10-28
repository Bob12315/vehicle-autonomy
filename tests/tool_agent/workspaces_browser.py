"""Chrome creates/saves/launches a real multi-process Workspace via the UI."""
import argparse
import json
from pathlib import Path

from .helpers import tool
from .test_service import Harness


def run(directory):
    from playwright.sync_api import sync_playwright,expect
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    h=Harness(directory,[tool(),tool('second',code='import time;print("second",flush=True);time.sleep(120)')]);errors=[]
    report=dict(passed=False,source='real Chromium/HTTP/Agent; two actual process fixtures, not native robotics integration')
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(viewport={'width':1560,'height':1080});page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(h.base+'/console#workspaces');page.locator('#token').fill(h.web_token);page.locator('#connection button[type=submit]').click()
                expect(page.locator('#link-state')).to_have_text('控制中心已连接')
                page.locator('#workspace-new').click();editor=page.locator('#workspace-editor')
                editor.locator('.form-grid input').nth(0).fill('ui-work');editor.locator('.form-grid input').nth(1).fill('UI dependency workspace')
                editor.get_by_role('button',name='添加组件',exact=True).click()
                editor.locator('[aria-label="依赖组件"]').nth(1).fill('component-1')
                editor.get_by_role('button',name='保存 Workspace',exact=True).click()
                row=page.locator('.workspace-row');expect(row).to_contain_text('UI dependency workspace')
                assert not h.local.instances
                row.get_by_role('button',name='Launch Workspace',exact=True).click()
                expect(row.locator('.workspace-heading .badge')).to_have_text('READY',timeout=15000)
                assert h.local.counter==2
                row.get_by_role('button',name='修改',exact=True).click();editor.locator('.form-grid input').nth(1).fill('Saved while running')
                editor.get_by_role('button',name='保存 Workspace',exact=True).click();expect(row).to_contain_text('Saved while running')
                assert h.local.counter==2 and all(v['process_running'] for v in h.local.instances.values())
                page.evaluate('scrollTo(0,0)');page.wait_for_timeout(300)
                page.screenshot(path=str(directory/'workspace-desktop.png'),full_page=True,mask=[page.locator('#token')],mask_color='#243d4a')
                row.get_by_role('button',name='Stop Workspace',exact=True).click();expect(row.locator('.workspace-heading .badge')).to_have_text('STOPPED',timeout=15000)
                assert all(v['cleanup_confirmed'] and not v['process_running'] for v in h.local.instances.values())
                page.locator('#workspace-new').click();editor.locator('[aria-label="Workspace 预设"]').select_option('rover-navigation');editor.get_by_role('button',name='载入预设',exact=True).click()
                expect(editor.locator('.form-grid input').nth(0)).to_have_value('rover-navigation')
                page.set_viewport_size({'width':390,'height':950});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(directory/'workspace-mobile.png'),full_page=True,mask=[page.locator('#token')],mask_color='#243d4a')
                report.update(passed=not errors,javascript_errors=errors,actual_processes=h.local.counter,dependency_order=True,save_does_not_launch=True,edit_keeps_live_instances=True,stop_cleanup=True,template_loaded=True)
                assert not errors
            finally:browser.close()
    finally:h.close()
    (directory/'summary.json').write_text(json.dumps(report,indent=2));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True)
    print(json.dumps(run(p.parse_args().run_dir)))

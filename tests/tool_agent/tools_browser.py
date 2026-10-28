"""Browser -> backend -> authenticated Agent -> actual owned test executable."""
import argparse
import json
from pathlib import Path

from .test_service import Harness
from .helpers import wait


def run(directory):
    from playwright.sync_api import sync_playwright,expect
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    h=Harness(directory);errors=[];report=dict(passed=False,source='actual Chrome/HTTP/Agent/process integration; tool is a test executable, not native robotics software')
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(viewport={'width':1560,'height':1000});page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(h.base+'/console#tools');page.locator('#token').fill(h.web_token);page.locator('#connection button[type=submit]').click()
                row=page.locator('[data-tool="desktop:fixture"]');expect(row).to_be_visible()
                row.get_by_role('button',name='Launch',exact=True).click()
                expect(row.locator('td:nth-child(4) .badge')).to_have_text('Ready',timeout=10000)
                row.get_by_role('button',name='Logs',exact=True).click();expect(page.locator('#tool-detail pre')).to_contain_text('started')
                row.get_by_role('button',name='Configure',exact=True).click();page.get_by_role('button',name='保存选择',exact=True).click()
                row.get_by_role('button',name='Stop',exact=True).click();expect(row.locator('td:nth-child(3) small').first).to_have_text('STOPPED',timeout=10000)
                row.get_by_role('button',name='Restart',exact=True).click();expect(row.locator('td:nth-child(4) .badge')).to_have_text('Ready',timeout=10000)
                page.evaluate('scrollTo(0,0)');page.wait_for_timeout(400)
                page.screenshot(path=str(directory/'tools-desktop.png'),full_page=True,mask=[page.locator('#token')],mask_color='#243d4a')
                page.set_viewport_size({'width':390,'height':900});page.locator('#tool-detail').evaluate('(e)=>e.hidden=true')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(directory/'tools-mobile.png'),full_page=True,mask=[page.locator('#token')])
                page.locator('#disconnect').click();expect(row.locator('td:nth-child(3) small').first).to_have_text('DISCONNECTED')
                report.update(passed=not errors,javascript_errors=errors,launch_stop_restart=True,profile_saved=True,disconnect_unknown=True,
                    actual_instance_count=h.local.counter,vehicle_actions=len(h.lab.runtime.views()))
                assert not errors and h.local.counter==2 and not h.lab.runtime.views()
            finally:browser.close()
    finally:h.close()
    (directory/'summary.json').write_text(json.dumps(report,indent=2));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True)
    print(json.dumps(run(p.parse_args().run_dir)))

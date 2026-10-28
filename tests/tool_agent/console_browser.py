"""Real Chromium against the real HTTP console; fixture vehicle status only."""
from contextlib import ExitStack
import argparse
import json
from pathlib import Path
import secrets
from threading import Thread
from unittest.mock import patch

from tests.mission_graph.test_service import WebDriver
from vehicle_autonomy.app.web.mission_control import MissionControl, MissionControlServer


def run(directory):
    from playwright.sync_api import sync_playwright, expect
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    errors=[];report=dict(passed=False,source='real Chromium + HTTP; fixture vehicles with unknown telemetry; no vehicle connection')
    with ExitStack() as stack:
        stack.enter_context(patch('vehicle_autonomy.app.web.mission_control.bind_simulations',return_value={}))
        drivers={}
        for kind in ('rover','copter','plane'):
            d=WebDriver();d.info=lambda kind=kind:dict(target=kind,kind=kind,connected=False,system_send=False,action_send=False)
            drivers[kind]=d
        service=MissionControl(drivers,directory/'missions');stack.callback(service.close)
        token=secrets.token_urlsafe(32)
        server=MissionControlServer(('127.0.0.1',0),service,token,directory/'http.jsonl')
        thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.02});thread.start()
        def close():server.shutdown();thread.join(3);server.server_close()
        stack.callback(close)
        playwright=stack.enter_context(sync_playwright())
        browser=playwright.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage']);stack.callback(browser.close)
        page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{server.server_address[1]}/console')
        page.locator('#token').fill(token);page.locator('#connection button[type=submit]').click()
        expect(page.locator('#link-state')).to_have_text('控制中心已连接')
        for kind in ('rover','copter','plane'):
            page.locator(f'[data-kind="{kind}"]').click();expect(page.locator('#vehicle-label')).to_contain_text(kind)
            expect(page.locator('#metric-connection')).to_have_text('Disconnected');expect(page.locator('#metric-armed')).to_have_text('未知')
        page.screenshot(path=str(directory/'dashboard-desktop.png'),full_page=True)
        for name in ('tools','workspaces','logs','settings','dashboard'):
            page.locator(f'[data-view={name}]').click();expect(page.locator(f'[data-panel={name}]')).to_be_visible()
        report['widths']=[]
        for width in (1440,1024,390):
            page.set_viewport_size({'width':width,'height':950})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
            report['widths'].append(width)
        page.screenshot(path=str(directory/'dashboard-mobile.png'),full_page=True)
        page.locator('#disconnect').click();expect(page.locator('#dashboard-data')).to_be_hidden()
        report.update(passed=not errors,javascript_errors=errors,writer_calls=sum(len(d.writes) for d in drivers.values()),three_types=True,unknown_values_preserved=True)
        assert report['writer_calls']==0 and not errors
    (directory/'summary.json').write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',required=True,type=Path)
    print(json.dumps(run(p.parse_args().run_dir)))

"""Read-only Chrome verification of an explicitly launched real simulation."""
import argparse
import json
from pathlib import Path
from urllib.request import Request,urlopen


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-url',required=True)
    p.add_argument('--token-file',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();token=a.token_file.read_text().strip()
    with urlopen(Request(a.base_url+'/api/console/state',headers={'Authorization':'Bearer '+token}),timeout=5) as response:data=json.load(response)['result']
    assert data['vehicles'] and all(v['environment']=='simulation' and v['fresh'] for v in data['vehicles'])
    from playwright.sync_api import sync_playwright,expect
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            page=browser.new_page(viewport={'width':1440,'height':1040});page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(a.base_url+'/console');page.locator('#token').fill(token);page.locator('#connection button[type=submit]').click()
            expect(page.locator('#metric-connection')).to_have_text('Connected');expect(page.locator('#environment')).to_have_text('SITL · 自有仿真')
            page.screenshot(path=str(a.output),full_page=True,mask=[page.locator('#token')])
            assert not errors
        finally:browser.close()
    a.output.with_suffix('.json').write_text(json.dumps(dict(passed=True,source='live owned SITL/Gazebo + real Chrome + HTTP',vehicles=data['vehicles'],javascript_errors=errors),indent=2))


if __name__=='__main__':main()

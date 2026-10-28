"""Real default-readonly launcher, auto Agent, shared login and native RViz.

Requires the existing native ROS/Gazebo/SITL environment. No Arm or movement.
"""
import argparse,json,subprocess,sys,time
from pathlib import Path
from urllib.request import Request,urlopen


def run(directory):
    from playwright.sync_api import sync_playwright,expect
    from tests.browser_auth import login
    from tests.visualization.desktop import goal
    from vehicle_autonomy.app.visualization.config import load
    from vehicle_autonomy.app.visualization.source import Client
    directory=directory.resolve();directory.parent.mkdir(parents=True,exist_ok=True);base='http://127.0.0.1:18890';errors=[]
    log=directory.with_suffix('.launcher.log').open('w')
    process=subprocess.Popen([sys.executable,'-m','vehicle_autonomy.app.visualization.launch','--kind','rover','--run-dir',str(directory),
        '--web-port','18890','--domain-id','184','--namespace','/launcher_rover'],stdout=log,stderr=subprocess.STDOUT)
    def api(path):
        key=(directory/'simulation/web-token.private').read_text().strip()
        with urlopen(Request(base+path,headers={'Authorization':'Bearer '+key}),timeout=2) as r:return json.load(r)['result']
    def wait(fn,timeout):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if process.poll() is not None:raise RuntimeError('owned launcher exited')
            try:
                value=fn()
                if value:return value
            except (OSError,ValueError,KeyError):pass
            time.sleep(.15)
        raise TimeoutError('native launcher acceptance')
    try:
        def connected():
            value=api('/api/console/state')
            return value if any(a['connected'] for a in value['tools']['agents']) else None
        state=wait(connected,100)
        assert not any(t.get('instance') for a in state['tools']['agents'] for t in a['tools'])
        initial={a['id'] for a in api('/api/instances')}
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(viewport={'width':1680,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
                login(page,base,(directory/'simulation/web-token.private').read_text().strip(),'/control')
                expect(page.locator('#open-rviz')).to_be_enabled(timeout=20000);page.locator('#open-rviz').click()
                def ready():
                    tools={t['manifest']['id']:t for a in api('/api/console/state')['tools']['agents'] for t in a['tools']}
                    return tools if all((tools.get(k,{}).get('instance') or {}).get('ready') for k in ('rviz2','visualization-bridge')) else None
                tools=wait(ready,80);window=goal(tools['rviz2']['instance']['pid'],capture=directory/'rviz-window.png',select=False)
                source=Client(load(directory/'source.json'),'rover').request('/api/visualization/state?target=rover')
                assert source['valid'] and source['origin']['geodetic_origin']
                vehicle=api('/api/control/state')['vehicles'][0];gates={k:vehicle[k] for k in ('deployment_send','system_send','action_send')};assert not any(gates.values())
                page.goto(base+'/console#workspaces');expect(page.locator('#login-key')).to_have_count(0)
                page.goto(base+'/control');expect(page.locator('#vehicle-name')).to_contain_text('Rover')
                assert {a['id'] for a in api('/api/instances')}==initial and not errors
                report=dict(passed=True,source=__doc__,auto_agent=True,no_automatic_tool_launch=True,no_vehicle_actions=True,
                    send_gates=gates,origin=source['origin'],namespace='/launcher_rover',domain=184,native_window=window,
                    one_login_across_pages=True,javascript_errors=errors)
            finally:browser.close()
    finally:
        if process.poll() is None:process.terminate()
        process.wait(55);log.close()
    closed=json.loads((directory/'launcher-closed.json').read_text());assert closed['closed']
    assert not (directory/'visualization.private').exists() and not (directory/'desktop.private').exists()
    report['temporary_credentials_removed']=True;report['owned_deployment_closed']=True
    (directory/'smoke-result.json').write_text(json.dumps(report,indent=2));return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True)
    result=run(p.parse_args().run_dir);print(json.dumps(dict(passed=result['passed'],send_gates=result['send_gates'],owned_deployment_closed=result['owned_deployment_closed'])))

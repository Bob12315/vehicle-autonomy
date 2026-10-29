"""Real browser controls and native ROS Tool Agent on the owned simulator.

All vehicle mutations originate from UI clicks/keys. HTTP reads and the
independent Gazebo oracle verify outcomes; neither writes vehicle commands.
Requires a trusted native registry containing a configured `ros2` profile.
"""
import json
import math
import socket
import subprocess
import sys
import time
from pathlib import Path

from vehicle_autonomy.app.web.server import load_token
from tests.simulation.web_controls import ControlCheck, TERMINAL
from tests.browser_auth import login


class ToolAcceptance:
    def __init__(self, directory, registry):
        self.directory = directory
        directory.mkdir(mode=0o700)
        self.process = None
        self.log = None
        native = json.loads(Path(registry).read_text())
        ros = next(t for t in native['tools'] if t['id'] == 'ros2')
        ros['profiles']['default']['env']['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'
        (directory/'registry.json').write_text(json.dumps(dict(schema=1, tools=[ros])))
        load_token(directory/'agent.private')
        (directory/'allowlist.json').write_text(json.dumps(dict(schema=1, agents={
            'desktop': dict(token_file=str(directory/'agent.private'))})))
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]

    def arguments(self):
        return ['--tool-agents', str(self.directory/'allowlist.json'),
                '--tool-port', str(self.port), '--tool-data-dir', str(self.directory/'persistent')]

    def start(self):
        self.log = (self.directory/'agent.log').open('w')
        self.process = subprocess.Popen([sys.executable, '-m', 'vehicle_autonomy.app.tools.agent',
            '--id', 'desktop', '--token-file', str(self.directory/'agent.private'),
            '--registry', str(self.directory/'registry.json'), '--data-dir', str(self.directory/'agent-state'),
            '--backend', f'http://127.0.0.1:{self.port}'], stdout=self.log,
            stderr=subprocess.STDOUT, start_new_session=True)

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(30)
        if self.log is not None:
            self.log.close()
        (self.directory/'agent.private').unlink(missing_ok=True)

    def exercise(self, kind, base, token, api, oracle, directory):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome',
                headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            try:
                context = browser.new_context(viewport={'width':1680, 'height':1100})
                page = context.new_page()
                errors = []
                initial_actions = {a['id'] for a in api('/api/instances')}
                page.on('pageerror', lambda error: errors.append(str(error)))
                login(page,base,token,'/console#tools')
                row = page.locator('[data-tool="desktop:ros2"]')
                row.wait_for(timeout=30000)
                # Initial automatic selection must also bind the Tool Context.
                expect(page.locator('#context-vehicle')).to_have_value(kind)
                expect(page.locator('#context-type')).to_have_value(kind)
                expect(page.locator('#context-namespace')).to_have_value('/'+kind)
                page.locator('[data-view=settings]').click()
                page.locator('#context-domain').fill(str({'rover':114, 'copter':115, 'plane':116}[kind]))
                page.locator('#context-form button[type=submit]').click()
                expect(page.locator('#notice')).to_contain_text('上下文已保存')
                page.locator('[data-view=tools]').click()
                row.get_by_role('button', name='启动', exact=True).click()
                expect(row.locator('td:nth-child(4) .badge')).to_have_text('已就绪', timeout=60000)
                first = api('/api/console/state')['tools']['agents'][0]['tools'][0]['instance']
                assert first['context']['vehicle_id'] == kind and first['owned'] is True
                row.get_by_role('button', name='连接信息', exact=True).click()
                expect(page.locator('#tool-detail')).to_contain_text('ros2')
                row.get_by_role('button', name='日志', exact=True).click()
                expect(page.locator('#tool-detail')).to_contain_text('vaf_tool_observer', timeout=15000)
                page.screenshot(path=str(directory/'native-tools.png'), full_page=True, mask=[])
                row.get_by_role('button', name='重启', exact=True).click()
                expect(row.locator('td:nth-child(4) .badge')).to_have_text('已就绪', timeout=60000)
                # A Ready badge can still be the previous instance while restart
                # is queued. Verify a new actual PID and matching context too.
                end = time.monotonic()+60
                while True:
                    second = api('/api/console/state')['tools']['agents'][0]['tools'][0]['instance']
                    if second['pid'] != first['pid'] and second['ready']: break
                    assert time.monotonic() < end, 'native ROS tool restart did not replace instance'
                    page.wait_for_timeout(150)
                assert not Path(f'/proc/{first["pid"]}').exists()
                row.get_by_role('button', name='停止', exact=True).click()
                expect(row.locator('td:nth-child(3) small').first).to_have_text('已停止', timeout=30000)
                assert not Path(f'/proc/{second["pid"]}').exists()
                authority = api('/api/console/state')['vehicles'][0]['authority']
                assert not authority['system_send'] and not authority['action_send']
                assert {a['id'] for a in api('/api/instances')} == initial_actions
                page.goto(base+'/control')
                assert '/login' not in page.url
                page.locator('#acquire-control').click()
                expect(page.locator('#top-authority')).to_have_text('开启指令发送')
                check = BrowserControlCheck(kind, api, oracle, directory, page)
                check.result['native_tool'] = dict(name='ROS2 graph observer',
                    actual_native=True, launch=True, restart=True, stop=True,
                    context=first['context'], first_pid=first['pid'], second_pid=second['pid'])
                # Recheck the default Action SEND gate through the actual UI.
                check.perform('Arm', allow_send=False, expected='REJECTED')
                result = check.run()
                page.locator('#release-control').click()
                expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
                page.screenshot(path=str(directory/'browser-controls.png'), full_page=True,
                    mask=[])
                assert not errors, errors
                result['javascript_errors'] = errors
                check.save()
                return result
            except Exception:
                page.screenshot(path=str(directory/'failure-ui.png'),full_page=True)
                (directory/'failure-ui.txt').write_text(page.locator('#notice').inner_text()+'\n'+page.locator('#diagnostics').inner_text())
                raise
            finally:
                browser.close()


class BrowserControlCheck(ControlCheck):
    def __init__(self, kind, api, oracle, directory, page):
        super().__init__(kind, api, oracle, directory)
        self.page = page
        self.result['control_origin'] = 'real Chromium UI clicks and held keys; HTTP observations only'

    def perform(self, name, parameters=None, seconds=45, *, allow_send=True, expected='SUCCEEDED'):
        from playwright.sync_api import expect
        page=self.page;parameters=parameters or {}
        before={a['id'] for a in self.call('/api/instances')}
        if name=='SetMode':
            page.locator('#mode').select_option(parameters['mode']);button=page.locator('#set-mode')
        elif name=='Takeoff':
            if self.kind=='plane':
                section=page.locator('[data-for=plane] details');section.locator('summary').click() if not section.get_attribute('open') else None
            page.locator('#plane-height' if self.kind=='plane' else '#takeoff-height').fill(str(parameters['height_m']))
            button=page.locator('#plane-takeoff' if self.kind=='plane' else '#takeoff')
        elif name=='Goto':
            section=page.locator('#position-advanced');section.locator('summary').click() if section.get_attribute('open') is None else None
            for key,field in [('x_m','#goto-x'),('y_m','#goto-y'),('z_m','#goto-z')]:
                if page.locator(field).is_disabled():assert parameters[key]==0
                else:page.locator(field).fill(str(parameters[key]))
            button=page.locator('#goto')
        elif name=='SetGuidedTarget':
            for key,field in [('latitude_deg','#latitude'),('longitude_deg','#longitude'),('altitude_amsl_m','#altitude-amsl')]:page.locator(field).fill(str(parameters[key]))
            button=page.locator('#guided-target')
        elif name=='ReturnHome':button=page.locator('#return-control')
        elif name=='Stop':button=page.locator('#hold-control')
        else:
            button=page.locator('[data-action="'+name+'"]')
        if not allow_send:
            page.locator('#release-control').click();expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
            expect(button).to_be_disabled();assert {a['id'] for a in self.call('/api/instances')}==before
            self.result['ui_without_send_on']='blocked before submission'
            page.locator('#acquire-control').click();expect(page.locator('#top-authority')).to_have_text('开启指令发送')
            return None
        button.click();expect(page.locator('#command-confirm')).not_to_be_visible()
        a=self.wait(lambda:next((a for a in self.call('/api/instances') if a['id'] not in before),None),12)
        final=self.finish(a,seconds,expected=expected)
        if name=='Takeoff' and self.kind=='plane':assert page.locator('[data-action="Disarm"]').is_disabled()
        return final

    def managed(self, name, parameters, threshold):
        self._held(parameters, threshold)
        if self.kind == 'rover' and threshold[0] == 'distance':
            self.perform('SetMode', {'mode':'GUIDED'})
            self._held(dict(speed_mps=-.3, yaw_rate_rad_s=0), ('distance', .4))

    def _held(self, parameters, threshold):
        from playwright.sync_api import expect
        page = self.page
        turn = threshold[0] == 'yaw'
        key = ('a' if self.kind == 'rover' else 'r') if turn else ('s' if parameters.get('speed_mps', .3) < 0 else 'w')
        start = self.truth(); before = {a['id'] for a in self.call('/api/instances')}
        if self.kind=='copter':
            section=page.locator('#copter-advanced')
            if section.get_attribute('open') is None:section.locator('summary').click()
            page.locator('#copter-motion-toggle').click()
        expect(page.locator('[data-key="'+key+'"]').last if self.kind=='copter' else page.locator('[data-key="'+key+'"]').first).to_be_enabled(timeout=15000)
        page.locator('#control-level').click();page.keyboard.down(key)
        try:
            a = self.wait(lambda: next((a for a in self.call('/api/instances') if a['id'] not in before), None), 8)
            def moved():
                t = self.truth()
                measured = abs(math.atan2(math.sin(t.yaw_rad-start.yaw_rad), math.cos(t.yaw_rad-start.yaw_rad))) if turn else math.hypot(t.x_m-start.x_m, t.y_m-start.y_m)
                return (t, measured) if measured >= threshold[1] else None
            t, measured = self.wait(moved, 15)
        finally:
            page.keyboard.up(key)
        if self.kind=='copter':
            def held_neutral():
                self.truth();current=self.state(a['id']);speed=self.oracle.recent_speed_mps();rate=self.oracle.recent_yaw_rate_rad_s()
                assert current['state']=='RUNNING',current
                return speed is not None and speed<=.15 and rate is not None and abs(rate)<=.15
            self.wait(held_neutral,15)
            assert {r['id'] for r in self.call('/api/instances') if r['id'] not in before}=={a['id']}
            page.locator('#copter-motion-toggle').click()
        final = self.finish(a, 25, expected='CANCELLED')
        speed = self.oracle.recent_speed_mps(); yaw_rate = self.oracle.recent_yaw_rate_rad_s()
        bound = .1 if self.kind == 'rover' else .15
        assert speed is not None and speed <= bound and yaw_rate is not None and abs(yaw_rate) <= bound
        if key == 's':
            assert (t.x_m-start.x_m)*math.cos(start.yaw_rad)+(t.y_m-start.y_m)*math.sin(start.yaw_rad) < -.3
        self.result['managed'].append(dict(key=key, parameters=parameters, measured=measured,
            stop_speed_mps=speed, stop_yaw_rate_rad_s=yaw_rate, state=final['state']))
        self.save()

    def fault_stream(self, mode):
        """Real physical motion followed by browser/HTTP failure, no port writes."""
        from playwright.sync_api import expect
        page=self.page;self.perform('SetMode',{'mode':'GUIDED'})
        panel=page.locator('#copter-advanced')
        if panel.get_attribute('open') is None:panel.locator('summary').click()
        before={a['id'] for a in self.call('/api/instances')};start=self.truth()
        page.locator('#copter-motion-toggle').click()
        expect(page.locator('#copter-stream [data-key="w"]')).to_be_enabled()
        page.locator('#control-level').click();page.keyboard.down('w')
        a=self.wait(lambda:next((a for a in self.call('/api/instances') if a['id'] not in before),None),8)
        self.wait(lambda:math.hypot(self.truth().x_m-start.x_m,self.truth().y_m-start.y_m)>=.25,12)
        blocker=lambda route:route.abort()
        alt=None
        try:
            if mode=='watchdog':
                page.route('**/api/manual/update',blocker);page.route('**/api/manual/stop',blocker)
            elif mode=='offline':page.context.set_offline(True)
            else:
                # Playwright gives each tab emulated permanent focus. Disable
                # that for this native Chrome tab switch; do not synthesize a
                # DOM blur event or bypass the page stop handler.
                focus=page.context.new_cdp_session(page)
                focus.send('Emulation.setFocusEmulationEnabled',{'enabled':False})
                page.bring_to_front()
                assert page.evaluate('document.hasFocus()')
                alt=page.context.new_page();alt.bring_to_front()
                page.wait_for_function('!document.hasFocus()',timeout=3000)
            end=time.monotonic()+20
            while time.monotonic()<end:
                page.wait_for_timeout(100)
                final=self.state(a['id'])
                if final['state'] in TERMINAL:break
            else:raise TimeoutError('physical stream did not exit after '+mode)
            self.finish(a,20,expected='CANCELLED' if mode=='blur' else 'TIMED_OUT')
            speed=self.oracle.recent_speed_mps();assert speed is not None and speed<=.15
            self.result.setdefault('browser_faults',[]).append(dict(mode=mode,state=final['state'],stop_speed_mps=speed))
        finally:
            if mode=='watchdog':page.unroute('**/api/manual/update',blocker);page.unroute('**/api/manual/stop',blocker)
            if mode=='offline':page.context.set_offline(False)
            if alt:
                alt.close();page.bring_to_front()
                focus.send('Emulation.setFocusEmulationEnabled',{'enabled':True});focus.detach()
            page.keyboard.up('w')
        if mode=='offline':
            expect(page.locator('#top-authority')).to_have_text('关闭指令发送',timeout=16000)
            page.locator('#acquire-control').click(timeout=20000)
            expect(page.locator('#top-authority')).to_have_text('开启指令发送')
        self.save()

    def hover_or_ground(self):
        if self.kind!='copter':return super().hover_or_ground()
        self.perform('Takeoff',{'height_m':1.5},45);self.information('airborne',armed=True)
        assert abs(self.truth().z_m-self.initial.z_m-1.5)<=.35
        for turn in (False,True):
            self.perform('SetMode',{'mode':'GUIDED'})
            p=dict(vx_mps=0 if turn else .3,vy_mps=0,vz_mps=0,yaw_rate_rad_s=.25 if turn else 0,frame='base_link')
            self.managed('SetVelocity',p,('yaw',.4) if turn else ('distance',.5))
            self.information('turn stopped' if turn else 'forward stopped',armed=True)
        for failure in ('watchdog','blur','offline'):self.fault_stream(failure)
        self.perform('SetMode',{'mode':'GUIDED'});self.perform('Goto',dict(x_m=0.,y_m=0.,z_m=1.5),55)
        self.perform('Land',seconds=45);self.information('explicit Land',armed=False)
        self.perform('SetMode',{'mode':'GUIDED'});self.perform('Arm');self.perform('Takeoff',{'height_m':1.5},45)
        self.perform('Goto',dict(x_m=2.,y_m=0.,z_m=1.5),55);self.information('goto',armed=True)
        self.perform('ReturnHome',seconds=65);self.information('home stopped',armed=False)
        t=self.truth();error=math.hypot(t.x_m-self.initial.x_m,t.y_m-self.initial.y_m)
        assert error<=.75 and self.oracle.recent_speed_mps()<=.15
        self.result['home_error_m']=error

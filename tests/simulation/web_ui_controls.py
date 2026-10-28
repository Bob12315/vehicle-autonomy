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
                page = browser.new_page(viewport={'width':1680, 'height':1100})
                errors = []
                initial_actions = {a['id'] for a in api('/api/instances')}
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base+'/console#tools')
                page.locator('#token').fill(token)
                page.locator('#connection button[type=submit]').click()
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
                row.get_by_role('button', name='Launch', exact=True).click()
                expect(row.locator('td:nth-child(4) .badge')).to_have_text('Ready', timeout=60000)
                first = api('/api/console/state')['tools']['agents'][0]['tools'][0]['instance']
                assert first['context']['vehicle_id'] == kind and first['owned'] is True
                row.get_by_role('button', name='Connection', exact=True).click()
                expect(page.locator('#tool-detail')).to_contain_text('ros2')
                row.get_by_role('button', name='Logs', exact=True).click()
                expect(page.locator('#tool-detail')).to_contain_text('vaf_tool_observer', timeout=15000)
                page.screenshot(path=str(directory/'native-tools.png'), full_page=True, mask=[page.locator('#token')])
                row.get_by_role('button', name='Restart', exact=True).click()
                expect(row.locator('td:nth-child(4) .badge')).to_have_text('Ready', timeout=60000)
                # A Ready badge can still be the previous instance while restart
                # is queued. Verify a new actual PID and matching context too.
                end = time.monotonic()+60
                while True:
                    second = api('/api/console/state')['tools']['agents'][0]['tools'][0]['instance']
                    if second['pid'] != first['pid'] and second['ready']: break
                    assert time.monotonic() < end, 'native ROS tool restart did not replace instance'
                    page.wait_for_timeout(150)
                assert not Path(f'/proc/{first["pid"]}').exists()
                row.get_by_role('button', name='Stop', exact=True).click()
                expect(row.locator('td:nth-child(3) small').first).to_have_text('STOPPED', timeout=30000)
                assert not Path(f'/proc/{second["pid"]}').exists()
                authority = api('/api/console/state')['vehicles'][0]['authority']
                assert not authority['system_send'] and not authority['action_send']
                assert {a['id'] for a in api('/api/instances')} == initial_actions
                page.goto(base+'/control')
                page.locator('#token').fill(token); page.locator('#connect').click()
                page.locator('#action option').first.wait_for(state='attached')
                check = BrowserControlCheck(kind, api, oracle, directory, page)
                check.result['native_tool'] = dict(name='ROS2 graph observer',
                    actual_native=True, launch=True, restart=True, stop=True,
                    context=first['context'], first_pid=first['pid'], second_pid=second['pid'])
                # Recheck the default Action SEND gate through the actual UI.
                check.perform('Arm', allow_send=False, expected='REJECTED')
                result = check.run()
                page.screenshot(path=str(directory/'browser-controls.png'), full_page=True,
                    mask=[page.locator('#token')])
                assert not errors, errors
                result['javascript_errors'] = errors
                check.save()
                return result
            finally:
                browser.close()


class BrowserControlCheck(ControlCheck):
    def __init__(self, kind, api, oracle, directory, page):
        super().__init__(kind, api, oracle, directory)
        self.page = page
        self.result['control_origin'] = 'real Chromium UI clicks and held keys; HTTP observations only'

    def perform(self, name, parameters=None, seconds=45, *, allow_send=True, expected='SUCCEEDED'):
        page = self.page
        before = {a['id'] for a in self.call('/api/instances')}
        page.locator('#action').select_option(name+'@1.0.0')
        for key, value in (parameters or {}).items():
            field = page.locator(f'#parameters [name="{key}"]')
            if field.is_disabled():
                # Rover deliberately fixes Goto Z at zero in the UI.
                assert json.loads(field.input_value()) == value, (key, value)
                continue
            if field.evaluate('(e)=>e.tagName') == 'SELECT': field.select_option(json.dumps(value))
            else: field.fill(str(value)); field.press('Tab')
        page.locator('#continuation').fill(self.last or '')
        page.locator('#send').set_checked(allow_send)
        page.locator('#execute').click()
        a = self.wait(lambda: next((a for a in self.call('/api/instances') if a['id'] not in before), None), 10)
        if expected == 'REJECTED':
            identifier = a['id']
            final = self.wait(lambda: (v if (v := self.state(identifier))['state'] in TERMINAL else None), 10)
            assert final['state'] == expected and not final['command_results'], final
            self.result['actions'].append(final); self.save()
            print(f'{self.kind}: UI {name} REJECTED without SEND', flush=True)
            return final
        return self.finish(a, seconds, expected=expected)

    def managed(self, name, parameters, threshold):
        self._held(parameters, threshold)
        if self.kind == 'rover' and threshold[0] == 'distance':
            self.perform('SetMode', {'mode':'GUIDED'})
            self._held(dict(speed_mps=-.3, yaw_rate_rad_s=0), ('distance', .4))

    def _held(self, parameters, threshold):
        page = self.page
        turn = threshold[0] == 'yaw'
        key = ('a' if self.kind == 'rover' else 'r') if turn else ('s' if parameters.get('speed_mps', .3) < 0 else 'w')
        start = self.truth(); before = {a['id'] for a in self.call('/api/instances')}
        page.locator('#manual-send').check()
        page.locator('#manual-send').focus(); page.keyboard.down(key)
        try:
            a = self.wait(lambda: next((a for a in self.call('/api/instances') if a['id'] not in before), None), 8)
            def moved():
                t = self.truth()
                measured = abs(math.atan2(math.sin(t.yaw_rad-start.yaw_rad), math.cos(t.yaw_rad-start.yaw_rad))) if turn else math.hypot(t.x_m-start.x_m, t.y_m-start.y_m)
                return (t, measured) if measured >= threshold[1] else None
            t, measured = self.wait(moved, 15)
        finally:
            page.keyboard.up(key)
        final = self.finish(a, 25, expected='CANCELLED')
        speed = self.oracle.recent_speed_mps(); yaw_rate = self.oracle.recent_yaw_rate_rad_s()
        bound = .1 if self.kind == 'rover' else .15
        assert speed is not None and speed <= bound and yaw_rate is not None and abs(yaw_rate) <= bound
        if key == 's':
            assert (t.x_m-start.x_m)*math.cos(start.yaw_rad)+(t.y_m-start.y_m)*math.sin(start.yaw_rad) < -.3
        self.result['managed'].append(dict(key=key, parameters=parameters, measured=measured,
            stop_speed_mps=speed, stop_yaw_rate_rad_s=yaw_rate, state=final['state']))
        self.save()

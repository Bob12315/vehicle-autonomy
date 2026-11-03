"""Owned native HTTP/Gazebo acceptance; never opens a vehicle command port."""
import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
from threading import Event, Thread
import time
import traceback
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from vehicle_autonomy.app.web.mission_control import MissionControl, MissionControlServer
from vehicle_autonomy.app.web.server import load_token
from tests.simulation.oracle import GazeboTruthOracle

TERMINAL = {'SUCCEEDED', 'FAILED', 'UNKNOWN', 'TIMED_OUT', 'CANCELLED', 'REJECTED'}


class Native:
    def __init__(self, directory):
        self.path = Path(directory).resolve()
        self.path.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.token = load_token(self.path/'web-token.private')
        self.app = MissionControl({}, self.path/'application', simulation_allow_send=True)
        self.server = MissionControlServer(('127.0.0.1', 0), self.app, self.token, self.path/'http.jsonl')
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:'+str(self.server.server_address[1])
        self.requests = (self.path/'requests.jsonl').open('w')
        self.raw = (self.path/'truth-writer.jsonl').open('w')
        self.oracles = {}; self.stop = Event(); self.samples = []
        self.report = dict(status='FAIL', checks={}, stopping=[], missions=[])
        self.sampler = Thread(target=self.sample, daemon=True); self.sampler.start()

    def api(self, route, payload=None, *, reject=False):
        headers = {'Authorization': 'Bearer '+self.token}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers.update({'Content-Type': 'application/json', 'X-VAF-CSRF': self.token, 'X-VAF-Request-ID': uuid4().hex})
        try:
            with urlopen(Request(self.base+route, data, headers), timeout=20) as response:
                value = json.load(response); code = response.status
        except HTTPError as exc:
            code, value = exc.code, json.load(exc)
        self.requests.write(json.dumps(dict(at_ns=time.monotonic_ns(), route=route, payload=payload, code=code, response=value))+'\n'); self.requests.flush()
        if reject:
            assert code == 409 and not value['ok'], (route, code, value)
            return value
        assert code == 200 and value['ok'], (route, code, value)
        return value['result']

    def sample(self):
        while not self.stop.wait(.1):
            for target, oracle in tuple(self.oracles.items()):
                try:
                    truth = oracle.latest()
                    if truth is None: continue
                    driver = self.app.drivers[target]
                    info = driver.info()
                    sample = dict(at_ns=time.monotonic_ns(), target=target, truth=asdict(truth),
                        speed_mps=oracle.recent_speed_mps(), yaw_rate=oracle.recent_yaw_rate_rad_s(),
                        writer=info.get('writer'), session_id=info.get('session_id'))
                    self.samples.append(sample)
                    self.raw.write(json.dumps(sample)+'\n'); self.raw.flush()
                except Exception: pass

    def wait(self, predicate, timeout=30):
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            value = predicate()
            if value: return value
            time.sleep(.1)
        raise TimeoutError('native acceptance wait')

    def create(self, kinds):
        r = self.api('/api/simulation/create', dict(scene_id='R01', vehicles=[dict(kind=k, spawn={'id': p})
            for k, p in zip(kinds, ('center', 'north', 'south', 'east'))], parameters={'obstacle_count': 0}))
        self.api('/api/simulation/start', {'id': r['id']})
        self.app.simulation_manager.wait_ready(r['id'], 150)
        owner = self.app.simulation_manager.owners[r['id']]
        os.environ.update(GZ_IP='127.0.0.1', GZ_PARTITION=owner.partition)
        for child in owner.vehicles.values(): self.oracles[child.target] = GazeboTruthOracle(owner.world, child.model.name)
        time.sleep(45)
        self.report['vehicles'] = [c.view() for c in owner.vehicles.values()]
        return r['id'], owner, list(owner.vehicles.values())

    def action(self, target, name, parameters=None, timeout=50):
        a = self.api('/api/manual/action', dict(target=target, name=name, parameters=parameters or {}, allow_send=True))
        v = self.wait(lambda: (lambda v: v if v['state'] in TERMINAL else None)(self.app.runtime.view(a['id'])), timeout)
        assert v['state'] == 'SUCCEEDED' and v['safety']['release_safe'], (name, v['state'], v['error'])
        return v

    def drive(self, target, *, neutral=False, deadman=False, stress=False):
        self.action(target, 'SetMode', {'mode': 'GUIDED'})
        oracle = self.oracles[target]
        p = dict(speed_mps=-.3 if deadman else .3, yaw_rate_rad_s=0.)
        response = self.api('/api/manual/start', dict(name='Drive', target=target, parameters=p, allow_send=True, timeout_s=60))
        session = response['session']['id']; identifier = response['action']['id']
        v = self.wait(lambda: (lambda v: v if v['state'] == 'RUNNING' else None)(self.app.runtime.view(identifier)), 5)
        def stream(parameters, seconds):
            end = time.monotonic()+seconds
            while time.monotonic() < end:
                time.sleep(.1)
                current = self.app.runtime.view(identifier)
                if current['state'] != 'RUNNING': return current
                self.api('/api/manual/update', dict(session_id=session, sequence=current['input_sequence']+1,
                    deadline_ns=current['input_ticket'], parameters=parameters))
            return self.app.runtime.view(identifier)
        stream(p,4)
        for _ in range(2):
            if oracle.recent_speed_mps()>.15:break
            stream(p,2)
        assert oracle.recent_speed_mps() > .15, 'actual forward motion required'
        if neutral and stress:
            for speed,rate,seconds in ((.3,.25,6.),(.3,-.25,6.),(-.3,0.,6.),(-.3,.25,2.),(.3,0.,6.)):
                start=oracle.latest()
                v=stream(dict(speed_mps=speed,yaw_rate_rad_s=rate),seconds)
                end=oracle.latest()
                velocity=oracle.recent_velocity_enu()
                final_forward=velocity[0]*math.cos(end.yaw_rad)+velocity[1]*math.sin(end.yaw_rad)
                final_rate=oracle.recent_yaw_rate_rad_s()
                delta=math.atan2(math.sin(end.yaw_rad-start.yaw_rad),math.cos(end.yaw_rad-start.yaw_rad))
                forward=(end.x_m-start.x_m)*math.cos(start.yaw_rad)+(end.y_m-start.y_m)*math.sin(start.yaw_rad)
                self.report.setdefault('direction_changes',[]).append(dict(action_id=identifier,speed_target=speed,yaw_target=rate,seconds=seconds,yaw_change=delta,forward_displacement=forward,final_yaw_rate=final_rate,final_body_speed=final_forward))
                assert v['state']=='RUNNING',(v['state'],v['error'])
                if speed>0 and rate:assert final_rate*rate>0.005,(delta,final_rate,rate)
                if speed<0 and not rate:assert final_forward<-.05,(forward,final_forward)
                if speed>0 and not rate:assert final_forward>.05,(forward,final_forward)
        if neutral:
            stream(p,4)
            assert oracle.recent_speed_mps()>.15
        before = oracle.latest(); at = time.monotonic_ns()
        speed_before = oracle.recent_speed_mps()
        if neutral:
            v = stream(dict(speed_mps=0., yaw_rate_rad_s=0.), 8.5)
            zero_samples = [s for s in self.samples if s['target']==target and s['at_ns']>=at]
            stopped = next((s for s in zero_samples if s['speed_mps'] is not None and s['speed_mps']<=.1 and abs(s['yaw_rate'] or 0)<=.15), None)
            entry = dict(kind='neutral', action_id=identifier, state=v['state'], error=v['error'], speed_before=speed_before,
                stop_time_s=None if stopped is None else (stopped['at_ns']-at)/1e9,
                stop_distance_m=None if stopped is None else math.hypot(stopped['truth']['x_m']-before.x_m,stopped['truth']['y_m']-before.y_m),
                mode=self.app.drivers[target].snapshot().vehicle.operation.native_mode)
            self.report['stopping'].append(entry)
            if v['state']!='RUNNING':
                final=self.wait(lambda:(lambda v:v if v['state'] in TERMINAL else None)(self.app.runtime.view(identifier)),20)
                assert stress and final['state']=='FAILED' and final['safety']['release_safe'],(final['state'],final['error'])
                assert oracle.recent_speed_mps()<=.1 and self.app.drivers[target].snapshot().vehicle.operation.native_mode=='ARDUPILOT_CUSTOM_4'
                points=[s for s in self.samples if s['target']==target and s['at_ns']>=at and s['speed_mps'] is not None and s['speed_mps']<=.1]
                assert points and (points[0]['at_ns']-at)/1e9<=10
                entry.update(state=final['state'],release_safe=True,mode='ARDUPILOT_CUSTOM_4',stop_time_s=(points[0]['at_ns']-at)/1e9,
                    stop_distance_m=math.hypot(points[0]['truth']['x_m']-before.x_m,points[0]['truth']['y_m']-before.y_m),outcome='expected safety HOLD after unconfirmed neutral stop')
                self.report['checks']['stress neutral failure enters original HOLD / physical stop confirmed']='PASS'
                return
            assert v['state']=='RUNNING' and entry['mode']=='ARDUPILOT_CUSTOM_15', entry
            assert stopped and entry['stop_time_s']<=8,entry
            assert v['feedback'][-1]['value']['physical_stop_observed'],v['feedback'][-1]
            assert stream(p, 1)['state']=='RUNNING', 'resume in same action'
            assert len([a for a in self.app.runtime.views() if a['id']==identifier])==1
            before=oracle.latest();at=time.monotonic_ns();speed_before=oracle.recent_speed_mps()
        if not deadman: self.api('/api/manual/stop', dict(session_id=session))
        final = self.wait(lambda: (lambda v:v if v['state'] in TERMINAL else None)(self.app.runtime.view(identifier)), 20)
        assert final['state']==('TIMED_OUT' if deadman else 'CANCELLED') and final['safety']['release_safe'], (final['state'],final['error'])
        assert self.app.drivers[target].snapshot().vehicle.operation.native_mode=='ARDUPILOT_CUSTOM_4'
        assert oracle.recent_speed_mps()<=.1
        after = oracle.latest()
        points = [s for s in self.samples if s['target']==target and s['at_ns']>=at and s['speed_mps'] is not None and s['speed_mps']<=.1]
        first = points[0] if points else None
        self.report['stopping'].append(dict(kind='deadman HOLD' if deadman else 'active HOLD' if neutral else 'baseline release HOLD',
            action_id=identifier, state=final['state'], release_safe=final['safety']['release_safe'],speed_before=speed_before,
            stop_time_s=None if first is None else (first['at_ns']-at)/1e9,
            stop_distance_m=None if first is None else math.hypot(first['truth']['x_m']-before.x_m,first['truth']['y_m']-before.y_m),
            final_speed_mps=oracle.recent_speed_mps(), exit_time_s=(time.monotonic_ns()-at)/1e9))

    def close(self):
        closing_at=time.monotonic_ns()
        try:
            self.app.close()
            if hasattr(self,'shutdown_action'):
                target,identifier=self.shutdown_action
                final=self.app.runtime.view(identifier)
                samples=[s for s in self.samples if s['target']==target and s['at_ns']>=closing_at]
                last=samples[-1] if samples else None
                self.report['shutdown']=dict(action_id=identifier,state=final['state'],safety=final['safety'],last_truth=last)
                assert final['state']=='CANCELLED' and final['safety']['release_safe'] and last and last['speed_mps']<=.1
                self.report['checks']['program exit while moving / observed stop before entity cleanup']='PASS'
        except Exception as exc:
            self.report['status']='FAIL';self.report['cleanup_error']=type(exc).__name__+': '+str(exc)
            traceback.print_exc()
        finally:
            self.server.shutdown(); self.server.server_close(); self.thread.join(3)
            self.stop.set(); self.sampler.join(3); self.raw.close(); self.requests.close()
            self.report['cleanup']={k:dict(state=r['state'],cleanup=r.get('cleanup')) for k,r in self.app.simulation_manager.records.items()}
            (self.path/'result.json').write_text(json.dumps(self.report,ensure_ascii=False,indent=2)+'\n')

    def prepare_shutdown_motion(self,target):
        self.action(target,'SetMode',{'mode':'GUIDED'});self.action(target,'Arm')
        p=dict(speed_mps=.3,yaw_rate_rad_s=0.)
        response=self.api('/api/manual/start',dict(name='Drive',target=target,parameters=p,allow_send=True,timeout_s=60))
        identifier=response['action']['id'];session=response['session']['id']
        self.wait(lambda:self.app.runtime.view(identifier)['state']=='RUNNING',5)
        end=time.monotonic()+6
        while time.monotonic()<end:
            time.sleep(.1);v=self.app.runtime.view(identifier)
            self.api('/api/manual/update',dict(session_id=session,sequence=v['input_sequence']+1,deadline_ns=v['input_ticket'],parameters=p))
        assert self.oracles[target].recent_speed_mps()>.15
        self.shutdown_action=target,identifier

    def publish(self, definition):
        self.api('/api/studio-b/draft/save',dict(definition=definition,expected_revision=0))
        return self.api('/api/studio-b/draft/publish',dict(mission_id=definition['mission_id'],revision=1))

    def binding(self,target):
        return next(v['binding'] for v in self.api('/api/studio-b/catalog')['vehicles'] if v['target']==target)

    def run_request(self,publication,target,*,send=True):
        return dict(publication=publication['key'],definition_hash=publication['definition_hash'],binding=self.binding(target),allow_send=send)

    def finish_mission(self,run,timeout=180):
        v=self.wait(lambda:(lambda v:v if v['state'] in TERMINAL else None)(self.app.missions.view(run['id'])),timeout)
        self.report['missions'].append(v)
        assert v['state']=='SUCCEEDED' and v['release_safe'],(v['mission_id'],v['state'],v['error'])
        return v

    def operation(self,identifier):
        return self.wait(lambda:(lambda r:r if r.get('operation',{}).get('state') in ('SUCCEEDED','FAILED') else None)(self.app.simulation_manager.sample(identifier)),150)

    def browser_rover(self,target):
        from playwright.sync_api import sync_playwright,expect
        from tests.browser_auth import login
        self.action(target,'SetMode',{'mode':'GUIDED'});self.action(target,'Arm')
        errors=[]
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                context=browser.new_context(viewport={'width':1720,'height':1100});page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                login(page,self.base,self.token,'/control#'+target)
                page.locator('#acquire-control').click();expect(page.locator('#top-authority')).to_have_text('开启指令发送')
                page.locator('#rover-motion-toggle').click();expect(page.locator('#rover-motion-state')).to_contain_text('零速度',timeout=5000)
                page.keyboard.down('w');page.wait_for_timeout(3000)
                page.keyboard.down('a');page.wait_for_timeout(900);page.keyboard.up('a');page.keyboard.down('d');page.wait_for_timeout(700)
                page.keyboard.up('w');page.keyboard.up('d');page.wait_for_timeout(3000)
                expect(page.locator('#rover-motion-state')).to_contain_text('已观测停稳')
                assert self.oracles[target].recent_speed_mps()<=.1
                page.screenshot(path=str(self.path/'rover-zero-hold.png'),full_page=True)
                page.keyboard.down('s');page.wait_for_timeout(2200);page.keyboard.up('s')
                page.locator('#rover-motion-toggle').click()
                expect(page.locator('#rover-motion-state')).to_contain_text('控制会话已结束',timeout=12000)
                assert self.app.drivers[target].snapshot().vehicle.operation.native_mode=='ARDUPILOT_CUSTOM_4'
                page.screenshot(path=str(self.path/'rover-HOLD-ended.png'),full_page=True)
                # Re-enter explicitly, then prove focus loss exits physically.
                page.locator('#mode').select_option('GUIDED');page.locator('#set-mode').click()
                page.wait_for_timeout(2200);page.locator('#rover-motion-toggle').click();page.keyboard.down('w');page.wait_for_timeout(2200)
                page.evaluate("window.dispatchEvent(new Event('blur'))")
                expect(page.locator('#rover-motion-state')).to_contain_text('控制会话已结束',timeout=12000)
                assert self.oracles[target].recent_speed_mps()<=.1
                page.keyboard.up('w')
                # Closing SEND during active motion revokes this browser scope.
                page.locator('#mode').select_option('GUIDED');page.locator('#set-mode').click();page.wait_for_timeout(2200)
                page.locator('#rover-motion-toggle').click();page.keyboard.down('w');page.wait_for_timeout(2500)
                page.locator('#release-control').click();page.keyboard.up('w')
                self.wait(lambda:target not in self.app.operator_controls.records,15)
                assert self.oracles[target].recent_speed_mps()<=.1
                expect(page.locator('#top-authority')).to_have_text('关闭指令发送')
                # HTTP/WS loss cannot keep the managed stream alive or resume it.
                self.action(target,'SetMode',{'mode':'GUIDED'})
                page.wait_for_timeout(1800);page.locator('#acquire-control').click();page.wait_for_timeout(800)
                page.locator('#rover-motion-toggle').click();page.keyboard.down('w');page.wait_for_timeout(2500)
                active=next(a for a in reversed(self.app.runtime.views()) if a['target']==target and a['name']=='Drive')
                context.set_offline(True)
                final=self.wait(lambda:(lambda v:v if v['state'] in TERMINAL else None)(self.app.runtime.view(active['id'])),15)
                assert final['safety']['release_safe'] and self.oracles[target].recent_speed_mps()<=.1
                context.set_offline(False);page.keyboard.up('w');page.wait_for_timeout(2000)
                count=len(self.app.runtime.views());page.wait_for_timeout(1000);assert len(self.app.runtime.views())==count
                self.wait(lambda:target not in self.app.operator_controls.records,15)
                self.report['checks']['browser SEND revocation / HTTP+WS loss / no auto-resume']='PASS'
                assert not errors,errors
                self.report['checks']['real browser W+A / W+D / reverse / zero / toggle OFF / blur']='PASS'
                self.report['browser_errors']=errors
            except BaseException:
                page.screenshot(path=str(self.path/'rover-failure.png'),full_page=True)
                (self.path/'rover-failure.txt').write_text(page.locator('body').inner_text())
                self.report['browser_errors']=errors
                raise
            finally:browser.close()
        self.action(target,'Disarm')

    def binding_acceptance(self,identifier,owner,children):
        from vehicle_autonomy.app.mission_designer.mission_examples import examples
        from playwright.sync_api import sync_playwright,expect
        from tests.browser_auth import login
        a,b=children
        initial_a=self.oracles[a.target].latest();initial_b=self.oracles[b.target].latest()
        definitions=examples(a.target,'rover')
        readonly=self.publish(definitions[0])
        patrol_definition=definitions[2];patrol_definition['mission_id']='Binding_Rover_Patrol'
        for node in patrol_definition['nodes']:
            if node.get('action_type')=='Goto':node['parameters']['y_m']=initial_b.y_m
        patrol=self.publish(patrol_definition)
        canonical=json.loads(json.dumps(self.app.studio.library.snapshot()['publications'][patrol['key']]))
        self.report['original_publication']=dict(key=patrol['key'],hash=patrol['definition_hash'],validation_target=a.target)
        errors=[]
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                ca=browser.new_context(viewport={'width':1680,'height':1100});cb=browser.new_context(viewport={'width':1680,'height':1100})
                pa=ca.new_page();pb=cb.new_page()
                for page in (pa,pb):
                    page.on('pageerror',lambda e:errors.append(str(e)));login(page,self.base,self.token,'/studio')
                    expect(page.locator('#vehicle')).to_have_value('')
                pa.locator('#vehicle').select_option(a.target);pb.locator('#vehicle').select_option(b.target)
                for page,pub,send in ((pb,patrol,True),(pa,readonly,False)):
                    page.locator('[data-tab=runner]').click();page.locator('#publication').select_option(pub['key'])
                    if send:page.locator('#send').check()
                    page.locator('#run-start').click();expect(page.locator('#dialog-content')).to_contain_text(b.target if send else a.target)
                    page.screenshot(path=str(self.path/('mission-B-confirm.png' if send else 'mission-A-readonly-confirm.png')),full_page=True)
                    page.locator('#dialog-confirm').click()
                    expect(page.locator('#run-state')).to_contain_text('后端运行状态',timeout=10000)
                runs=self.app.missions.views();motion=next(r for r in runs if r['target']==b.target)
                before=len(self.app.missions.views())
                self.api('/api/studio-b/run/start',self.run_request(patrol,b.target),reject=True)
                assert len(self.app.missions.views())==before,'resource rejection added a Run'
                self.api('/api/studio-b/run/debug',dict(id=motion['id'],operation='rebind',parameters={'target':a.target}),reject=True)
                expect(pb.locator('#vehicle')).to_be_disabled();expect(pb.locator('#run-target')).to_be_disabled()
                expect(pa.locator('#vehicle')).to_have_value(a.target);expect(pb.locator('#vehicle')).to_have_value(b.target)
                final=self.finish_mission(motion)
                readrun=next(r for r in runs if r['target']==a.target);self.finish_mission(readrun)
                pb.wait_for_timeout(1500);pb.screenshot(path=str(self.path/'mission-B-result.png'),full_page=True)
                assert self.app.drivers[a.target].info()['writer']['attempts']==0
                writer=self.app.drivers[b.target].info()['writer'];assert writer['attempts']>0 and writer['target_system']==b.model.system_id
                assert {e['run_id'] for e in writer['recent']}<=set(final['action_ids'])
                assert math.dist([initial_a.x_m,initial_a.y_m],[self.oracles[a.target].latest().x_m,self.oracles[a.target].latest().y_m])<.02
                truth_b=self.oracles[b.target].latest();assert math.hypot(truth_b.x_m-initial_b.x_m-3,truth_b.y_m-initial_b.y_m)<.75
                self.report['writer_binding']=dict(A=dict(target=a.target,system_id=a.model.system_id,writer=self.app.drivers[a.target].info()['writer']),
                    B=dict(target=b.target,system_id=b.model.system_id,writer=writer,mission_id=final['id'],action_ids=final['action_ids']))
                self.report['checks'].update(rover_B_only_motion='PASS',two_browser_independent_selection='PASS',resource_conflict_no_extra_action='PASS',running_binding_immutable='PASS',readonly_no_SEND_no_motion_writes='PASS')
                # Add a different kind to the same real World; catalog must update.
                self.api('/api/simulation/add_vehicle',dict(id=identifier,vehicle=dict(kind='copter',spawn={'id':'south'})))
                r=self.operation(identifier);assert r['operation']['state']=='SUCCEEDED',r['operation']
                air=next(c for c in owner.vehicles.values() if c.vehicle=='copter')
                self.oracles[air.target]=GazeboTruthOracle(owner.world,air.model.name)
                expect(pa.locator('#vehicle option[value="'+air.target+'"]')).to_have_count(1,timeout=10000)
                self.api('/api/studio-b/run/start',self.run_request(patrol,air.target),reject=True)
                assert air.driver.info()['writer']['attempts']==0
                self.report['checks']['Rover + Copter incompatible reject']='PASS'
                old=self.run_request(readonly,a.target,send=False)
                self.api('/api/simulation/remove_vehicle',dict(id=identifier,vehicle_id=a.id))
                r=self.operation(identifier);assert r['operation']['state']=='SUCCEEDED',r['operation']
                self.oracles.pop(a.target,None)
                expect(pa.locator('#vehicle option[value="'+a.target+'"]')).to_have_count(0,timeout=10000)
                expect(pa.locator('#vehicle')).to_have_value('')
                self.api('/api/simulation/add_vehicle',dict(id=identifier,vehicle=dict(kind='rover',spawn={'id':'center'})))
                r=self.operation(identifier);assert r['operation']['state']=='SUCCEEDED',r['operation']
                c=next(c for c in owner.vehicles.values() if c.target not in (b.target,air.target))
                self.oracles[c.target]=GazeboTruthOracle(owner.world,c.model.name)
                self.api('/api/studio-b/run/start',old,reject=True)
                assert c.driver.info()['writer']['attempts']==0
                copied=self.api('/api/studio-b/template/apply',dict(source='Example_Ground_Patrol',new_mission_id='Unbound_Copy'))
                assert copied['definition']['target']==''
                self.report['checks']['remove A / add C never rebound']='PASS'
                self.report['checks']['catalog add / remove synchronized']='PASS'
                assert self.app.studio.library.snapshot()['publications'][patrol['key']]==canonical
                self.report['checks']['original publication unchanged']='PASS'
                assert not errors,errors
            except BaseException:
                for label,page in (('A',pa),('B',pb)):
                    page.screenshot(path=str(self.path/('failure-'+label+'.png')),full_page=True)
                    (self.path/('failure-'+label+'.txt')).write_text(page.locator('body').inner_text())
                self.report['browser_errors']=errors
                raise
            finally:browser.close()
        old=self.run_request(readonly,air.target,send=False)
        for child in (b,c):
            self.api('/api/simulation/remove_vehicle',dict(id=identifier,vehicle_id=child.id))
            r=self.operation(identifier);assert r['operation']['state']=='SUCCEEDED',r['operation']
            self.oracles.pop(child.target,None)
        switched=self.api('/api/simulation/switch',dict(id=identifier,scene_id='R01',parameters={'obstacle_count':0}))
        new_id=switched['switch']['new_session_id']
        self.wait(lambda:self.app.simulation_manager.sample(identifier).get('switch',{}).get('state')=='SUCCEEDED',180)
        self.api('/api/studio-b/run/start',old,reject=True)
        self.report['checks']['World switch rejects old target / epoch']='PASS'
        new_owner=self.app.simulation_manager.owners[new_id];self.oracles.clear()
        self.api('/api/simulation/add_vehicle',dict(id=new_id,vehicle=dict(kind='copter',spawn={'id':'north'})))
        r=self.operation(new_id);assert r['operation']['state']=='SUCCEEDED',r['operation']
        os.environ.update(GZ_PARTITION=new_owner.partition)
        for child in new_owner.vehicles.values():self.oracles[child.target]=GazeboTruthOracle(new_owner.world,child.model.name)
        time.sleep(45)
        aircraft=list(new_owner.vehicles.values())
        fresh=self.run_request(readonly,aircraft[0].target,send=False)
        for field in ('epoch','session_id','generation'):
            stale=json.loads(json.dumps(fresh));stale['binding'][field]=old['binding'][field]
            self.api('/api/studio-b/run/start',stale,reject=True)
        assert aircraft[0].driver.info()['writer']['attempts']==0
        self.report['checks']['new target with old epoch / link / generation rejects without Writer']='PASS'
        hover=examples(aircraft[0].target,'copter')[2]
        pub=self.publish(hover)
        for child in aircraft:
            initial=self.oracles[child.target].latest()
            v=self.finish_mission(self.api('/api/studio-b/run/start',self.run_request(pub,child.target)),120)
            relevant=[s for s in self.samples if s['target']==child.target]
            assert max(s['truth']['z_m'] for s in relevant)-initial.z_m>=1.15
            assert not child.driver.snapshot().vehicle.operation.armed
            assert self.oracles[child.target].latest().z_m-initial.z_m<.25
            writer=child.driver.info()['writer'];assert writer['target_system']==child.model.system_id
            self.report.setdefault('aircraft_bindings',[]).append(dict(instance=self.binding(child.target),writer=writer,run_id=v['id']))
        self.report['checks']['Copter A + B same immutable publication / real takeoff and landing']='PASS'


def run(directory, stage):
    n = Native(directory)
    try:
        _,owner,children=n.create(('rover','rover') if stage=='binding' else ('rover',))
        target=children[0].target
        if stage=='rover-motion':
            n.action(target,'Arm')
            n.drive(target)
            n.action(target,'SetMode',{'mode':'GUIDED'})
            n.action(target,'Goto',dict(x_m=0.,y_m=0.,z_m=0.))
            n.report['checks']['ordinary Goto and observed HOLD exit']='PASS'
            n.drive(target,neutral=True)
            n.action(target,'SetMode',{'mode':'GUIDED'})
            n.action(target,'Goto',dict(x_m=0.,y_m=0.,z_m=0.))
            n.drive(target,neutral=True,stress=True)
            n.drive(target,deadman=True)
            n.action(target,'Disarm')
            n.report['checks']['rover continuous direction / zero stop / active HOLD / deadman']='PASS'
        elif stage=='rover-ui':
            n.browser_rover(target)
            n.prepare_shutdown_motion(target)
        else:n.binding_acceptance(_,owner,children)
        n.report['status']='PASS'
    except Exception as exc:
        n.report['error']=type(exc).__name__+': '+str(exc)[:1500];traceback.print_exc()
    finally:n.close()
    print(json.dumps({k:v for k,v in n.report.items() if k not in ('vehicles','missions')},ensure_ascii=False,default=str),flush=True)
    return n.report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True);p.add_argument('--stage',choices=('rover-motion','rover-ui','binding'),default='rover-motion');p.add_argument('--allow-send',action='store_true');a=p.parse_args()
    if not a.allow_send:p.error('explicit owned simulation SEND required')
    raise SystemExit(run(a.run_dir,a.stage)['status']!='PASS')

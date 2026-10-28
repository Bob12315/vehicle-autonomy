"""Real Chrome presentation regression; isolated HTTP, no vehicle connection.

Checks localization without changing Mission wire identifiers, editor controls,
read-only/Wait execution, responsive layout and unchanged authorization defaults.
This does not replace physical SITL acceptance.
"""
from tests.browser_auth import login
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
from threading import Thread
import time
from unittest.mock import patch

from tests.mission_graph.test_service import WebDriver
from vehicle_autonomy.actions.catalog import capabilities
from vehicle_autonomy.app.web.mission_control import MissionControl, MissionControlServer
from vehicle_autonomy.contracts.action import ActionContext



def edge_checks(page,lab):
    """Invalid editing/import cannot submit a Mission or silently drop edges."""
    from playwright.sync_api import expect
    original=page.locator('#json').input_value()
    page.locator('#json').locator('..').locator('summary').click()
    mutations=[]
    page.on('request',lambda r:mutations.append(r.url) if r.method=='POST' and '/api/missions/' in r.url else None)
    def draft(nodes):
        return dict(schema_version=1,id='edge-regression',name='连线回归',version='1.0.0',target='v',root='n1',
            nodes=[dict(n,position={'x':30+210*i,'y':30}) for i,n in enumerate(nodes)])
    def apply(spec):
        page.locator('#json').fill(json.dumps(spec));page.locator('#apply-json').click()
    for kind in ('Action','Wait'):
        parent=dict(id='n1',type=kind,children=['n2'])
        if kind=='Action':parent.update(action='GetVehicleState',parameters={})
        else:parent['duration_s']=.1
        apply(draft([parent,dict(id='n2',type='Wait',duration_s=.1,children=[])]))
        page.locator('[data-node-id="n1"]').click()
        expect(page.locator('#connect-nodes')).to_be_disabled()
        expect(page.locator('#child-rule')).to_contain_text('叶子节点')
        assert json.loads(page.locator('#json').input_value())['nodes'][0]['children']==['n2']
        for button in ('validate','save','start'):
            page.locator('#'+button).click()
            expect(page.locator('#notice')).to_contain_text('n1')
            expect(page.locator('#notice')).to_contain_text('不能连接子节点')
            expect(page.locator('#notice')).to_contain_text('顺序执行')
        page.locator('#properties button').filter(has_text='断开').click()
        assert json.loads(page.locator('#json').input_value())['nodes'][0]['children']==[]
    apply(draft([dict(id='n1',type='Sequence',children=['n2']),dict(id='n2',type='Sequence',children=[])]))
    page.locator('[data-node-id="n2"]').click();page.locator('#connect-nodes').click();page.locator('[data-node-id="n1"]').click()
    expect(page.locator('#notice')).to_contain_text('循环')
    assert json.loads(page.locator('#json').input_value())['nodes'][1]['children']==[]
    apply(draft([dict(id='n1',type='Sequence',children=['n2','n3']),dict(id='n2',type='Sequence',children=['n4']),
        dict(id='n3',type='Sequence',children=[]),dict(id='n4',type='Wait',duration_s=.1,children=[])]))
    page.locator('[data-node-id="n3"]').click();page.locator('#connect-nodes').click();page.locator('[data-node-id="n4"]').click()
    expect(page.locator('#notice')).to_contain_text('已有父节点')
    assert json.loads(page.locator('#json').input_value())['nodes'][2]['children']==[]
    apply(draft([dict(id='n1',type='Timeout',timeout_s=1,children=['n2']),dict(id='n2',type='Wait',duration_s=.1,children=[])]))
    page.locator('[data-node-id="n1"]').click();page.locator('#connect-nodes').click()
    expect(page.locator('#notice')).to_contain_text('上限')
    apply(draft([dict(id='n1',type='Action',action='Goto',action_version='1.0.0',parameters={},children=[])]))
    page.locator('[data-node-id="n1"]').click()
    for button in ('validate','save','start'):
        page.locator('#'+button).click()
        expect(page.locator('#notice')).to_contain_text('请填写东向位置')
    assert 'x_m' not in json.loads(page.locator('#json').input_value())['nodes'][0]['parameters']
    assert not mutations and not lab.missions.views() and not lab.runtime.views()
    page.locator('#json').fill(original);page.locator('#apply-json').click()
    page.locator('#json').locator('..').locator('summary').click()
    return ['Action/Wait outgoing disabled','imported leaf children retained and blocked before validate/save/start',
        'explicit disconnect repairs edge','cycle rejected','shared child rejected','child capacity enforced','blank required coordinates blocked before Mission submission']


def run(directory):
    from playwright.sync_api import sync_playwright, expect
    directory.mkdir(parents=True, exist_ok=False)
    driver=WebDriver()
    driver.context=lambda:ActionContext('v','rover',capabilities('rover'),True,
        metadata={'mode_ids':{'HOLD':4,'GUIDED':15,'RTL':11}})
    errors=[];result={'passed':False,'source':'real Chrome / isolated HTTP / no vehicle transport'}
    with ExitStack() as stack:
        stack.enter_context(patch('vehicle_autonomy.app.web.mission_control.bind_simulations',return_value={}))
        lab=MissionControl({'v':driver},directory/'application');stack.callback(lab.close)
        token=secrets.token_urlsafe(32)
        server=MissionControlServer(('127.0.0.1',0),lab,token,directory/'http.jsonl')
        thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.02});thread.start()
        def stop():server.shutdown();thread.join(3);server.server_close()
        stack.callback(stop)
        base='http://127.0.0.1:'+str(server.server_address[1])
        pw=stack.enter_context(sync_playwright())
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        stack.callback(browser.close)
        page=browser.new_page(viewport={'width':1680,'height':1100})
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            login(page,base,token,'/studio')
            expect(page.locator('h1')).to_have_text('任务编排')
            expect(page.locator('#empty-graph')).to_be_visible()
            for kind,label in [('Sequence','顺序执行'),('Parallel','并行执行'),('Condition','条件判断'),('Fallback','失败备选'),('Recovery','故障恢复'),('Event','事件触发'),('Reactive','事件响应'),('Wait','等待'),('Timeout','超时限制'),('Repeat','有限重复')]:
                expect(page.locator(f'#palette [data-type="{kind}"] strong')).to_have_text(label)
            expect(page.locator('#action-library option').first).to_be_attached()
            expect(page.locator('#send')).not_to_be_checked()
            expect(page.locator('#action-library option[value="Arm@1.0.0"]')).to_contain_text('解锁')
            result['edge_guards']=edge_checks(page,lab)
            page.locator('#add-sequence').click()
            page.locator('#palette [data-type="Wait"]').click()
            page.locator('[data-node-id="n1"]').click();page.locator('#connect-nodes').click();page.locator('[data-node-id="n2"]').click()
            expect(page.locator('[data-node-id="n1"] strong')).to_have_text('顺序执行')
            expect(page.locator('#empty-graph')).to_be_hidden()
            page.locator('[data-node-id="n2"]').click()
            page.locator('#properties [name="duration_s"]').fill('0.15');page.locator('#properties [name="duration_s"]').press('Tab')
            page.locator('#action-library').select_option('GetVehicleState@1.0.0');page.locator('#add-action').click()
            expect(page.locator('[data-node-id="n3"] strong')).to_have_text('读取车辆状态')
            page.locator('#delete').click()
            page.locator('#undo').click();expect(page.locator('[data-node-id="n3"]')).to_be_visible()
            page.locator('#redo').click();expect(page.locator('[data-node-id="n3"]')).to_have_count(0)
            page.locator('#layout').click();page.locator('#zoom-in').click();page.locator('#fit').click()
            page.locator('#validate').click();expect(page.locator('#validation')).to_contain_text('校验通过')
            page.locator('#save').click();expect(page.locator('#validation')).to_have_text('版本已保存')
            with page.expect_download() as download:page.locator('#export').click()
            download.value.save_as(str(directory/'export.json'))
            spec=json.loads((directory/'export.json').read_text())
            assert spec['nodes'][0]['type']=='Sequence' and spec['nodes'][1]['type']=='Wait'
            assert spec['nodes'][0]['children']==['n2'] and spec['root']=='n1'
            assert 'name' not in spec['nodes'][0] # Presentation never adds unsupported wire fields.
            page.locator('#import').set_input_files(str(directory/'export.json'))
            page.locator('#load').click()
            # A Wait-only Mission needs no SEND and creates no vehicle effects.
            page.locator('#start').click();expect(page.locator('#run-summary')).to_contain_text('已成功',timeout=5000)
            assert lab.missions.views()[-1]['state']=='SUCCEEDED'
            assert lab.missions.views()[-1]['release_safe'] and not lab.runtime.views()
            page.screenshot(path=str(directory/'studio-desktop.png'),full_page=True,mask=[])
            for width in (1280,1024,390):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'Studio overflow at {width}'
                if width==390:page.screenshot(path=str(directory/'studio-mobile.png'),full_page=True,mask=[])
            page.set_viewport_size({'width':1680,'height':1100});page.goto(base+'/control')
            expect(page.locator('#vehicle-name')).to_contain_text('v')
            expect(page.locator('#top-authority')).to_have_text('SEND OFF')
            expect(page.locator('[data-action="Arm"]')).to_be_disabled()
            expect(page.locator('#vehicle-status')).to_contain_text('未知')
            expect(page.locator('#telemetry-warning')).to_contain_text('过期或未知')
            expect(page.locator('#send')).to_have_count(0);expect(page.locator('#manual-send')).to_have_count(0)
            page.locator('#speed').fill('0.45');expect(page.locator('#speed-value')).to_have_text('0.45 m/s')
            page.locator('h1').click();page.keyboard.press('"')
            page.screenshot(path=str(directory/'control-desktop.png'),full_page=True)
            for width in (1280,1024,390):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),f'Control overflow at {width}'
                if width==390:page.screenshot(path=str(directory/'control-mobile.png'),full_page=True)
            assert not driver.writes and not lab.runtime.views()
            # An unknown Plane must expose no flight operations, even when an
            # operator checks a local SEND box. Actual flight is a separate SITL test.
            driver.info=lambda:dict(target='v',kind='plane',connected=True,session_id='fixture',system_send=False,action_send=False)
            driver.context=lambda:ActionContext('v','plane',frozenset(capabilities('plane')),True)
            page.set_viewport_size({'width':1680,'height':1100});page.goto(base+'/control')
            expect(page.locator('#vehicle-name')).to_contain_text('Plane')
            expect(page.locator('[data-action="Loiter"]')).to_be_disabled()
            expect(page.locator('#guided-target')).to_be_disabled()
            expect(page.locator('#acquire-control')).to_be_disabled()
            assert not driver.writes and not lab.runtime.views()
            assert not errors,errors
            result.update(passed=True,javascript_errors=errors,writer_calls=len(driver.writes),
                localized_node_types=10,responsive_widths=[1680,1280,1024,390],
                machine_identifiers_preserved=True,send_defaults_false=True,plane_stale_blocks_submission=True,observer_blocks_motion=True,wait_mission='SUCCEEDED')
        except Exception as exc:
            result['error']=type(exc).__name__+': '+str(exc)
            page.screenshot(path=str(directory/'failure.png'),full_page=True,mask=[])
            raise
        finally:(directory/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-dir',type=Path,required=True)
    print(json.dumps(run(parser.parse_args().run_dir),ensure_ascii=False))

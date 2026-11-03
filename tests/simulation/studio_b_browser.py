"""Actual browser + isolated HTTP/real executor acceptance, no vehicle transport."""
import argparse,json,secrets,time
from dataclasses import dataclass,field
from contextlib import ExitStack
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from tests.browser_auth import login
from tests.mission_graph.test_service import WebDriver
from tests.action_system.test_runtime import Factory,Parameters
from vehicle_autonomy.contracts.decision import ActionSpec
from vehicle_autonomy.contracts.action import ActionContext
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer


@dataclass(frozen=True)
class Position:
    x:float=0.
    y:float=0.

@dataclass(frozen=True)
class Shape:
    position:Position=field(default_factory=Position)
    samples:tuple[int,...]=()
    enabled:bool=False


def run(directory,*,demo=False):
    from playwright.sync_api import sync_playwright,expect
    directory.mkdir(parents=True,exist_ok=False);errors=[];driver=WebDriver();registry=ActionRegistry()
    registry.register_typed(ActionSpec('BrowserWork',Parameters,external_lifecycle='typed_only',output_schema={'type':'object','properties':{'count':{'type':'integer'}},'required':['count']}),Factory())
    registry.register_typed(ActionSpec('BrowserShape',Shape,external_lifecycle='typed_only'),Factory())
    if demo:driver.context=lambda:ActionContext('v','copter',frozenset(),True)
    from tests.web_ui.helpers import FixtureDriver
    driver.snapshot=FixtureDriver('copter' if demo else 'rover').snapshot
    result=dict(passed=False,environment='isolated HTTP + Chrome + existing executor; no vehicle transport')
    with ExitStack() as stack:
        stack.enter_context(patch('vehicle_autonomy.app.web.mission_control.bind_simulations',return_value={}))
        lab=MissionControl({'v':driver},directory/'application',registry=registry,studio_demo=demo);stack.callback(lab.close)
        token=secrets.token_urlsafe(32);server=MissionControlServer(('127.0.0.1',0),lab,token,directory/'http.jsonl')
        thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.02});thread.start()
        def stop():server.shutdown();thread.join(3);server.server_close()
        stack.callback(stop);base='http://127.0.0.1:'+str(server.server_address[1])
        pw=stack.enter_context(sync_playwright());browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage']);stack.callback(browser.close)
        page=browser.new_page(viewport={'width':1680,'height':1050});page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            login(page,base,token,'/studio');expect(page.locator('h1')).to_have_text('任务库');expect(page.locator('#save-state')).to_contain_text('统一会话')
            for source in ('/control','/console'):
                page.goto(base+source);page.locator('nav a[href="/studio"]').click()
                expect(page.locator('h1')).to_have_text('任务库');expect(page.locator('#save-state')).to_contain_text('统一会话')
            page.screenshot(path=str(directory/'01-library.png'),full_page=True)
            page.locator('#vehicle').select_option('v');page.locator('#new-mission').click();page.get_by_label('任务名称',exact=True).fill('Browser end-to-end');page.locator('#dialog-confirm').click()
            expect(page.locator('#editor-view')).to_be_visible();expect(page.locator('.graph-node')).to_have_count(2)
            page.locator('#palette [data-category=logic] summary').click();page.locator('#palette button').filter(has_text='等待').click();expect(page.locator('.graph-node')).to_have_count(3)
            wait=page.locator('.graph-node').filter(has=page.locator('.node-category',has_text='等待'));wait_id=wait.get_attribute('data-node')
            page.get_by_label(wait_id+'.duration_s',exact=True).fill('0.15');page.get_by_label(wait_id+'.duration_s',exact=True).press('Tab')
            page.get_by_label('断点',exact=True).check()
            def connect(source,target):
                a=page.locator('[data-output="'+source+'"][data-port="next"]').bounding_box();b=page.locator('[data-input="'+target+'"]').bounding_box()
                page.mouse.move(a['x']+a['width']/2,a['y']+a['height']/2);page.mouse.down();page.mouse.move(b['x']+b['width']/2,b['y']+b['height']/2,steps=12);page.mouse.up()
            connect('start',wait_id);connect(wait_id,'end');page.locator('#layout').click();page.locator('#undo').click();page.locator('#redo').click()
            # Exercise real HTML drag/drop and recursive typed forms.
            page.locator('#palette [data-category=uncategorized] button.palette-item').filter(has_text='BrowserShape').drag_to(page.locator('#graph-viewport'),target_position={'x':200,'y':230})
            expect(page.locator('.graph-node')).to_have_count(4)
            shape=page.locator('.graph-node').filter(has_text='BrowserShape');shape.click();shape_id=shape.get_attribute('data-node')
            for label,value in [('position.x','2'),('position.y','3')]:page.get_by_label(label,exact=True).fill(value);page.get_by_label(label,exact=True).press('Tab')
            page.get_by_label('enabled',exact=True).check();page.get_by_role('button',name='＋ 添加项',exact=True).click();page.get_by_label('samples.0',exact=True).fill('5');page.get_by_label('samples.0',exact=True).press('Tab')
            page.get_by_role('button',name='＋ 添加项',exact=True).click();page.get_by_label('samples.1',exact=True).fill('7');page.get_by_label('samples.1',exact=True).press('Tab')
            page.locator('#save-draft').click();expect(page.locator('#save-state')).to_contain_text('已保存')
            stored=next(v['definition'] for v in lab.studio.library.snapshot()['drafts'].values() if v['definition']['name']=='Browser end-to-end')
            params=next(n['parameters'] for n in stored['nodes'] if n['node_id']==shape_id);assert params==dict(position=dict(x=2.,y=3.),samples=[5,7],enabled=True),params
            page.locator('#palette [data-category=uncategorized] button.palette-item').filter(has_text='BrowserWork').click();expect(page.locator('.graph-node')).to_have_count(5)
            page.locator('#properties').get_by_role('button',name='高级',exact=True).click();page.get_by_label('count 输出变量',exact=True).locator('..').get_by_role('button',name='＋ 结果列表',exact=True).click();page.locator('#dialog-confirm').click()
            page.locator('#save-draft').click();expect(page.locator('#save-state')).to_contain_text('已保存')
            stored=next(v['definition'] for v in lab.studio.library.snapshot()['drafts'].values() if v['definition']['name']=='Browser end-to-end');assert stored['blackboard']['count_list']['schema']['items']['type']=='integer'
            page.locator('#delete').click();expect(page.locator('.graph-node')).to_have_count(4);page.locator('[data-node="'+shape_id+'"]').click()
            page.locator('#copy').click();page.locator('#paste').click();expect(page.locator('.graph-node')).to_have_count(5);page.locator('#delete').click();expect(page.locator('.graph-node')).to_have_count(4)
            page.locator('[data-node="'+shape_id+'"]').click();page.locator('#delete').click();expect(page.locator('.graph-node')).to_have_count(3)
            page.locator('#save-draft').click();expect(page.locator('#save-state')).to_contain_text('已保存')
            page.locator('#validate').click();expect(page.locator('#notice')).to_contain_text('静态验证通过')
            page.screenshot(path=str(directory/'02-editor.png'),full_page=True)
            page.locator('#publish').click();expect(page.locator('#notice')).to_contain_text('已发布不可变版本')
            page.locator('[data-tab=runner]').click();page.locator('#debug-run').check();page.locator('#run-start').click();page.locator('#dialog-confirm').click();expect(page.locator('#run-state')).to_contain_text('已暂停',timeout=8000)
            page.locator('[data-debug=step]').click();page.wait_for_timeout(600);expect(page.locator('#run-state')).to_contain_text('已暂停');page.locator('[data-debug=resume]').click();expect(page.locator('#run-state')).to_contain_text('执行成功',timeout=8000)
            page.locator('[data-inspect=events]').click();expect(page.locator('.inspector-event').first).to_be_visible()
            page.screenshot(path=str(directory/'03-runner.png'),full_page=True)
            run=lab.missions.views()[-1];assert run['state']=='SUCCEEDED' and run['release_safe'];assert run['studio']['definition']['nodes'];assert not driver.writes
            if demo:
                page.locator('[data-tab=templates]').click();page.locator('.mission-card').filter(has_text='CUADC 多目标').get_by_role('button',name='从模板创建',exact=True).click()
                page.locator('[data-node=handle]').dblclick();expect(page.locator('#breadcrumbs')).to_contain_text('处理目标');page.get_by_role('button',name='← 返回父 任务',exact=True).click()
                page.locator('#mission-target').select_option('v');page.locator('#publish').click();expect(page.locator('#notice')).to_contain_text('已发布不可变版本');page.locator('[data-tab=runner]').click();page.locator('#debug-run').uncheck();previous_runs=len(lab.missions.views());page.locator('#run-start').click();page.locator('#dialog-confirm').click()
                until=time.monotonic()+10
                while len(lab.missions.views())==previous_runs and time.monotonic()<until:page.wait_for_timeout(50)
                assert len(lab.missions.views())==previous_runs+1;expect(page.locator('#run-state')).to_contain_text('执行成功',timeout=15000)
                demo_run=lab.missions.views()[-1];values={c['name']:c['data']['value'] for c in demo_run['studio']['blackboard']['values'] if c['scope_id']=='mission'}
                assert [r['target_id'] for r in values['results']]==['T-02','T-03'];assert values['simulated_payload_remaining']==0;assert not driver.writes
                page.locator('[data-node=handle]').dblclick();expect(page.locator('#runner-breadcrumbs')).to_contain_text('处理目标');page.wait_for_timeout(1500);expect(page.locator('#runner-breadcrumbs')).to_contain_text('处理目标');page.get_by_role('button',name='← 返回父 任务',exact=True).click()
                page.locator('[data-inspect=blackboard]').click();expect(page.locator('#inspector-content')).to_contain_text('selected_targets');page.screenshot(path=str(directory/'05-cuadc-scopes.png'),full_page=True)
                result['cuadc']=dict(run=demo_run['id'],selected=[t['id'] for t in values['selected_targets']],results=values['results'])
            page.reload();expect(page.locator('h1')).to_have_text('任务库');expect(page.locator('#save-state')).to_contain_text('统一会话')
            page.goto(base+'/console');expect(page.locator('h1')).to_be_visible();page.goto(base+'/studio');expect(page.locator('h1')).to_have_text('任务库')
            page.set_viewport_size({'width':820,'height':1050});page.screenshot(path=str(directory/'04-tablet.png'),full_page=True)
            assert not errors,errors;result.update(passed=True,run=run['id'],checks=['Library first','dynamic palette','node add','port connections','schema input','undo/redo','CAS autosave','validate/publish','real executor Wait run','events','refresh + cross-page session','tablet layout'],browser_errors=errors)
        except BaseException as exc:
            page.screenshot(path=str(directory/'failure.png'),full_page=True);result.update(error=type(exc).__name__+': '+str(exc),browser_errors=errors);raise
        finally:(directory/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--demo',action='store_true');args=parser.parse_args();print(json.dumps(run(args.output,demo=args.demo),ensure_ascii=False))

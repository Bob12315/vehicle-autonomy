"""Actual Chrome graph editing and manual controls; no fetch/evaluate substitutes."""
import json
import time

from tests.simulation.mission_scenario import build_mission
from tests.browser_auth import login

TERMINAL={'SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN'}


def wait(page,fixture,predicate,seconds=20):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        fixture.truth()
        value=predicate()
        if value:return value
        page.wait_for_timeout(50)
    raise TimeoutError('Chrome operation: '+page.locator('#notice').inner_text()[:500])


def create_mission(page,f,result):
    spec=build_mission(f.kind)
    login(page,f.base,f.token,'/studio')
    page.locator('#action-library option').first.wait_for(state='attached')
    for field,value in [('mission-id',spec['id']),('mission-name',spec['name']),('mission-version',spec['version']),('mission-timeout',str(spec['timeout_s']))]:
        page.locator('#'+field).fill(value);page.locator('#'+field).press('Tab')
    ids={}
    for i,n in enumerate(spec['nodes'],1):
        if n['type']=='Action':
            page.locator('#action-library').select_option(n['action']+'@1.0.0');page.locator('#add-action').click()
        else:page.locator(f'#palette button[data-type="{n["type"]}"]').click()
        ids[n['id']]='n'+str(i)
        page.locator(f'[data-node-id="n{i}"]').click()
        if n['type']=='Action':
            for name,value in n.get('parameters',{}).items():
                if isinstance(value,dict) and '$query' in value:
                    q=value['$query'];page.locator('#properties summary').filter(has_text='类型化观测参数绑定').click()
                    page.locator('#binding-field').select_option(name);page.locator('#binding-source').select_option(q['source'])
                    page.locator('#binding-path').fill(q['path']);page.locator('#binding-frame').fill(q.get('frame',''))
                    page.locator('#binding-offset').fill(str(q.get('offset',0)))
                    page.get_by_role('button',name='绑定参数',exact=True).click()
                    continue
                control=page.locator(f'#node-parameters [name="{name}"]')
                if control.is_disabled():continue
                if control.evaluate('(e)=>e.tagName')=='SELECT':control.select_option(json.dumps(value))
                else:control.fill(str(value));control.press('Tab')
            if n.get('output'):page.locator('#properties [name="output"]').fill(n['output']);page.locator('#properties [name="output"]').press('Tab')
        elif n['type']=='Wait':
            page.locator('#properties [name="duration_s"]').fill(str(n['duration_s']));page.locator('#properties [name="duration_s"]').press('Tab')
        elif n['type']=='Condition':
            # This physical Mission uses the same default typed armed query.
            assert n['expression']==dict(op='eq',source='world',path='vehicle.operation.armed',value=True,max_age_s=3)
    for n in spec['nodes']:
        for child in n.get('children',[]):
            page.locator(f'[data-node-id="{ids[n["id"]]}"]').click();page.locator('#connect-nodes').click()
            page.locator(f'[data-node-id="{ids[child]}"]').click()
    page.locator('#layout').click();page.locator('#undo').click();page.locator('#redo').click();page.locator('#fit').click()
    page.locator('#validate').click();page.locator('#validation').filter(has_text='schema_version').wait_for(timeout=5000)
    page.locator('#save').click();page.locator('#validation').filter(has_text='版本已保存').wait_for()
    with page.expect_download() as download:page.locator('#export').click()
    download.value.save_as(str(f.path/'browser-mission-export.json'))
    page.locator('#import').set_input_files(str(f.path/'browser-mission-export.json'))
    page.locator('#load').click();page.locator('#send').check();page.locator('#start').click()
    r=wait(page,f,lambda:next(iter(f.lab.missions.views()),None),10)
    result['mission_checkpoints']={}
    def completed():
        current=f.lab.missions.view(r['id'])
        for a in f.lab.runtime.views():
            if a['id'] not in current['action_ids'] or a['state']!='SUCCEEDED' or a['name'] in result['mission_checkpoints']:continue
            t=f.truth();result['mission_checkpoints'][a['name']]=dict(truth=[t.x_m,t.y_m,t.z_m],speed_mps=f.oracle.recent_speed_mps(),action=a)
            if a['name']=='SetGuidedTarget':
                from tests.simulation.mission_physics import target_reference
                result['mission_checkpoints'][a['name']]['native_reference']=target_reference(f,a)
        if current['state'] in TERMINAL:
            if current['state']!='SUCCEEDED':raise AssertionError('Chrome Mission '+str(current))
            return current
    mission=wait(page,f,completed,960 if f.kind=='plane' else 210)
    if not mission['release_safe'] or mission['continuation_allowed']:raise AssertionError('Mission did not safely release')
    result['mission']=mission
    page.locator('#run-detail').locator('..').locator('summary').click()
    page.locator('#run-detail').filter(has_text='SUCCEEDED').wait_for()
    page.screenshot(path=str(f.path/'mission-studio.png'),full_page=True)
    return mission


def manual(page,f,result):
    """Keep the original Mission test; exercise the current, map-free console."""
    from playwright.sync_api import expect
    from tests.simulation.web_ui_controls import BrowserControlCheck
    login(page,f.base,f.token,'/control')
    page.locator('#acquire-control').click();expect(page.locator('#top-authority')).to_have_text('SEND ON')
    directory=f.path/'manual-browser';directory.mkdir()
    check=BrowserControlCheck(f.kind,f.api,f.oracle,directory,page)
    physical=check.run();result['manual_control']=physical
    result['manual_actions']=physical['actions'];result['managed_inputs']=physical['managed']
    t=f.truth();result['manual_final_truth']=dict(position=[t.x_m,t.y_m,t.z_m],speed_mps=f.oracle.recent_speed_mps())
    page.locator('#release-control').click();expect(page.locator('#top-authority')).to_have_text('SEND OFF')
    page.screenshot(path=str(f.path/'manual-control.png'),full_page=True)
    return result


def exercise(f,result):
    from playwright.sync_api import sync_playwright
    result['browser']='real Chrome headless';errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            context=browser.new_context(viewport={'width':1680,'height':1100});page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            create_mission(page,f,result);manual(page,f,result)
            if errors:raise AssertionError('Chrome JavaScript errors: '+str(errors))
            result['javascript_errors']=errors
        finally:browser.close()

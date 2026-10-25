"""Actual Chrome graph editing and manual controls; no fetch/evaluate substitutes."""
import json
import math
import time

from tests.simulation.mission_scenario import build_mission

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
    page.goto(f.base+'/studio');page.locator('#token').fill(f.token);page.locator('#connect').click()
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
    page.locator('#save').click();page.locator('#validation').filter(has_text='Version saved').wait_for()
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
    page.locator('#run-detail').filter(has_text='SUCCEEDED').wait_for()
    page.screenshot(path=str(f.path/'mission-studio.png'),full_page=True,mask=[page.locator('#token')])
    return mission


def manual(page,f,result):
    page.goto(f.base+'/control');page.locator('#token').fill(f.token);page.locator('#connect').click()
    page.locator('#action option').first.wait_for(state='attached')
    result['manual_actions']=[];previous=None
    def perform(name,parameters=None,*,keep_form=False,expected='SUCCEEDED',timeout=60):
        nonlocal previous
        old={a['id'] for a in f.lab.runtime.views()}
        if not keep_form:
            page.locator('#action').select_option(name+'@1.0.0')
            for key,value in (parameters or {}).items():
                c=page.locator(f'#parameters [name="{key}"]')
                if c.is_disabled():continue
                if c.evaluate('(e)=>e.tagName')=='SELECT':c.select_option(json.dumps(value))
                else:c.fill(str(value));c.press('Tab')
        page.locator('#continuation').fill(previous or '')
        page.locator('#send').check();page.locator('#execute').click()
        a=wait(page,f,lambda:next((a for a in f.lab.runtime.views() if a['id'] not in old),None),10)
        if page.locator('#send').is_checked():raise AssertionError('manual SEND persisted across commands')
        def done():
            value=f.lab.runtime.view(a['id'])
            if value['state'] not in TERMINAL:return None
            if value['state']!=expected:raise AssertionError('manual '+str(value))
            return value
        a=wait(page,f,done,timeout);result['manual_actions'].append(a)
        if a['state']=='SUCCEEDED':previous=a['id'] if a['safety'] and a['safety']['continuation_allowed'] else None
        return a
    perform('SetMode',{'mode':'MANUAL' if f.kind=='plane' else 'GUIDED'});perform('Arm')
    if f.kind!='plane':
        if f.kind=='copter':perform('Takeoff',{'height_m':1.5},timeout=60)
        result['managed_inputs']=[]
        for fault in ('release','expiry','disconnect'):
            if f.kind=='rover' and fault!='release':perform('SetMode',{'mode':'GUIDED'})
            before={a['id'] for a in f.lab.runtime.views()};initial=f.truth()
            page.locator('#manual-send').check();button=page.locator('[data-key="w"]');button.hover();page.mouse.down()
            a=wait(page,f,lambda:next((a for a in f.lab.runtime.views() if a['id'] not in before),None),5)
            wait(page,f,lambda:f.lab.runtime.view(a['id'])['state']=='RUNNING',5)
            until=time.monotonic()+2
            while time.monotonic()<until:f.truth();page.wait_for_timeout(50)
            moved=f.truth();distance=math.hypot(moved.x_m-initial.x_m,moved.y_m-initial.y_m)
            if distance<.15:raise AssertionError('real Chrome managed input did not move vehicle in Gazebo')
            if fault=='release':page.mouse.up()
            elif fault=='expiry':
                page.route('**/api/manual/update',lambda route:route.abort());page.route('**/api/manual/stop',lambda route:route.abort())
            else:page.context.set_offline(True)
            def terminal_input():
                value=f.lab.runtime.view(a['id'])
                if value['state'] not in TERMINAL:return None
                expected='CANCELLED' if fault=='release' else 'TIMED_OUT'
                if value['state']!=expected:raise AssertionError(fault+' input '+str(value))
                if not value['safety'] or not value['safety']['release_safe']:raise AssertionError('manual exit not proven')
                return value
            end=wait(page,f,terminal_input,16)
            limit=.1 if f.kind=='rover' else .15
            if f.oracle.recent_speed_mps()>limit:raise AssertionError('manual '+fault+' stop not corroborated by Gazebo')
            if fault=='expiry':page.unroute('**/api/manual/update');page.unroute('**/api/manual/stop');page.mouse.up()
            if fault=='disconnect':page.context.set_offline(False);page.mouse.up()
            page.wait_for_timeout(250)
            if page.locator('#manual-send').is_checked():raise AssertionError('manual session silently reauthorized')
            if len([x for x in f.lab.runtime.views() if x['id'] not in before])!=1:raise AssertionError('input updates created new Action instances')
            from tests.simulation.mission_physics import no_expired_motion
            result['managed_inputs'].append(dict(fault=fault,distance_m=distance,final=end,physical_stop_speed_mps=f.oracle.recent_speed_mps(),writer_deadline_check=no_expired_motion(f,end)))
        if f.kind=='rover':perform('SetMode',{'mode':'GUIDED'})
        # An actual map click fills the declared odom target; UI executes it.
        box=page.locator('#field').bounding_box()
        b=f.owned.profile.safety
        page.locator('#field').click(position={'x':box['width']/2+box['width']*(1.2-(b.min_x_m+b.max_x_m)/2)/(b.max_x_m-b.min_x_m),
            'y':240-480*(.4-(b.min_y_m+b.max_y_m)/2)/(b.max_y_m-b.min_y_m)})
        if f.kind=='copter':page.locator('#parameters [name="z_m"]').fill('1.5');page.locator('#parameters [name="z_m"]').press('Tab')
        perform('Goto',keep_form=True,timeout=60)
        perform('ReturnHome',timeout=100)
        if f.kind=='rover':perform('Disarm')
    else:
        perform('Takeoff',{'height_m':50},timeout=140)
        before=len(f.writer);perform('Disarm',expected='REJECTED')
        if len(f.writer)!=before:raise AssertionError('airborne Plane Disarm reached Writer')
        box=page.locator('#field').bounding_box();page.locator('#field').click(position={'x':box['width']/2,'y':80})
        page.locator('#parameters [name="altitude_amsl_m"]').fill('634');page.locator('#parameters [name="altitude_amsl_m"]').press('Tab')
        a=perform('SetGuidedTarget',keep_form=True,timeout=40)
        if a['result']['physical_arrival_claim']:raise AssertionError('map native target claimed arrival')
        from tests.simulation.mission_physics import target_reference,target_motion
        reference=target_reference(f,a)
        result['manual_target_truth']=wait(page,f,lambda:target_motion(f,reference),91)
        for name in ('Loiter','RTL'):perform(name,timeout=40)
        perform('AutoLand',timeout=430)
    t=f.truth()
    if f.kind=='plane' and (t.z_m-f.initial.z_m>.25 or f.oracle.recent_speed_mps()>=1):
        raise AssertionError('manual Plane AUTOLAND lacked physical touchdown/rollout')
    if f.kind=='copter' and (t.z_m-f.initial.z_m>.2 or f.oracle.recent_speed_mps()>.15):
        raise AssertionError('manual Copter ReturnHome lacked physical landing')
    result['manual_final_truth']=dict(position=[t.x_m,t.y_m,t.z_m],speed_mps=f.oracle.recent_speed_mps())
    # The displayed result must follow the server, not remain the submit-time
    # VALIDATING response after the actual operation has already completed.
    wait(page,f,lambda:json.loads(page.locator('#log').inner_text()).get('state')=='SUCCEEDED',3)
    page.screenshot(path=str(f.path/'manual-control.png'),full_page=True,mask=[page.locator('#token')])
    return result


def exercise(f,result):
    from playwright.sync_api import sync_playwright
    result['browser']='real Chrome headless';errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            page=browser.new_page(viewport={'width':1680,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
            create_mission(page,f,result);manual(page,f,result)
            if errors:raise AssertionError('Chrome JavaScript errors: '+str(errors))
            result['javascript_errors']=errors
        finally:browser.close()

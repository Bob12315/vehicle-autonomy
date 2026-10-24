"""Actual Chrome UI operation, not direct fetch/evaluate as a UI substitute."""
import time


def exercise(base,token,lab,oracle,path,sample,actions):
    from playwright.sync_api import sync_playwright
    report={'passed':False,'browser':'Chrome headless','actions':[]}
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            page=browser.new_page(viewport={'width':1360,'height':1000});errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base);page.locator('#token').fill(token);page.locator('#connect').click()
            page.locator('#action option').first.wait_for(state='attached')
            def perform(name,parameters=None):
                existing={r['id'] for r in lab.runtime.views()}
                page.locator('#action').select_option(name+'@1.0.0')
                for key,value in (parameters or {}).items():
                    control=page.locator(f'#parameters [name="{key}"]')
                    if control.evaluate('(e)=>e.tagName')=='SELECT':
                        import json
                        control.select_option(json.dumps(value))
                    else:control.fill(str(value))
                page.locator('#send').check();page.locator('#run').click()
                end=time.monotonic()+15
                while time.monotonic()<end:
                    sample();new=[r for r in lab.runtime.views() if r['id'] not in existing]
                    if new:break
                    page.wait_for_timeout(100)
                else:raise TimeoutError('UI submit did not create an Action')
                if len(new)!=1:raise AssertionError('UI duplicated Action submission')
                identifier=new[0]['id'];continuous=name=='Drive';expected='RUNNING' if continuous else 'SUCCEEDED'
                end=time.monotonic()+15
                while time.monotonic()<end:
                    value=lab.runtime.view(identifier);sample()
                    if value['state']==expected:break
                    if value['state'] in ('FAILED','REJECTED','TIMED_OUT','UNKNOWN'):raise AssertionError('UI Action '+name+' '+value['state'])
                    page.wait_for_timeout(100)
                else:raise TimeoutError('UI Action '+name)
                page.locator('.instance').filter(has_text=identifier).get_by_text(expected,exact=False).first.wait_for()
                if page.locator('#send').is_checked():raise AssertionError('UI retained SEND across submissions')
                return identifier
            for name,p in [('SetMode',{'mode':'GUIDED'}),('Arm',{})]:
                identifier=perform(name,p);report['actions'].append(identifier)
            start=sample();identifier=perform('Drive',{'speed_mps':.3});report['actions'].append(identifier)
            until=time.monotonic()+2
            while time.monotonic()<until:sample();page.wait_for_timeout(100)
            finish=sample()
            import math
            distance=math.hypot(finish.x_m-start.x_m,finish.y_m-start.y_m)
            if distance<.15:raise AssertionError('real browser Drive did not move in Gazebo')
            card=page.locator('.instance').filter(has_text=identifier)
            card.get_by_role('button',name='取消 / 请求安全退出').click()
            end=time.monotonic()+15
            while time.monotonic()<end:
                sample();value=lab.runtime.view(identifier)
                if value['state']=='CANCELLED':break
                if value['state']=='UNKNOWN':raise AssertionError('UI cancel stop unconfirmed')
                page.wait_for_timeout(100)
            else:raise TimeoutError('UI cancellation')
            if (oracle.recent_speed_mps() or 0)>.1:raise AssertionError('UI cancel real Rover stop speed')
            card.get_by_text('CANCELLED',exact=False).first.wait_for()
            if errors:raise AssertionError('browser JavaScript error')
            page.screenshot(path=str(path/'action-lab.png'),full_page=True,mask=[page.locator('#token')])
            for action_id in report['actions']:
                r=lab.runtime.view(action_id)
                actions.append({'name':r['name'],'id':r['id'],'source':'real Chrome UI','final':r})
            report.update(passed=True,physical_distance_m=distance,post_cancel_speed_mps=oracle.recent_speed_mps(),javascript_errors=errors)
        finally:browser.close()
    return report

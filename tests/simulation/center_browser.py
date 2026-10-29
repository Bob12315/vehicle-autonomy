"""Actual Chrome clicks against the real Simulation Manager, no mocked backend.

Runs world-only acceptance by default. A world lifecycle browser PASS does not
claim SITL motion or framework L5 qualification.
"""
import argparse
import json
from pathlib import Path
import time
from urllib.request import Request,urlopen

from tests.browser_auth import login


def run(base,token,directory,*,scene_id='R01'):
    from playwright.sync_api import sync_playwright,expect
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    errors=[];responses=[];identifier=None
    result=dict(status='FAIL',scene_id=scene_id,vehicle='none',scope='real Chrome + authenticated HTTP + Gazebo world lifecycle; no SITL movement',checks={})
    def read(path):
        with urlopen(Request(base+path,headers={'Authorization':'Bearer '+token}),timeout=10) as response:
            return json.load(response)['result']
    def current():
        return next((s for s in read('/api/simulation/sessions') if s['id']==identifier),None)
    def await_state(predicate,seconds=90):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            s=current()
            if s and s['state']=='FAILED':raise AssertionError('Simulation Manager failed: '+str(s.get('error')))
            if s and predicate(s):return s
            page.wait_for_timeout(150)
        raise TimeoutError('simulation UI lifecycle: '+page.locator('#notice').inner_text())
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            page=browser.new_page(viewport={'width':1680,'height':1080},accept_downloads=True)
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('response',lambda response:responses.append(dict(url=response.url.removeprefix(base),status=response.status)) if '/api/simulation/' in response.url else None)
            login(page,base,token,'/simulation')
            catalog_count=len(read('/api/simulation/catalog'));assert catalog_count>=24
            result['catalog_count']=catalog_count
            expect(page.locator('.scene-card')).to_have_count(catalog_count,timeout=15000)
            page.locator('#search').fill(scene_id)
            page.locator('[data-scene="'+scene_id+'"]').click()
            expect(page.locator('#detail-id')).to_have_text(scene_id)
            expect(page.locator('.preview-caption')).to_contain_text('非实时')
            page.screenshot(path=str(directory/'01-scene-library.png'),full_page=True)
            result['checks']['search_detail_and_static_label']='PASS'
            page.locator('#config-vehicle').select_option('none')
            page.locator('#seed').fill('20261029')
            page.locator('#parameter-obstacle_count').fill('10')
            before={s['id'] for s in read('/api/simulation/sessions')}
            page.locator('#create-session').click()
            expect(page.locator('#sessions-view')).to_be_visible(timeout=10000)
            added=[s for s in read('/api/simulation/sessions') if s['id'] not in before]
            assert len(added)==1,added
            identifier=added[0]['id'];result['session_id']=identifier
            page.locator('[data-operation=start]').click()
            active=await_state(lambda s:s['state'] in ('READY','RUNNING'))
            expect(page.locator('#session-state')).to_contain_text('就绪' if active['state']=='READY' else '运行',timeout=10000)
            await_state(lambda s:s['levels']['L2']=='PASS',30)
            result['checks']['real_gazebo_start']='PASS'
            page.locator('[data-operation=pause]').click()
            await_state(lambda s:s.get('paused') is True,20)
            result['checks']['pause']='PASS'
            page.locator('[data-operation=resume]').click()
            await_state(lambda s:s.get('paused') is False,20)
            result['checks']['resume']='PASS'
            page.locator('[data-operation=reset]').click()
            expect(page.locator('#notice')).to_contain_text('操作已提交',timeout=10000)
            result['checks']['reset_request']='PASS'
            page.screenshot(path=str(directory/'02-running.png'),full_page=True)
            page.locator('#session-logs').click()
            expect(page.locator('#session-log-output')).not_to_have_text('尚未读取。',timeout=10000)
            page.locator('#session-report').click()
            expect(page.locator('#report-levels div')).to_have_count(6,timeout=10000)
            with page.expect_download() as download:page.locator('#export-report').click()
            download.value.save_as(str(directory/'report-export.json'))
            exported=json.loads((directory/'report-export.json').read_text())
            assert identifier in json.dumps(exported)
            result['checks']['report_log_and_export']='PASS'
            page.screenshot(path=str(directory/'03-report.png'),full_page=True)
            page.locator('[data-tab=sessions]').click()
            page.locator('[data-operation=stop]').click()
            stopped=await_state(lambda s:s['state'] in ('FINISHED','CANCELLED'),30)
            result['checks']['stop_and_cleanup']='PASS'
            result['final_session']=stopped
            page.goto(base+'/console');page.locator('nav a[href="/simulation"]').click()
            expect(page.locator('h1')).to_have_text('仿真中心')
            assert '/login' not in page.url
            result['checks']['shared_login_navigation']='PASS'
            expect(page.locator('#scene-count')).to_contain_text(str(catalog_count),timeout=10000)
            page.screenshot(path=str(directory/'04-completed-library.png'),full_page=True)
            assert not errors,errors
            assert not [r for r in responses if r['status']>=400],responses
            result['javascript_errors']=errors
            result['status']='PASS'
            return result
        except BaseException as exc:
            result['error']=str(exc)
            if 'page' in locals():
                page.screenshot(path=str(directory/'failure.png'),full_page=True)
                (directory/'failure.txt').write_text(page.locator('body').inner_text())
            raise
        finally:
            if identifier and result['status']!='PASS':
                try:
                    if current()['state'] not in ('FINISHED','FAILED','CANCELLED'):
                        page.goto(base+'/simulation')
                        page.locator('[data-tab=sessions]').click()
                        page.locator('[data-session="'+identifier+'"]').click(timeout=10000)
                        page.locator('[data-operation=stop]').click(timeout=5000)
                        await_state(lambda s:s['state'] in ('FINISHED','CANCELLED'),30)
                except Exception as cleanup:
                    result['cleanup_error']=str(cleanup)
            result['javascript_errors']=errors;result['http_responses']=responses
            (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            browser.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',required=True)
    parser.add_argument('--token-file',required=True,type=Path)
    parser.add_argument('--run-dir',required=True,type=Path)
    parser.add_argument('--scene-id',default='R01')
    args=parser.parse_args()
    result=run(args.base,args.token_file.read_text().strip(),args.run_dir,scene_id=args.scene_id)
    print(json.dumps(dict(status=result['status'],session_id=result['session_id'],checks=result['checks']),ensure_ascii=False))


if __name__=='__main__':main()

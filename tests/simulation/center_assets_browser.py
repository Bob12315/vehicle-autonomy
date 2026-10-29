"""Chrome asset lifecycle on a small locked official world, no Gazebo process."""
import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from tests.browser_auth import login


def run(base,token,directory,asset_id='gazebo-air-pressure'):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    result=dict(status='FAIL',asset_id=asset_id,checks={});errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        page=browser.new_page(viewport={'width':1680,'height':1080})
        page.on('pageerror',lambda error:errors.append(str(error)))
        try:
            login(page,base,token,'/simulation')
            expect(page.locator('.scene-card').first).to_be_visible(timeout=15000)
            page.locator('#search').fill('U_'+asset_id)
            page.locator('[data-scene="U_'+asset_id+'"]').click()
            for op,expected_status in (('uninstall','MISSING'),('install','INSTALLED')):
                page.locator('#asset-'+op).click()
                expect(page.locator('#notice')).to_contain_text('资源任务：',timeout=60000)
                page.locator('#asset-status').click()
                expect(page.locator('#asset-output')).to_contain_text('"state": "SUCCEEDED"',timeout=10000)
                expect(page.locator('#asset-output')).to_contain_text(expected_status)
                result['checks'][op]='PASS'
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(directory/(op+'.png')),full_page=True)
            assert not errors,errors
            result['status']='PASS'
            return result
        except Exception as exc:
            result['error']=str(exc);page.screenshot(path=str(directory/'failure.png'),full_page=True)
            raise
        finally:
            result['javascript_errors']=errors
            (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            browser.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',required=True);p.add_argument('--token-file',required=True,type=Path)
    p.add_argument('--run-dir',required=True,type=Path);p.add_argument('--asset-id',default='gazebo-air-pressure')
    a=p.parse_args();print(json.dumps(run(a.base,a.token_file.read_text().strip(),a.run_dir,a.asset_id)))


if __name__=='__main__':main()

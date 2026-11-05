"""Real CUADC camera/PT -> authenticated source selection, without SEND."""
import argparse,json,os,secrets,signal,time,traceback
from contextlib import suppress
from pathlib import Path
from threading import Thread

from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer


def run(directory):
    from playwright.sync_api import sync_playwright,expect,TimeoutError as BrowserTimeout
    from tests.browser_auth import login
    directory=Path(directory).resolve();directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    app=MissionControl({},directory/'application',simulation_allow_send=False)
    token=secrets.token_urlsafe(32)
    server=MissionControlServer(('127.0.0.1',0),app,token,directory/'http.jsonl')
    thread=Thread(target=server.serve_forever,kwargs={'poll_interval':.1});thread.start()
    base='http://127.0.0.1:'+str(server.server_address[1]);report=dict(status='FAIL',checks={});paused=None;identifier=None
    def wait(predicate,timeout=45):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=predicate()
            if value:return value
            time.sleep(.1)
        raise TimeoutError('YOLO preview acceptance deadline')
    try:
        manager=app.simulation_manager
        identifier=manager.create(dict(scene_id='CUADC2026',vehicles=[dict(kind='copter_rescue')],parameters={}))['id']
        manager.start(identifier);manager.wait_ready(identifier,150)
        child=next(iter(manager.owners[identifier].vehicles.values()));driver=app.drivers[child.target]
        raw=child.camera_sources['gimbal-camera'];processed=child.camera_sources['yolo']
        wait(lambda:processed.health()['online'])
        catalog=app.cameras.catalog(child.target);assert len(catalog)==3,catalog
        yolo=next(c for c in catalog if c['kind']=='yolo');original=next(c for c in catalog if c['kind']=='gazebo')
        stable=next(c for c in catalog if c['kind']=='stabilized')
        assert yolo['binding']==original['binding'];report['catalog']=catalog
        frames=[]
        for _ in range(6):
            previous=frames[-1]['sequence'] if frames else -1
            def next_frame():
                if not processed.health()['online']:return None
                metadata,jpeg=processed.packet()
                if metadata['sequence']<=previous:return None
                (directory/'annotated-native.jpg').write_bytes(jpeg)
                return metadata
            frames.append(wait(next_frame,10))
        report['frames']=frames
        assert all(f['received_ns']==f['original_received_ns'] for f in frames)
        assert all(f['image_domain']=='virtual_nadir' and f['rectification']['valid'] for f in frames)
        assert len({f['rectification']['reference_id'] for f in frames})==1
        report['stabilization']=driver.info()['rescue_perception']['stabilization']
        report['checks']['actual PT, original capture provenance, advancing annotated frames']='PASS'
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(viewport={'width':1480,'height':1080});errors=[]
                snapshot_codes=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('response',lambda response:snapshot_codes.append(response.status) if '/snapshot?' in response.url else None)
                login(page,base,token,'/control#'+child.target)
                expect(page.locator('label[for="camera-source"]')).to_have_text('画面来源')
                page.wait_for_function("() => document.querySelector('#camera-source').options.length===4")
                page.locator('#camera-source').select_option(original['camera_id'])
                expect(page.locator('#camera-video')).to_be_visible(timeout=10000)
                page.wait_for_function("() => document.querySelector('#camera-video').naturalWidth===640")
                page.locator('#camera-source').select_option(stable['camera_id'])
                expect(page.locator('#camera-video')).to_be_visible(timeout=10000)
                page.screenshot(path=str(directory/'vehicle-control-stabilized.png'),full_page=True)
                page.locator('#camera-source').select_option(yolo['camera_id'])
                expect(page.locator('#camera-video')).to_be_visible(timeout=10000)
                page.wait_for_function("() => document.querySelector('#camera-video').src.includes('/"+yolo['camera_id']+"/stream')")
                page.screenshot(path=str(directory/'vehicle-control-yolo.png'),full_page=True)
                for attempt in range(5):
                    expect(page.locator('#camera-snapshot')).to_be_enabled(timeout=10000)
                    before=len(snapshot_codes)
                    try:
                        with page.expect_download(timeout=5000) as download:page.locator('#camera-snapshot').click(timeout=5000)
                    except BrowserTimeout:
                        # Catalog health is not a snapshot lease. A sync fault
                        # racing the click correctly returns 409, never an old
                        # JPEG. Retry only that observed freshness rejection.
                        if snapshot_codes[before:]!=[409]:raise
                    else:
                        download.value.save_as(str(directory/'browser-yolo-snapshot.jpg'));break
                else:raise AssertionError('no fresh annotated snapshot after bounded retries')
                report['snapshot_http_codes']=list(snapshot_codes)
                report['checks']['browser raw/stabilized/YOLO selection and annotated snapshot']='PASS'
                # Stop only this original owner's capture process, never the simulator.
                paused=raw.process.pid;os.kill(paused,signal.SIGSTOP)
                wait(lambda:not processed.health()['online'],5)
                expect(page.locator('#camera-video')).not_to_be_visible(timeout=5000)
                expect(page.locator('#camera-snapshot')).to_be_disabled()
                response=page.request.get(base+'/api/cameras/'+yolo['camera_id']+'/snapshot?target='+child.target)
                assert response.status==409,response.status
                os.kill(paused,signal.SIGCONT);paused=None
                wait(lambda:processed.health()['online'],15)
                expect(page.locator('#camera-video')).to_be_visible(timeout=10000)
                report['checks']['capture outage clears view, refuses snapshots, fresh recovery']='PASS'
                assert not errors,errors;report['browser_errors']=errors
            finally:browser.close()
        info=driver.info();assert not info['system_send'] and not info['action_send']
        assert info['writer']['attempts']==0 and not info['lease_active'],info
        report['writer']=info['writer'];report['checks']['read-only, no SEND/Lease/vehicle writes']='PASS'
        app.close()
        record=manager.records[identifier]
        report['cleanup']=record
        assert record['cleanup']=='COMPLETE',record
        assert not app.cameras.catalog(child.target)
        with suppress(ProcessLookupError):
            os.kill(raw.process.pid,0);raise AssertionError('original camera still alive')
        report['status']='PASS'
    except Exception:
        report['error']=traceback.format_exc();print(report['error'],flush=True)
    finally:
        if paused is not None:os.kill(paused,signal.SIGCONT)
        server.shutdown();thread.join(5);server.server_close()
        try:app.close()
        except Exception as exc:report.update(status='FAIL',cleanup_error=str(exc))
        (directory/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps({k:report.get(k) for k in ('status','checks','error','cleanup_error')},ensure_ascii=False),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);args=parser.parse_args()
    raise SystemExit(0 if run(args.directory)['status']=='PASS' else 1)

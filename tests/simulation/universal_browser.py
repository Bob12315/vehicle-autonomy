"""Actual Chrome + native Manager acceptance for universal World composition.

No routes, drivers, telemetry or process stages are mocked. This harness owns a
fresh loopback application and data directory. Motion, when explicitly enabled,
is clicked through the existing /control UI and original safety chain.
"""
from __future__ import annotations
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from threading import Thread
import time
from urllib.request import Request,urlopen
from uuid import uuid4

from tests.browser_auth import login
from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer
from vehicle_autonomy.app.web.server import load_token

TERMINAL={'FINISHED','FAILED','CANCELLED'}


def run(directory,*,scene_id='R01',next_scene_id='R04',kinds=('rover','copter'),allow_send=False):
    from playwright.sync_api import sync_playwright,expect
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    token_path=directory/'web-token.private';token=load_token(token_path)
    server_log=(directory/'application-server.log').open('w')
    command=[sys.executable,'-m','tests.simulation.universal_server',str(directory)]
    if allow_send:command.append('--allow-send')
    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=server_log,stderr=subprocess.STDOUT)
    deadline=time.monotonic()+15
    while not (directory/'server-ready.json').exists():
        if process.poll() is not None or time.monotonic()>deadline:
            process.terminate();process.wait(timeout=20);server_log.close()
            raise RuntimeError('dedicated native web server did not initialize')
        time.sleep(.05)
    base='http://127.0.0.1:'+str(json.loads((directory/'server-ready.json').read_text())['port'])
    result=dict(status='FAIL',scene_id=scene_id,next_scene_id=next_scene_id,kinds=list(kinds),
                scope='real Chrome + native Gazebo/SITL + shared browser auth',checks={},javascript_errors=[])
    owned=[];page=None;control=None

    def api(path,payload=None):
        headers={'Authorization':'Bearer '+token};data=None
        if payload is not None:
            data=json.dumps(payload).encode();headers.update({'Content-Type':'application/json','X-VAF-CSRF':token,'X-VAF-Request-ID':uuid4().hex})
        with urlopen(Request(base+path,data,headers),timeout=20) as reply:value=json.load(reply)
        if not value.get('ok'):raise AssertionError(value)
        return value['result']

    def wait(predicate,seconds=150):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            found=predicate()
            if found:return found
            page.wait_for_timeout(200)
        raise TimeoutError('native browser condition; notice='+page.locator('#notice').inner_text())

    def report(identifier):return api('/api/simulation/report',{'id':identifier})
    def ready(identifier):
        item=report(identifier)
        if item['state']=='FAILED':raise AssertionError(item.get('error'))
        return item if item['state'] in ('READY','RUNNING') and all(v.get('state') in ('READY','RUNNING') for v in item.get('vehicles',[])) else None

    def view(target):return next(v for v in api('/api/control/state')['vehicles'] if v['target']==target)
    def position(target):return view(target)['world']['vehicle']['reported_pose']['value']['position']
    def armed(target):return view(target)['world']['vehicle']['operation']['armed']

    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            context=browser.new_context(viewport={'width':1680,'height':1080},accept_downloads=True)
            page=context.new_page();page.on('pageerror',lambda error:result['javascript_errors'].append(str(error)))
            login(page,base,token,'/simulation')
            expect(page.locator('.scene-card')).to_have_count(len(api('/api/simulation/catalog')),timeout=15000)
            page.locator('#search').fill(scene_id);page.locator('[data-scene="'+scene_id+'"]').click()
            page.locator('#config-vehicle').select_option(kinds[0])
            expect(page.locator('#vehicle-definition-output')).to_contain_text('fingerprint')
            if page.locator('#parameter-obstacle_count').count():page.locator('#parameter-obstacle_count').fill('0')
            for kind in kinds[1:]:
                page.locator('#add-config-vehicle').click()
                page.locator('#vehicle-instances fieldset').last.locator('select').first.select_option(kind)
            before={s['id'] for s in api('/api/simulation/sessions')}
            page.locator('#create-session').click();expect(page.locator('#sessions-view')).to_be_visible(timeout=10000)
            created=wait(lambda:next((s for s in api('/api/simulation/sessions') if s['id'] not in before),None),15)
            identifier=created['id'];owned.append(identifier);result['initial_id']=identifier
            page.locator('[data-operation=start]').click();initial=wait(lambda:ready(identifier))
            vehicles=initial['vehicles'];assert len(vehicles)==len(kinds),(vehicles,kinds)
            for key in ('id','target','system_id','entity_name'):
                assert len({v[key] for v in vehicles})==len(vehicles),(key,vehicles)
            numeric_ports=[port for v in vehicles for port in v.get('ports',{}).values() if type(port) is int]
            assert len(numeric_ports)==len(set(numeric_ports)),vehicles
            profile_by_slot={v['slot_id']:(v['kind'],v['definition_version'],v['fingerprint']) for v in vehicles}
            expect(page.locator('#session-vehicles [data-vehicle-id]')).to_have_count(len(vehicles),timeout=10000)
            for vehicle in vehicles:
                page.locator('#current-vehicle').select_option(vehicle['id'])
                expect(page.locator('#current-vehicle-facts')).to_contain_text(str(vehicle['system_id']))
                expect(page.locator('#control-link')).to_have_attribute('href','/control#'+vehicle['target'])
            page.screenshot(path=str(directory/'01-multiple-vehicles.png'),full_page=True)
            result['checks']['same_world_independent_identity_and_profiles']='PASS'
            page.locator('#query-test').click()
            queried=wait(lambda:next((t for t in report(identifier)['tests'] if t.get('action',{}).get('state')=='SUCCEEDED'),None),15)
            assert queried['action']['target']==vehicles[-1]['target'],queried
            result['checks']['selected_vehicle_read_only_query']='PASS'

            controlled=next((v for v in vehicles if v['kind'] in ('rover','copter')),vehicles[0])
            page.locator('#current-vehicle').select_option(controlled['id'])
            control=context.new_page();control.on('pageerror',lambda error:result['javascript_errors'].append(str(error)))
            control.goto(base+page.locator('#control-link').get_attribute('href'))
            expect(control.locator('#target')).to_have_value(controlled['target'],timeout=10000)
            assert '/login' not in control.url
            result['checks']['shared_login_and_selected_control_target']='PASS'
            if allow_send and controlled['kind'] in ('rover','copter'):
                # Fresh signed health precedes AP's own arming/EKF warmup.
                # Preserve the established native 45-second acceptance warmup.
                control.wait_for_timeout(45000)
                expect(control.locator('#acquire-control')).to_be_enabled(timeout=70000)
                control.locator('#acquire-control').click()
                expect(control.locator('#set-mode')).to_be_enabled(timeout=15000)
                control.locator('#mode').select_option('GUIDED');control.locator('#set-mode').click()
                expect(control.locator('[data-action=Arm]')).to_be_enabled(timeout=15000)
                control.locator('[data-action=Arm]').click();wait(lambda:armed(controlled['target']),25)
                start=position(controlled['target']);others={v['target']:position(v['target']) for v in vehicles if v['id']!=controlled['id']}
                if controlled['kind']=='rover':
                    expect(control.locator('[data-key=w]:visible')).to_be_enabled(timeout=10000)
                    button=control.locator('[data-key=w]:visible');button.scroll_into_view_if_needed();box=button.bounding_box()
                    control.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);control.mouse.down();control.wait_for_timeout(3500);control.mouse.up()
                    wait(lambda:math.dist(list(start.values()),list(position(controlled['target']).values()))>.15,15)
                    expect(control.locator('[data-action=Disarm]')).to_be_enabled(timeout=20000)
                    control.locator('[data-action=Disarm]').click();wait(lambda:not armed(controlled['target']),20)
                else:
                    control.locator('#takeoff-height').fill('1.5');control.locator('#takeoff').click()
                    wait(lambda:position(controlled['target'])['z']>1,35)
                    expect(control.locator('[data-action=Land]')).to_be_enabled(timeout=15000);control.locator('[data-action=Land]').click()
                    wait(lambda:not armed(controlled['target']),45)
                # Physical disarm can precede the original Action's signed
                # completion/exit barrier. Do not cancel it by releasing early.
                final_name='Disarm' if controlled['kind']=='rover' else 'Land'
                wait(lambda:next((a for a in api('/api/instances') if a['target']==controlled['target'] and a['name']==final_name and a['state']=='SUCCEEDED' and (a.get('safety') or {}).get('release_safe')),None),45)
                for target,start_other in others.items():
                    assert not armed(target),target
                    assert math.dist(list(start_other.values()),list(position(target).values()))<.5,(target,start_other,position(target))
                result['checks']['original_control_ui_motion_and_other_vehicle_isolation']='PASS'
                control.screenshot(path=str(directory/'02-original-control.png'),full_page=True)
                control.locator('#release-control').click()
                wait(lambda:not api('/api/control/state')['operator_control'].get(controlled['target'],{}).get('holder'),20)
            else:result['checks']['original_control_ui_motion_and_other_vehicle_isolation']='NOT_TESTED'
            control.close();control=None

            # Single-vehicle stop must preserve the same Gazebo world and peer.
            if len(vehicles)>1:
                removed=vehicles[-1];peer=vehicles[0]
                page.locator('#current-vehicle').select_option(removed['id']);page.locator('#remove-vehicle').click()
                def removed_live():
                    item=report(identifier);operation=item.get('operation',{})
                    if operation.get('state')=='FAILED':raise AssertionError(operation)
                    retired=any(v['id']==removed['id'] for v in item.get('retired_vehicles',[]))
                    return item if operation.get('state')=='SUCCEEDED' and retired and all(v['id']!=removed['id'] for v in item['vehicles']) else None
                after_remove=wait(removed_live,50)
                assert after_remove['state'] in ('READY','RUNNING'),after_remove
                assert view(peer['target'])['connected'],view(peer['target'])
                profile_by_slot.pop(removed['slot_id'])
                result['checks']['single_vehicle_remove_preserves_world_and_peer']='PASS'
                page.locator('#add-vehicle-panel > summary').click()
                page.locator('#add-vehicle-kind').select_option(removed['kind'])
                page.locator('#add-live-vehicle').click()
                def added_live():
                    item=report(identifier);operation=item.get('operation',{})
                    if operation.get('state')=='FAILED':raise AssertionError(operation)
                    return item if operation.get('state')=='SUCCEEDED' and len(item['vehicles'])==len(kinds) and all(v.get('state') in ('READY','RUNNING') for v in item['vehicles']) else None
                after_add=wait(added_live,160)
                additions=[v for v in after_add['vehicles'] if v['id'] not in {old['id'] for old in vehicles}]
                assert len(additions)==1,after_add['vehicles']
                added=additions[0]
                assert added['id']!=removed['id'] and added['target']!=removed['target'],added
                assert added['fingerprint']==removed['fingerprint'] and added['definition_version']==removed['definition_version'],added
                assert view(peer['target'])['connected'] and not armed(peer['target'])
                profile_by_slot={v['slot_id']:(v['kind'],v['definition_version'],v['fingerprint']) for v in after_add['vehicles']}
                result['added_vehicle']={k:added[k] for k in ('id','target','kind','slot_id','fingerprint','definition_version')}
                vehicles=after_add['vehicles']
                result['checks']['live_add_independent_instance_same_fixed_profile']='PASS'

            page.locator('#switch-panel > summary').click();page.locator('#switch-scene').select_option(next_scene_id)
            if page.locator('#switch-parameter-obstacle_count').count():page.locator('#switch-parameter-obstacle_count').fill('0')
            page.locator('#switch-world').click()
            def switched():
                previous=report(identifier);operation=previous.get('switch',{})
                if operation.get('state')=='FAILED':raise AssertionError(operation)
                next_id=operation.get('new_session_id')
                if next_id and next_id not in owned:owned.append(next_id)
                return ready(next_id) if next_id and operation.get('state')=='SUCCEEDED' else None
            current=wait(switched,210);new_id=current['id'];result['replacement_id']=new_id
            assert new_id!=identifier and current['scene_id']==next_scene_id,current
            assert {v['slot_id']:(v['kind'],v['definition_version'],v['fingerprint']) for v in current['vehicles']}==profile_by_slot
            assert not ({v['target'] for v in current['vehicles']}&{v['target'] for v in vehicles})
            for vehicle in current['vehicles']:
                info=view(vehicle['target']);assert not info['system_send'] and not info['action_send'],info
            expect(page.locator('#session-title')).to_contain_text(next_scene_id,timeout=15000)
            expect(page.locator('#switch-progress')).to_contain_text('SUCCEEDED',timeout=10000)
            page.screenshot(path=str(directory/'03-switched-world-new-epoch.png'),full_page=True)
            result['checks']['controlled_world_switch_preserves_profiles_new_epoch_send_off']='PASS'
            page.locator('#session-logs').click();expect(page.locator('#session-log-output')).not_to_have_text('尚未读取。',timeout=10000)
            page.locator('#session-report').click();expect(page.locator('#report-levels div')).to_have_count(6,timeout=10000)
            with page.expect_download() as download:page.locator('#export-report').click()
            download.value.save_as(str(directory/'exported-report.json'))
            assert new_id in (directory/'exported-report.json').read_text()
            result['checks']['real_logs_and_report_download']='PASS'
            page.locator('[data-tab=sessions]').click();page.locator('[data-operation=stop]').click()
            final=wait(lambda:report(new_id) if report(new_id)['state'] in TERMINAL else None,60)
            assert final['state']=='FINISHED' and final['cleanup']=='COMPLETE',final
            result['final_report']=final;result['old_report']=report(identifier)
            assert not result['javascript_errors'],result['javascript_errors']
            result['checks']['final_cleanup']='PASS';result['status']='PASS'
        except BaseException as exc:
            result['error']=type(exc).__name__+': '+str(exc)
            if page:
                page.screenshot(path=str(directory/'failure.png'),full_page=True)
                (directory/'failure.txt').write_text(page.locator('body').inner_text())
        finally:
            if control:
                try:control.locator('#release-control').click(timeout=5000)
                except Exception:pass
            browser.close()
            for identifier in reversed(owned):
                try:
                    if report(identifier)['state'] not in TERMINAL:api('/api/simulation/stop',{'id':identifier})
                except Exception as exc:result.setdefault('cleanup_errors',[]).append(str(exc))
            try:
                process.terminate()
                process.wait(timeout=180)
                if process.returncode:raise RuntimeError('dedicated web server cleanup exit '+str(process.returncode))
            except Exception as exc:
                result.setdefault('cleanup_errors',[]).append(str(exc));result['status']='FAIL'
                if process.poll() is None:process.kill();process.wait(timeout=10)
            finally:server_log.close()
            token_path.unlink(missing_ok=True)
            (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


def main():
    from tests.simulation.launch import install_signal_cleanup
    install_signal_cleanup()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--scene-id',default='R01');parser.add_argument('--next-scene-id',default='R04')
    parser.add_argument('--kind',action='append',choices=('rover','copter','plane'))
    parser.add_argument('--allow-send',action='store_true')
    args=parser.parse_args()
    value=run(args.run_dir,scene_id=args.scene_id,next_scene_id=args.next_scene_id,kinds=tuple(args.kind or ['rover','copter']),allow_send=args.allow_send)
    print(json.dumps({k:value.get(k) for k in ('status','checks','error','cleanup_errors')},ensure_ascii=False))
    return int(value['status']!='PASS')


if __name__=='__main__':raise SystemExit(main())

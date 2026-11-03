"""Real Gazebo Image -> managed capture -> authenticated HTTP/browser acceptance."""
import argparse
from collections import deque
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import signal
import statistics
import threading
import time
import traceback

from tests.simulation.control_binding_native import Native, TERMINAL
from tests.simulation.oracle import GazeboTruthOracle


class VideoReader:
    def __init__(self,n,target,camera,phase,*,slow=False):
        self.n=n;self.target=target;self.camera=camera;self.phase=phase;self.slow=slow
        self.stop=threading.Event();self.records=[];self.error=None
        self.conn=http.client.HTTPConnection('127.0.0.1',n.server.server_address[1],timeout=5)
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        try:
            self.conn.request('GET',f'/api/cameras/{self.camera}/stream?target={self.target}',headers={'Authorization':'Bearer '+self.n.token})
            response=self.conn.getresponse();assert response.status==200,response.status
            while not self.stop.is_set():
                line=response.readline()
                if not line:break
                assert line==b'--vaf-camera\r\n',line[:100]
                fields={}
                while True:
                    line=response.readline()
                    if line==b'\r\n':break
                    if not line:raise EOFError('partial MJPEG headers')
                    key,value=line.decode().strip().split(': ',1);fields[key]=value
                jpeg=response.read(int(fields['Content-Length']));received=time.monotonic_ns();assert response.read(2)==b'\r\n'
                assert fields['X-Camera-ID']==self.camera and fields['X-Camera-Target']==self.target
                assert jpeg.startswith(b'\xff\xd8') and len(jpeg)<=1_000_000
                row=dict(phase=self.phase,camera_id=self.camera,target=self.target,epoch=fields['X-Camera-Epoch'],
                    sequence=int(fields['X-Frame-Sequence']),captured_ns=int(fields['X-Capture-Ns']),capture_clock=fields['X-Capture-Clock'],
                    source_received_ns=int(fields['X-Source-Received-Ns']),web_sent_ns=int(fields['X-Web-Sent-Ns']),
                    web_received_ns=received,bytes=len(jpeg),sha256=hashlib.sha256(jpeg).hexdigest())
                row.update(source_to_web_ms=(received-row['source_received_ns'])/1e6,web_transfer_ms=(received-row['web_sent_ns'])/1e6)
                self.records.append(row)
                with self.n.video_lock:self.n.video_log.write(json.dumps(row)+'\n');self.n.video_log.flush()
                if len(self.records)%10==1:
                    (self.n.path/'frames'/f'{self.phase}-{self.camera}-{row["sequence"]}.jpg').write_bytes(jpeg)
                if self.slow:self.stop.wait(2)
        except Exception as exc:
            if not self.stop.is_set():self.error=type(exc).__name__+': '+str(exc)
        finally:self.conn.close()
    def close(self):
        self.stop.set();self.conn.close();self.thread.join(6)
        assert not self.thread.is_alive(),'video client shutdown unconfirmed'
    def summary(self):
        rows=self.records
        assert len(rows)>=3,(self.phase,self.error,len(rows))
        times=[r['web_received_ns'] for r in rows];seq=[r['sequence'] for r in rows]
        assert all(b>a for a,b in zip(seq,seq[1:]));assert all(b['captured_ns']>a['captured_ns'] for a,b in zip(rows,rows[1:]))
        latency=sorted(r['source_to_web_ms'] for r in rows)
        return dict(phase=self.phase,target=self.target,camera_id=self.camera,frames=len(rows),
            fps=(len(rows)-1)*1e9/(times[-1]-times[0]),source_to_web_ms_median=statistics.median(latency),
            source_to_web_ms_p95=latency[min(len(latency)-1,math.floor(len(latency)*.95))],
            web_transfer_ms_median=statistics.median(r['web_transfer_ms'] for r in rows),unique_jpegs=len({r['sha256'] for r in rows}),error=self.error)


class CameraNative(Native):
    def __init__(self,path):
        super().__init__(path);(self.path/'frames').mkdir();self.video_lock=threading.Lock();self.video_log=(self.path/'web-frames.jsonl').open('w');self.readers=[]
    def camera(self,target):
        data=self.api('/api/cameras?target='+target);assert data['cameras'],data
        self.wait(lambda:any(v['online'] for v in self.api('/api/cameras?target='+target)['cameras']),15)
        data=self.api('/api/cameras?target='+target)
        assert all(v['binding']['target']==target and v['kind']=='gazebo' for v in data['cameras'])
        self.report.setdefault('camera_catalogs',[]).append(data)
        return data['cameras'][0]
    def reader(self,target,camera,phase,**kwargs):
        reader=VideoReader(self,target,camera,phase,**kwargs);self.readers.append(reader);return reader
    def resource_sample(self,children):
        groups={}
        for owner in {c.owner for c in children}:
            for process,_,record in owner.session.processes:groups[process.pid]='world:'+record['name']
        for child in children:
            for process,_,record in child.session.processes:groups[process.pid]=child.id+':'+record['name']
        rows=[]
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():continue
            try:
                stat=(path/'stat').read_text().rsplit(')',1)[1].split();pgid=int(stat[2]);pid=int(path.name)
                if pgid not in groups and pid!=os.getpid():continue
                rows.append(dict(pid=pid,component='web-test-host' if pid==os.getpid() else groups[pgid],
                    at_ns=time.monotonic_ns(),cpu_ticks=int(stat[11])+int(stat[12]),rss_bytes=int(stat[21])*os.sysconf('SC_PAGE_SIZE')))
            except (OSError,ValueError,IndexError):pass
        self.report.setdefault('resource_samples',[]).append(rows)
        return rows
    def move(self,target,reader):
        self.action(target,'SetMode',{'mode':'GUIDED'});self.action(target,'Arm');oracle=self.oracles[target]
        initial=oracle.latest();p=dict(speed_mps=.3,yaw_rate_rad_s=.2)
        result=self.api('/api/manual/start',dict(target=target,name='Drive',parameters=p,allow_send=True,timeout_s=60))
        session=result['session']['id'];identifier=result['action']['id']
        self.wait(lambda:self.app.runtime.view(identifier)['state']=='RUNNING',5)
        end=time.monotonic()+15
        while time.monotonic()<end:
            time.sleep(.1);view=self.app.runtime.view(identifier);assert view['state']=='RUNNING',(view['state'],view['error'])
            self.api('/api/manual/update',dict(session_id=session,sequence=view['input_sequence']+1,deadline_ns=view['input_ticket'],parameters=p))
        self.api('/api/manual/stop',dict(session_id=session))
        final=self.wait(lambda:(lambda v:v if v['state'] in TERMINAL else None)(self.app.runtime.view(identifier)),20)
        assert final['state']=='CANCELLED' and final['safety']['release_safe'];assert oracle.recent_speed_mps()<=.1
        end=oracle.latest();distance=math.hypot(end.x_m-initial.x_m,end.y_m-initial.y_m);angle=end.yaw_rad-initial.yaw_rad
        self.report['motion']=dict(action_id=identifier,distance_m=distance,yaw_change_rad=angle,final_speed_mps=oracle.recent_speed_mps())
        assert distance>.5 and abs(angle)>.1,(distance,angle)
        assert len({r['sha256'] for r in reader.records})>10,'movement must visibly change native camera images'
        self.action(target,'Disarm')
    def browser(self,children,cameras):
        from playwright.sync_api import sync_playwright,expect
        from tests.browser_auth import login
        errors=[]
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                context=browser.new_context(viewport={'width':1480,'height':1080},accept_downloads=True)
                page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                login(page,self.base,self.token,'/control#'+children[0].target)
                expect(page.locator('#camera-video')).to_be_visible(timeout=15000)
                page.wait_for_function("() => document.querySelector('#camera-video').naturalWidth===640")
                assert not self.app.operator_controls.records
                page.screenshot(path=str(self.path/'preview-rover-A.png'),full_page=True)
                with page.expect_download() as dl:page.locator('#camera-snapshot').click()
                dl.value.save_as(str(self.path/'browser-snapshot.jpg'))
                page.locator('#camera-fullscreen').click();page.wait_for_function('() => document.fullscreenElement!==null');page.screenshot(path=str(self.path/'fullscreen-camera.png'));page.evaluate('document.exitFullscreen()')
                # Closing and reopening with the same authenticated cookie must
                # start a new video connection, without acquiring SEND.
                page.close();page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(self.base+'/control#'+children[0].target)
                expect(page.locator('#camera-video')).to_be_visible(timeout=15000)
                page.wait_for_function("() => document.querySelector('#camera-video').naturalWidth===640")
                source=next(iter(children[0].camera_sources.values()));os.kill(source.process.pid,signal.SIGSTOP)
                try:
                    expect(page.locator('#camera-video')).to_be_hidden(timeout=4000)
                    assert not self.api('/api/cameras?target='+children[0].target)['cameras'][0]['online']
                    self.api('/api/cameras/'+cameras[0]['camera_id']+'/snapshot?target='+children[0].target,reject=True)
                    page.screenshot(path=str(self.path/'camera-stale-cleared.png'),full_page=True)
                finally:os.kill(source.process.pid,signal.SIGCONT)
                expect(page.locator('#camera-video')).to_be_visible(timeout=8000)
                self.report['checks']['camera interruption / stale clearing / recovery']='PASS'
                if len(children)>1:
                    page.locator('#target').select_option(children[1].target)
                    expect(page.locator('#camera-identity')).to_contain_text(cameras[1]['camera_id'],timeout=12000)
                    expect(page.locator('#camera-identity')).not_to_contain_text(cameras[0]['camera_id'])
                    assert page.locator('#camera-video').get_attribute('src').endswith('?target='+children[1].target)
                    page.screenshot(path=str(self.path/'preview-rover-B.png'),full_page=True)
                assert not errors,errors
                self.report['checks']['authenticated browser preview / snapshot / fullscreen / close and reopen']='PASS'
                self.report['browser_errors']=errors
                # Leave the page visible for native remove/World tests.
                yield page
            finally:browser.close()
    def multi_camera_browser(self,target,cameras):
        from playwright.sync_api import sync_playwright,expect
        from tests.browser_auth import login
        errors=[]
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            try:
                page=browser.new_page(viewport={'width':1480,'height':1080});page.on('pageerror',lambda e:errors.append(str(e)))
                login(page,self.base,self.token,'/control#'+target)
                expect(page.locator('#camera-source option')).to_have_count(len(cameras)+1,timeout=10000)
                if len(cameras)>1:expect(page.locator('#camera-video')).to_be_hidden()
                for camera in cameras:
                    page.locator('#camera-source').select_option(camera['camera_id'])
                    expect(page.locator('#camera-video')).to_be_visible(timeout=10000)
                    page.wait_for_function("() => document.querySelector('#camera-video').naturalWidth===640")
                    assert camera['camera_id'] in page.locator('#camera-video').get_attribute('src')
                    expect(page.locator('#camera-state')).to_contain_text('在线',timeout=5000)
                    expect(page.locator('#camera-health')).to_contain_text('FPS')
                    page.screenshot(path=str(self.path/('preview-'+camera['slot']+'.png')),full_page=True)
                assert not self.app.operator_controls.records and not errors,errors
                self.report['checks']['multiple source browser selection / readonly']='PASS'
                self.report['browser_errors']=errors
            finally:browser.close()

    def native_identity(self,camera,reader):
        import cv2,numpy as np
        from gz.transport13 import Node
        from gz.msgs10.image_pb2 import Image,RGB_INT8
        evidence=deque(maxlen=128);lock=threading.Lock()
        def ingest(message):
            if message.pixel_format_type!=RGB_INT8:return
            stamp=message.header.stamp.sec*1_000_000_000+message.header.stamp.nsec
            image=np.frombuffer(message.data,dtype=np.uint8).reshape(message.height,message.step)[:,:message.width*3].reshape(message.height,message.width,3)
            image=cv2.cvtColor(image,cv2.COLOR_RGB2BGR)
            if message.width>640:image=cv2.resize(image,(640,int(message.height*640/message.width)))
            ok,jpeg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,75])
            with lock:evidence.append((stamp,hashlib.sha256(jpeg.tobytes()).hexdigest()))
        node=Node();assert node.subscribe(Image,camera['source'],ingest)
        time.sleep(3)
        node.unsubscribe(camera['source'])
        with lock:raw=dict(evidence)
        matching=[r for r in reader.records if raw.get(r['captured_ns'])==r['sha256']]
        assert len(matching)>5,'HTTP JPEG must match independent native Gazebo image pixels and capture stamp'
        self.report.setdefault('native_image_match',[]).append(dict(topic=camera['source'],matches=len(matching),capture_stamps=[r['captured_ns'] for r in matching]))
    def finish(self):
        for reader in self.readers:reader.close()
        self.video_log.close();pids=[row['worker_pid'] for catalog in self.report.get('camera_catalogs',[]) for row in catalog['cameras']]+[s.process.pid for owner in self.app.simulation_manager.owners.values() for c in owner.vehicles.values() for s in c.camera_sources.values()]
        super().close()
        self.report['camera_process_cleanup']={str(pid):not Path('/proc/'+str(pid)).exists() for pid in pids}
        if not all(self.report['camera_process_cleanup'].values()):self.report['status']='FAIL'
        (self.path/'result.json').write_text(json.dumps(self.report,ensure_ascii=False,indent=2)+'\n')


def run(path,stage):
    n=CameraNative(path)
    try:
        kinds=['rover','rover'] if stage=='acceptance' else [stage]
        identifier,owner,children=n.create(kinds,scene_id='F01' if stage=='plane' else 'R01');cameras=[n.camera(c.target) for c in children]
        video_children=children
        if stage=='plane':
            cameras=n.api('/api/cameras?target='+children[0].target)['cameras'];assert len(cameras)==2 and all(c['online'] for c in cameras)
            video_children=[children[0]]*len(cameras)
        readers=[n.reader(c.target,camera['camera_id'],'stationary-'+str(i)) for i,(c,camera) in enumerate(zip(video_children,cameras))]
        slow=n.reader(children[0].target,cameras[0]['camera_id'],'slow-client',slow=True)
        start=n.resource_sample(children);time.sleep(8);end=n.resource_sample(children)
        slow.close();n.report['slow_client']=dict(received_frames=len(slow.records),error=slow.error,global_stream_limit=4,send_buffer_bytes=65536,write_timeout_s=.5)
        n.report['checks']['slow reader bounded / other streams stay live']='PASS'
        assert all(c.driver.info()['writer']['attempts']==0 and not c.driver.info()['system_send'] and not c.driver.info()['lease_active'] for c in children)
        n.report['checks']['stationary native video without SEND / control / Writer']='PASS'
        for camera,reader in zip(cameras,readers):n.native_identity(camera,reader)
        for reader in readers:reader.close()
        stream_summaries=[reader.summary() for reader in readers]
        assert all(s['fps']>=5 for s in stream_summaries),stream_summaries
        if stage=='acceptance':
            assert cameras[0]['source']!=cameras[1]['source'] and cameras[0]['camera_id']!=cameras[1]['camera_id']
            n.api('/api/cameras/'+cameras[0]['camera_id']+'/snapshot?target='+children[1].target,reject=True)
            for page in n.browser(children,cameras):
                motion=n.reader(children[0].target,cameras[0]['camera_id'],'moving-turning')
                n.move(children[0].target,motion);motion.close();stream_summaries.append(motion.summary());assert children[1].driver.info()['writer']['attempts']==0
                n.report['checks']['moving and turning real image change / Rover A B isolation']='PASS'
                old=children[1];old_camera=cameras[1]
                n.api('/api/simulation/remove_vehicle',dict(id=identifier,vehicle_id=old.id));r=n.operation(identifier);assert r['operation']['state']=='SUCCEEDED',r['operation']
                n.oracles.pop(old.target,None)
                from playwright.sync_api import expect
                expect(page.locator('#camera-video')).to_be_hidden(timeout=6000)
                n.api('/api/cameras/'+old_camera['camera_id']+'/snapshot?target='+old.target,reject=True)
                n.api('/api/simulation/add_vehicle',dict(id=identifier,vehicle=dict(kind='rover',spawn={'id':'north'})))
                r=n.operation(identifier);assert r['operation']['state']=='SUCCEEDED',r['operation']
                new=next(c for c in owner.vehicles.values() if c.target!=children[0].target);fresh=n.camera(new.target)
                assert fresh['camera_id']!=old_camera['camera_id'] and fresh['binding']['epoch']!=old_camera['binding']['epoch']
                n.report['checks']['remove and recreate clears old video / fresh identity']='PASS'
                page.locator('#target').select_option(new.target);expect(page.locator('#camera-video')).to_be_visible(timeout=10000)
                oldtarget=new.target;oldcamera=fresh['camera_id'];oldworld=owner.world
                switched=n.api('/api/simulation/switch',dict(id=identifier,scene_id='R01',parameters={'obstacle_count':0}))
                expect(page.locator('#camera-video')).to_be_hidden(timeout=6000)
                n.wait(lambda:n.app.simulation_manager.sample(identifier).get('switch',{}).get('state')=='SUCCEEDED',180)
                new_id=switched['switch']['new_session_id'];newowner=n.app.simulation_manager.owners[new_id]
                n.api('/api/cameras/'+oldcamera+'/snapshot?target='+oldtarget,reject=True)
                for c in newowner.vehicles.values():
                    cam=n.camera(c.target);assert cam['binding']['world']!=oldworld and cam['camera_id'] not in [v['camera_id'] for v in cameras]
                n.report['checks']['World replacement fences previous source / epoch / frame']='PASS'
                page.screenshot(path=str(n.path/'world-old-frame-cleared.png'),full_page=True)
        if stage!='acceptance':n.multi_camera_browser(children[0].target,cameras)
        for reader in readers:reader.close()
        n.report['streams']=stream_summaries
        n.report['checks']['independent Gazebo pixel and capture stamp match']='PASS'
        n.report['status']='PASS'
    except Exception:
        n.report['error']=traceback.format_exc();print(n.report['error'],flush=True)
    finally:n.finish()
    print(json.dumps({k:v for k,v in n.report.items() if k not in ('vehicles','camera_catalogs')},ensure_ascii=False),flush=True)
    return n.report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--stage',choices=('acceptance','copter','plane'),default='acceptance');p.add_argument('--allow-send',action='store_true');a=p.parse_args()
    if not a.allow_send:p.error('explicit --allow-send required for owned native motion test')
    raise SystemExit(0 if run(a.run_dir,a.stage)['status']=='PASS' else 1)

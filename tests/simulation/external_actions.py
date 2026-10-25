"""Real native, HTTP service and ROS 2 DDS integration acceptance."""
import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
from threading import Thread,Event,RLock
import time
from uuid import uuid4

from vehicle_autonomy.actions.external.clients import ApiJob
from vehicle_autonomy.actions.external.native import NativeJob
from vehicle_autonomy.actions.external.job import DurationParameters
from vehicle_autonomy.actions.common.standard import Empty
from vehicle_autonomy.app.bootstrap.external_actions import ExternalActionDriver,register_external,ros_job,initialize_http_resources
from vehicle_autonomy.app.web.action_lab import ActionLab
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.engine.action.resources import PersistentResources
from vehicle_autonomy.contracts.action import ActionSafety
from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry


class ProviderJob:
    """Independent server-side worker; no framework client/Runtime shortcuts."""
    def __init__(self,execute):
        self.cancelled=Event();self.lock=RLock();self.value={'state':'RUNNING'}
        def feedback(value):
            with self.lock:self.value={'state':'RUNNING','feedback':value}
        def run():
            try:
                result=execute(self.cancelled,feedback)
                value={'state':'CANCELLED' if self.cancelled.is_set() else 'SUCCEEDED','result':result}
            except Exception:value={'state':'FAILED','error':'intentional provider error'}
            with self.lock:self.value=value
        self.thread=Thread(target=run,daemon=True);self.thread.start()
    def poll(self):
        with self.lock:return dict(self.value)
    def cancel(self):self.cancelled.set()
    def close(self):self.thread.join(.1)


def timer(parameters,*,server=False):
    def execute(cancel,feedback):
        start=time.monotonic()
        while time.monotonic()-start<parameters.duration_s:
            feedback({'elapsed_s':time.monotonic()-start})
            if cancel.wait(.03):return {'cancelled':True}
        if parameters.behavior=='error':raise RuntimeError('intentional local service error')
        return {'elapsed_s':time.monotonic()-start}
    return ProviderJob(execute) if server else NativeJob(execute)


def isolated_registry(path):
    ProviderRegistry._root=path.absolute()
    os.environ['VAF_TEST_PROVIDER_REGISTRY']=str(path.absolute());ProviderRegistry.initialize()


def adopt_test_registry():
    # Fixture-only location injection. Production ignores this environment
    # variable; all applications in this test deployment share this one root.
    ProviderRegistry._root=Path(os.environ['VAF_TEST_PROVIDER_REGISTRY'])


def initialize_local_resources(directory,*,protocol,locator,provider_id,epoch):
    identity=(NativeJob.identity() if protocol=='native' else {'provider_id':provider_id,'provider_epoch':epoch,
        'resource_id':'jobs','protocol':protocol,'locator':locator})
    return PersistentResources.initialize(directory,lambda:ActionSafety(True,evidence={'quiescent':True,**identity}))


class JobServer(ThreadingHTTPServer):
    def __init__(self):
        self.jobs={};self.instance=uuid4().hex;super().__init__(('127.0.0.1',0),JobHandler)


class JobHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def response(self,value):
        raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)))
        self.send_header('X-VAF-Job-Protocol','2');self.end_headers();self.wfile.write(raw)
    def provider_identity(self):
        return {'provider_id':getattr(self.server,'provider_id',self.server.instance),
            'provider_epoch':self.server.instance,'resource_id':'jobs'}
    def job_allowed(self):
        # Independent provider implementation: reject mismatched requests before
        # starting/cancelling any worker, including through an endpoint alias.
        try:expected=json.loads(self.headers.get('X-VAF-Expected-Provider','null'))
        except ValueError:expected=None
        if expected!=self.provider_identity():self.send_error(409,'Provider identity/epoch mismatch');return False
        return True
    def job_response(self,identifier,value):
        self.response(dict(value,provider=self.provider_identity(),job_id=identifier))
    def do_POST(self):
        if not self.job_allowed():return
        from vehicle_autonomy.actions.external.job import WaitParameters
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path=='/jobs':
            identifier=uuid4().hex;self.server.jobs[identifier]=timer(WaitParameters(**data),server=True);self.job_response(identifier,{'id':identifier})
        elif self.path.startswith('/jobs/') and self.path.endswith('/cancel'):
            identifier=self.path.split('/')[2];self.server.jobs[identifier].cancel();self.job_response(identifier,{'requested':True})
        else:self.send_error(404)
    def do_GET(self):
        if self.path=='/identity':self.response(self.provider_identity())
        elif self.path=='/inventory':self.response({'instance':self.server.instance,'states':[j.poll()['state'] for j in self.server.jobs.values()]})
        elif self.job_allowed():
            identifier=self.path.split('/')[2];self.job_response(identifier,self.server.jobs[identifier].poll())


def run(path):
    path.mkdir(parents=True,exist_ok=False);report={'passed':False,'cases':{}};lab=server=ros=None
    events=(path/'runtime.jsonl').open('w');roslog=(path/'ros-server.log').open('w')
    try:
        isolated_registry(path/'provider-registry')
        prefix='/vaf_phase3_'+uuid4().hex;domain=173
        ros=subprocess.Popen([str(resource_root()/'scripts/with_ros2.sh'),'/usr/bin/python3',
            str(Path(__file__).with_name('external_ros_server.py')),'--prefix',prefix],
            env=dict(os.environ,ROS_DOMAIN_ID=str(domain)),stdout=roslog,stderr=roslog,start_new_session=True)
        end=time.monotonic()+5
        while time.monotonic()<end:
            if ros.poll() is not None:raise RuntimeError('actual ROS server failed to start')
            if '"ready": true' in (path/'ros-server.log').read_text():break
            time.sleep(.1)
        else:raise TimeoutError('actual ROS server startup')
        server=JobServer();Thread(target=server.serve_forever,daemon=True).start()
        endpoint=f'http://127.0.0.1:{server.server_address[1]}'
        initialize_http_resources(path/'resource-state',endpoint,lambda:ActionSafety(not server.jobs,evidence={'quiescent':not server.jobs}))
        native=initialize_local_resources(path/'native-state',protocol='native',locator=prefix+'/native',provider_id=prefix+'/native',epoch=prefix+'/native')
        ros_store=initialize_local_resources(path/'ros-state',protocol='ros2',locator=f'ros2:{domain}:{prefix}',provider_id=prefix,epoch=prefix)
        registry=ActionRegistry();register_external(registry,'NativeWait',timer,resource_store=native)
        register_external(registry,'ApiWait',lambda p:ApiJob(f'http://127.0.0.1:{server.server_address[1]}',asdict(p)))
        register_external(registry,'ContinuousApi',lambda p:ApiJob(f'http://127.0.0.1:{server.server_address[1]}',asdict(p)),continuous=True)
        for action,suffix,service in [('RosWait','normal',False),('RosError','error',False),('RosUnavailable','absent',False),('RosDisconnect','disconnect',False),('RosService','trigger',True)]:
            register_external(registry,action,lambda p,s=suffix,v=service:ros_job(prefix+'/'+s,p,service=v,domain_id=domain,result_timeout=2 if s=='disconnect' else 8),
                parameters_type=Empty if service else DurationParameters,resource_store=ros_store)
        lab=ActionLab({'external':ExternalActionDriver(state_dir=path/'resource-state'),
            'lost':ExternalActionDriver('lost',state_dir=path/'resource-state')},registry=registry,
            event_sink=lambda e:(events.write(json.dumps(e)+'\n'),events.flush()))
        def execute(case,name,p,expected,*,timeout_s=8,cancel=False,target='external',feedback=False):
            a=lab.runtime.submit(name,target,p,timeout_s=timeout_s)
            end=time.monotonic()+15;observed=[];sent_cancel=False
            while time.monotonic()<end:
                a=lab.runtime.view(a['id']);observed.extend(a['feedback'])
                if cancel and a['feedback'] and not sent_cancel:lab.runtime.cancel(a['id']);sent_cancel=True
                if a['state'] in ('SUCCEEDED','FAILED','REJECTED','CANCELLED','TIMED_OUT','UNKNOWN'):break
                time.sleep(.05)
            if a['state']!=expected:raise AssertionError(case+': '+a['state']+': '+str(a['error']))
            if feedback and not observed:raise AssertionError(case+': real feedback missing')
            report['cases'][case]={'passed':True,'action':a,'real_feedback_observed':bool(observed)}
            return a
        execute('native_goal','NativeWait',{'duration_s':.3},'SUCCEEDED',feedback=True)
        execute('api_goal','ApiWait',{'duration_s':.3},'SUCCEEDED',feedback=True)
        execute('api_cancel','ContinuousApi',{'duration_s':3},'CANCELLED',cancel=True,feedback=True)
        execute('api_error','ApiWait',{'duration_s':.2,'behavior':'error'},'FAILED')
        execute('ros_goal_feedback_result','RosWait',{'duration_s':.8},'SUCCEEDED',feedback=True)
        execute('ros_cancel','RosWait',{'duration_s':3},'CANCELLED',cancel=True,feedback=True)
        execute('ros_timeout','RosWait',{'duration_s':3},'TIMED_OUT',timeout_s=.8)
        execute('ros_error_result','RosError',{'duration_s':.2},'FAILED')
        execute('ros_unavailable','RosUnavailable',{},'FAILED')
        execute('ros_service','RosService',{},'SUCCEEDED')
        execute('ros_disconnect','RosDisconnect',{'duration_s':3},'UNKNOWN',target='lost',feedback=True)
        if not lab.runtime.resources.view():raise AssertionError('lost external job released its resource')
        report['passed']=True
    except BaseException as exc:report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if lab:lab.close()
        if server:
            server.shutdown();server.server_close()
            for job in server.jobs.values():job.cancel();job.close()
        if ros and ros.poll() is None:
            ros.terminate()
            try:ros.wait(timeout=4)
            except subprocess.TimeoutExpired:ros.kill();ros.wait(timeout=2)
        report['ros_process_exit']=None if ros is None else ros.poll();events.close();roslog.close()
        (path/'summary.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);args=p.parse_args()
    result=run(args.run_dir.resolve());print(json.dumps({'passed':result['passed'],'error':result.get('error')}),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

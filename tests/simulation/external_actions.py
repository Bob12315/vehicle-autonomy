"""Real native, HTTP service and ROS 2 DDS integration acceptance."""
import argparse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
from threading import Thread
import time
from uuid import uuid4

from vehicle_autonomy.actions.external.clients import ApiJob
from vehicle_autonomy.actions.external.native import NativeJob
from vehicle_autonomy.actions.external.job import DurationParameters
from vehicle_autonomy.actions.common.standard import Empty
from vehicle_autonomy.app.bootstrap.external_actions import ExternalActionDriver,register_external,ros_job
from vehicle_autonomy.app.web.action_lab import ActionLab
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy._resources import resource_root


def timer(parameters):
    def execute(cancel,feedback):
        start=time.monotonic()
        while time.monotonic()-start<parameters.duration_s:
            feedback({'elapsed_s':time.monotonic()-start})
            if cancel.wait(.03):return {'cancelled':True}
        if parameters.behavior=='error':raise RuntimeError('intentional local service error')
        return {'elapsed_s':time.monotonic()-start}
    return NativeJob(execute)


class JobServer(ThreadingHTTPServer):
    def __init__(self):
        self.jobs={};super().__init__(('127.0.0.1',0),JobHandler)


class JobHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def response(self,value):
        raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        from vehicle_autonomy.actions.external.job import WaitParameters
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path=='/jobs':
            identifier=uuid4().hex;self.server.jobs[identifier]=timer(WaitParameters(**data));self.response({'id':identifier})
        elif self.path.startswith('/jobs/') and self.path.endswith('/cancel'):
            self.server.jobs[self.path.split('/')[2]].cancel();self.response({'requested':True})
        else:self.send_error(404)
    def do_GET(self):self.response(self.server.jobs[self.path.split('/')[2]].poll())


def run(path):
    path.mkdir(parents=True,exist_ok=False);report={'passed':False,'cases':{}};lab=server=ros=None
    events=(path/'runtime.jsonl').open('w');roslog=(path/'ros-server.log').open('w')
    try:
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
        registry=ActionRegistry();register_external(registry,'NativeWait',timer)
        register_external(registry,'ApiWait',lambda p:ApiJob(f'http://127.0.0.1:{server.server_address[1]}',asdict(p)))
        register_external(registry,'ContinuousApi',lambda p:ApiJob(f'http://127.0.0.1:{server.server_address[1]}',asdict(p)),continuous=True)
        for action,suffix,service in [('RosWait','normal',False),('RosError','error',False),('RosUnavailable','absent',False),('RosDisconnect','disconnect',False),('RosService','trigger',True)]:
            register_external(registry,action,lambda p,s=suffix,v=service:ros_job(prefix+'/'+s,p,service=v,domain_id=domain,result_timeout=2 if s=='disconnect' else 8),
                parameters_type=Empty if service else DurationParameters)
        lab=ActionLab({'external':ExternalActionDriver(),'lost':ExternalActionDriver('lost')},registry=registry,
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

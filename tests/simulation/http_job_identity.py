"""Real HTTP epoch switches, reused IDs and per-response identity fences."""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
import time
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from uuid import uuid4
from unittest.mock import patch

from vehicle_autonomy.actions.external.clients import ApiJob,ProviderIdentityError
from vehicle_autonomy.app.bootstrap.external_actions import ExternalActionDriver,initialize_http_resources,register_external,reconcile_api_resource
from vehicle_autonomy.contracts.action import ActionSafety
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.engine.action.manager import ActionRuntime
from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry
from vehicle_autonomy.engine.action.registry import ActionRegistry
from tests.simulation.external_actions import ProviderJob

CASES=('poll_epoch','unknown_epoch','read_identity_race','foreign_response','cancel_epoch',
    'submit_epoch','wrong_job','missing_provider','missing_job_id','lost_admission_identity','legacy_protocol')


def clock():return TimePoint(time.monotonic_ns(),datetime.now(timezone.utc),'host-monotonic-simulation')
def endpoint(server):return f'http://127.0.0.1:{server.server_address[1]}'
def active(server):return sum(job.poll()['state']=='RUNNING' for job in server.jobs.values())
def wait(predicate,runtime=None,seconds=5):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if runtime:runtime.tick()
        value=predicate()
        if value:return value
        time.sleep(.01)
    raise TimeoutError('HTTP identity fixture condition not reached')


class Provider(ThreadingHTTPServer):
    def __init__(self,provider_id):
        self.provider_id=provider_id;self.epoch=uuid4().hex;self.jobs={};self.requests=[]
        self.fail_status=False;self.enforce_reads=True;self.version='2';self.cancel_calls=0;self.peak_active=0
        super().__init__(('127.0.0.1',0),ProviderHandler)
    def identity(self):return {'provider_id':self.provider_id,'provider_epoch':self.epoch,'resource_id':'jobs'}


class ProviderHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def response(self,value,code=200):
        raw=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Length',str(len(raw)))
        if self.server.version:self.send_header('X-VAF-Job-Protocol',self.server.version)
        self.end_headers();self.wfile.write(raw)
    def allowed(self):
        expected=json.loads(self.headers.get('X-VAF-Expected-Provider','null'))
        self.server.requests.append({'method':self.command,'path':self.path,'expected':expected,'actual':self.server.identity()})
        if expected!=self.server.identity() and (self.command=='POST' or self.server.enforce_reads):
            self.response({'error':'provider changed'},409);return False
        return True
    def do_GET(self):
        if self.path=='/identity':self.response(self.server.identity());return
        if not self.allowed():return
        if self.server.fail_status:self.response({'error':'status temporarily unavailable'},503);return
        identifier=self.path.split('/')[2]
        self.response(dict(self.server.jobs[identifier].poll(),job_id=identifier,provider=self.server.identity()))
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if not self.allowed():return
        if self.path=='/jobs':
            identifier=str(len(self.server.jobs)+1)
            def execute(cancel,feedback):
                end=time.monotonic()+data['duration_s']
                while time.monotonic()<end:
                    feedback({'epoch':self.server.epoch})
                    if cancel.wait(.01):return {'cancelled':True}
                return {'completed':True}
            self.server.jobs[identifier]=ProviderJob(execute)
            self.server.peak_active=max(self.server.peak_active,active(self.server))
            self.response({'id':identifier,'provider':self.server.identity()})
        else:
            identifier=self.path.split('/')[2];self.server.cancel_calls+=1;self.server.jobs[identifier].cancel()
            self.response({'requested':True,'job_id':identifier,'provider':self.server.identity()})


class Proxy(ThreadingHTTPServer):
    def __init__(self,upstream):
        self.upstream=upstream;self.identity_upstream=None;self.after_identity=None;self.on_cancel=None
        self.status_id=None;self.strip_field=None;self.strip_admission=False
        super().__init__(('127.0.0.1',0),ProxyHandler)


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def forward(self):
        proxy=self.server;path=self.path
        if path.endswith('/cancel') and proxy.on_cancel:
            proxy.upstream=proxy.on_cancel;proxy.on_cancel=None
        upstream=proxy.identity_upstream if path=='/identity' and proxy.identity_upstream else proxy.upstream
        if self.command=='GET' and path.startswith('/jobs/') and proxy.status_id:path='/jobs/'+proxy.status_id
        body=self.rfile.read(int(self.headers.get('Content-Length',0))) if self.command=='POST' else None
        headers={'Content-Type':'application/json'}
        if self.headers.get('X-VAF-Expected-Provider'):headers['X-VAF-Expected-Provider']=self.headers['X-VAF-Expected-Provider']
        try:response=urlopen(Request(upstream+path,data=body,headers=headers),timeout=1)
        except HTTPError as exc:response=exc
        with response:
            raw=response.read();code=response.code;version=response.headers.get('X-VAF-Job-Protocol')
        if code==200 and ((self.command=='GET' and path.startswith('/jobs/') and proxy.strip_field)
                or (self.command=='POST' and path=='/jobs' and proxy.strip_admission)):
            value=json.loads(raw);value.pop('provider' if proxy.strip_admission else proxy.strip_field,None);raw=json.dumps(value).encode()
        if path=='/identity' and proxy.after_identity:
            proxy.upstream=proxy.after_identity;proxy.after_identity=None
        self.send_response(code);self.send_header('Content-Length',str(len(raw)))
        if version:self.send_header('X-VAF-Job-Protocol',version)
        self.end_headers();self.wfile.write(raw)
    do_GET=forward
    do_POST=forward


def seed(server):
    headers={'Content-Type':'application/json','X-VAF-Expected-Provider':json.dumps(server.identity())}
    with urlopen(Request(endpoint(server)+'/jobs',data=b'{"duration_s":0.02}',headers=headers),timeout=1) as response:
        identifier=json.load(response)['id']
    wait(lambda:active(server)==0);return identifier


def run_case(root,case):
    root.mkdir(parents=True);result={'case':case,'passed':False,'vehicle_writer_calls':0};jobs=[];servers=[];threads=[];events=[]
    provider_id='http-identity-'+uuid4().hex
    first=Provider(provider_id);second=Provider(provider_id);proxy=Proxy(endpoint(first));servers=[first,second,proxy]
    for server in servers:
        thread=Thread(target=server.serve_forever,daemon=True);thread.start();threads.append(thread)
    with ExitStack() as stack:
        stack.enter_context(patch.object(ProviderRegistry,'_root',root/'registry'));ProviderRegistry.initialize()
        try:
            seed(second)
            previous=seed(first) if case=='wrong_job' else None
            if case=='legacy_protocol':first.version=None
            try:
                store=initialize_http_resources(root/'ledger',endpoint(proxy),lambda:ActionSafety(active(first)==0,evidence={'quiescent':active(first)==0}))
            except ProviderIdentityError:
                if case!='legacy_protocol':raise
                assert not first.jobs
                result.update(passed=True,unsupported_provider_rejected_before_POST=True,actual_started=0);return result
            registry=ActionRegistry();positive=[False]
            def create(parameters):
                job=ApiJob(endpoint(proxy),dict(asdict(parameters),duration_s=.05 if positive[0] else 30));jobs.append(job);return job
            register_external(registry,'remote',create)
            runtime=ActionRuntime(registry,{'external':ExternalActionDriver(state_dir=store.root)},clock=clock,event_sink=events.append)
            if case=='submit_epoch':proxy.after_identity=endpoint(second)
            if case=='lost_admission_identity':proxy.strip_admission=True
            submitted=runtime.submit('remote','external');identifier=submitted['id']
            if case not in ('submit_epoch','lost_admission_identity'):
                wait(lambda:active(first)==1 and jobs[0].recovery_descriptor()['job_id'],runtime)
            else:wait(lambda:runtime.view(identifier)['state']=='UNKNOWN',runtime)
            if case=='unknown_epoch':
                first.fail_status=True;wait(lambda:runtime.view(identifier)['state']=='UNKNOWN',runtime)
            if case in ('poll_epoch','unknown_epoch','foreign_response'):proxy.upstream=endpoint(second)
            if case=='foreign_response':second.enforce_reads=False
            if case=='read_identity_race':
                proxy.identity_upstream=endpoint(first);proxy.upstream=endpoint(second);second.enforce_reads=False
            if case=='cancel_epoch':
                proxy.on_cancel=endpoint(second);runtime.cancel(identifier)
            if case=='wrong_job':proxy.status_id=previous
            if case in ('missing_provider','missing_job_id'):proxy.strip_field='provider' if case=='missing_provider' else 'job_id'
            unknown=wait(lambda:(v if (v:=runtime.view(identifier))['state']=='UNKNOWN' else None),runtime)
            claims=runtime.resource_view();assert claims and not unknown['safety']['release_safe']
            for _ in range(20):runtime.tick()
            assert runtime.resource_view() and not runtime.view(identifier)['safety']['release_safe']
            competitor=runtime.submit('remote','external');assert competitor['state']=='REJECTED'
            assert len(second.jobs)==1 and second.cancel_calls==0
            expected_started=0 if case=='submit_epoch' else (2 if case=='wrong_job' else 1)
            assert len(first.jobs)==expected_started and active(first)==(0 if case=='submit_epoch' else 1)
            record=store.records()[0]
            try:manual=reconcile_api_resource(record)
            except (ValueError,HTTPError):manual=ActionSafety(False)
            assert not manual.release_safe
            if case=='read_identity_race':
                # /identity still reports A, while the following GET is served
                # by B: checking only before GET does not close this window.
                assert ApiJob.identity(endpoint(proxy))==first.identity()
            result.update(first_unknown=unknown,retained_claims=claims,competing_action=competitor['state'],
                jobs_before_reconciliation=len(first.jobs),actual_active_before_reconciliation=active(first),
                foreign_jobs=len(second.jobs),foreign_cancel_calls=second.cancel_calls,manual_release_safe=manual.release_safe)
            proxy.upstream=endpoint(first);proxy.identity_upstream=None;proxy.status_id=None;proxy.strip_field=None;proxy.strip_admission=False;first.fail_status=False
            if case in ('submit_epoch','lost_admission_identity'):
                assert jobs[0].recovery_descriptor()['job_id'] is None
                for job in first.jobs.values():job.cancel()
                wait(lambda:active(first)==0)
                # Lost admission responses need a complete trusted inventory;
                # restoring the endpoint must never retry POST automatically.
                for _ in range(20):runtime.tick()
                assert runtime.resource_view() and len(first.jobs)==expected_started
                assert runtime.reconcile_external(identifier,lambda r:ActionSafety(active(first)==0,evidence={
                    'owner':r['owner'],'scope':r['scope'],'terminal':active(first)==0,'verification':'complete owned provider inventory'}))
            else:
                time.sleep(1.1);runtime.tick()  # actual read-only recovery while A's job is STILL running
                assert runtime.resource_view() and active(first)==1
                for job in first.jobs.values():job.cancel()
                wait(lambda:not runtime.resource_view(),runtime)
            assert runtime.view(identifier)['state']=='UNKNOWN'
            positive[0]=True;fresh=runtime.submit('remote','external')
            normal=wait(lambda:(v if (v:=runtime.view(fresh['id']))['state']=='SUCCEEDED' else None),runtime)
            assert not runtime.resource_view() and active(first)==0 and first.peak_active<=1
            result.update(passed=True,old_logical_state=runtime.view(identifier)['state'],new_normal=normal,
                actual_total_after_recovery=len(first.jobs),peak_active=first.peak_active,actual_active_after_recovery=active(first))
            return result
        finally:
            for job in jobs:job.close()
            for server in (first,second):
                for job in server.jobs.values():job.cancel();job.close()
            for server in servers:server.shutdown();server.server_close()
            for thread in threads:thread.join(2)
            result['server_threads_stopped']=all(not thread.is_alive() for thread in threads)
            result['provider_requests']={'first':first.requests,'second':second.requests}
            (root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
            (root/'runtime.jsonl').write_text(''.join(json.dumps(event)+'\n' for event in events))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-dir',type=Path,required=True);args=parser.parse_args()
    root=args.run_dir.resolve();root.mkdir(parents=True,exist_ok=False);result={'passed':False,'cases':{}}
    try:
        for case in CASES:result['cases'][case]=run_case(root/case,case)
        result['passed']=all(value['passed'] and value['server_threads_stopped'] for value in result['cases'].values())
    except Exception as exc:result['error']=f'{type(exc).__name__}: {exc}'
    (root/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'error':result.get('error')}),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

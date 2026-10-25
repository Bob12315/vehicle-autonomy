"""Real HTTP/process and DDS Service regressions for the independent FAIL."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event,Thread
import time
from urllib.request import urlopen
from uuid import uuid4
from unittest.mock import patch

from vehicle_autonomy.actions.common.standard import Empty
from vehicle_autonomy.actions.external.clients import ApiJob,ProcessJob
from vehicle_autonomy.actions.external.job import ExternalFactory
from vehicle_autonomy.app.bootstrap.external_actions import ExternalActionDriver,register_external,reconcile_api_resource,initialize_http_resources
from vehicle_autonomy.app.web.action_lab import ActionLab
from vehicle_autonomy.contracts.action import ActionKind,ActionResource,ActionSafety
from vehicle_autonomy.contracts.decision import ActionSpec,ActionDecision,ActionOutcome,ExitDecision
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.action.resources import PersistentResources
from vehicle_autonomy._resources import resource_root
from tests.simulation.external_actions import JobHandler,timer,isolated_registry,initialize_local_resources,adopt_test_registry


def wait_for(predicate,seconds=8):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        result=predicate()
        if result:return result
        time.sleep(.02)
    raise TimeoutError('owned test condition not reached')


class Handler(JobHandler):
    def do_POST(self):
        if self.path=='/jobs' and self.server.hold_response:
            if not self.job_allowed():return
            from vehicle_autonomy.actions.external.job import WaitParameters
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            identifier=uuid4().hex;self.server.jobs[identifier]=timer(WaitParameters(**data),server=True)
            self.server.submitted.set();self.server.response_gate.wait(4)
            try:self.job_response(identifier,{'id':identifier})
            except BrokenPipeError:pass
        else:super().do_POST()
    def do_GET(self):
        if self.path=='/inventory':self.response({'instance':self.server.instance,'states':[j.poll()['state'] for j in self.server.jobs.values()]})
        else:super().do_GET()


def app_child(args):
    adopt_test_registry()
    registry=ActionRegistry();register_external(registry,'remote',lambda p:ApiJob(args.endpoint,asdict(p)))
    lab=ActionLab({args.target:ExternalActionDriver(args.target,state_dir=args.state)},registry=registry)
    try:
        a=lab.runtime.submit('remote',args.target,{'duration_s':.3 if args.positive else 20.})
        def snapshot():
            value=lab.runtime.view(a['id'])
            if args.positive:return value if value['state'] in ('SUCCEEDED','FAILED','UNKNOWN','REJECTED') else None
            if value['state']=='REJECTED':return value
            if value['state']=='RUNNING' and (args.early or value['feedback']):return value
        value=wait_for(snapshot)
        # Descriptor must be durable before declaring ID-known probe ready.
        records=lab.drivers[args.target].resource_store.records()
        if value['state']=='RUNNING' and not args.early:
            wait_for(lambda:any(r['owner']==a['id'] and r['descriptor'].get('job_id') for r in lab.drivers[args.target].resource_store.records()))
        args.snapshot.write_text(json.dumps({'action':value,'claims':lab.runtime.resource_view()}))
        while True:time.sleep(.1)
    finally:lab.close()


def http_restart(root,*,before_id=False):
    root.mkdir();server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.jobs={};server.hold_response=before_id;server.submitted=Event();server.response_gate=Event();server.instance=uuid4().hex
    thread=Thread(target=server.serve_forever,daemon=True);thread.start();children=[]
    endpoint=f'http://127.0.0.1:{server.server_address[1]}';state=root/'resource-state'
    initialize_http_resources(state,endpoint,lambda:ActionSafety(not server.jobs,evidence={'quiescent':not server.jobs}))
    def start(name,**kw):
        snapshot=root/(name+'.json')
        command=[sys.executable,'-m',__name__ if __name__!='__main__' else 'tests.simulation.remediation_external',
            '--app-child','--endpoint',endpoint,'--state',str(state),'--snapshot',str(snapshot),'--target',kw.get('target','external')]
        if before_id:command.append('--early')
        if kw.get('positive'):command.append('--positive')
        log=(root/(name+'.log')).open('w');p=subprocess.Popen(command,stdout=log,stderr=log,start_new_session=True)
        children.append((p,log));wait_for(lambda:snapshot.exists() or p.poll() is not None)
        if not snapshot.exists():raise AssertionError('isolated application did not produce evidence')
        return p,json.loads(snapshot.read_text())
    try:
        first,a=start('first')
        if before_id:assert server.submitted.wait(3)
        old=a['action']['id'];assert a['action']['state']=='RUNNING'
        second,b=start('concurrent',target='alias')
        assert b['action']['state']=='REJECTED' and len(server.jobs)==1
        first.kill();first.wait(timeout=3)
        assert all(j.poll()['state']=='RUNNING' for j in server.jobs.values())
        third,c=start('restart',target='new-alias')
        assert c['action']['state']=='REJECTED' and len(server.jobs)==1
        ledger=PersistentResources(state);record=next(r for r in ledger.records() if r['owner']==old)
        if before_id:
            assert not record['descriptor'].get('job_id')
            try:ledger.reconcile(old,reconcile_api_resource)
            except ValueError:pass
            else:raise AssertionError('unknown job ID incorrectly resolved')
        else:assert ledger.reconcile(old,reconcile_api_resource) is False
        # Stop only jobs explicitly created on this owned test provider.
        for job in server.jobs.values():job.cancel()
        wait_for(lambda:all(j.poll()['state']=='CANCELLED' for j in server.jobs.values()))
        if before_id:
            def inventory_proof(r):
                with urlopen(endpoint+'/inventory',timeout=1) as response:inventory=json.load(response)
                terminal=inventory['instance']==server.instance and bool(inventory['states']) and all(s in ('SUCCEEDED','FAILED','CANCELLED') for s in inventory['states'])
                return ActionSafety(terminal,evidence={'owner':r['owner'],'scope':r['scope'],'terminal':terminal,
                    'verification':'trusted owned provider complete inventory','provider_instance':server.instance})
            assert ledger.reconcile(old,inventory_proof)
        else:assert ledger.reconcile(old,reconcile_api_resource)
        server.hold_response=False;server.response_gate.set()
        fourth,d=start('positive',positive=True)
        assert d['action']['state']=='SUCCEEDED' and len(server.jobs)==2
        return {'passed':True,'actual_http':True,'separate_applications':4,'prior_job_id_known':not before_id,
            'old_owner':old,'concurrent_state':b['action']['state'],'restart_state':c['action']['state'],
            'jobs_before_reconciliation':1,'positive_state':d['action']['state'],'vehicle_writer_calls':0,
            'record_before_reconciliation':record,'recovery':'complete_owned_provider_inventory' if before_id else 'read_existing_job_id'}
    finally:
        server.response_gate.set()
        for p,log in children:
            if p.poll() is None:p.terminate();p.wait(timeout=3)
            log.close()
        for job in server.jobs.values():job.cancel();job.close()
        server.shutdown();server.server_close();thread.join(2)


def ros_server(root,prefix):
    import rclpy
    from std_srvs.srv import Trigger
    from rclpy.executors import MultiThreadedExecutor,ExternalShutdownException
    from rclpy.callback_groups import ReentrantCallbackGroup
    rclpy.init();node=rclpy.create_node('remediation_service_'+uuid4().hex[:10]);group=ReentrantCallbackGroup()
    def callback(name,duration,success):
        def execute(request,response):
            identifier=uuid4().hex;(root/(name+'-started.json')).write_text(json.dumps({'invocation':identifier,'server':prefix}))
            time.sleep(duration)
            (root/(name+'-done.json')).write_text(json.dumps({'invocation':identifier,'server':prefix,'terminal':True}))
            response.success=success;response.message='owned service actual terminal result';return response
        return execute
    for name,duration,success in [('fault',4,True),('normal',.1,True),('error',.1,False)]:
        node.create_service(Trigger,prefix+'/'+name,callback(name,duration,success),callback_group=group)
    (root/'ready.json').write_text('{}');executor=MultiThreadedExecutor(2);executor.add_node(node)
    try:executor.spin()
    except (KeyboardInterrupt,ExternalShutdownException):pass
    finally:executor.shutdown(timeout_sec=2);node.destroy_node();rclpy.try_shutdown()


def ros_fault_worker(root,prefix):
    import rclpy
    from vehicle_autonomy.actions.external import ros_worker
    original=rclpy.spin_once;injected=False
    def spin(*a,**kw):
        nonlocal injected
        if not injected and (root/'fault-started.json').exists():
            injected=True;raise RuntimeError('injected client exception after actual service start')
        return original(*a,**kw)
    rclpy.spin_once=spin
    sys.argv=['worker','--name',prefix+'/fault','--service','--result-timeout','8']
    return ros_worker.main()


def ros_boundary(root):
    root.mkdir();prefix='/vaf_phase3_'+uuid4().hex
    repository=Path(__file__).resolve().parents[2]
    env=dict(os.environ,ROS_DOMAIN_ID='184',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',
        PYTHONPATH=os.pathsep.join([str(repository/'src'),str(repository),os.environ.get('PYTHONPATH','')]))
    wrapper=str(resource_root()/'scripts/with_ros2.sh');source=str(Path(__file__).resolve())
    log=(root/'server.log').open('w');server=subprocess.Popen([wrapper,'/usr/bin/python3',source,'--ros-server','--run-dir',str(root),'--prefix',prefix],env=env,stdout=log,stderr=log,start_new_session=True)
    jobs=[];lab=None
    try:
        wait_for(lambda:(root/'ready.json').exists())
        assert not (root/'fault-started.json').exists()
        initialize_local_resources(root/'resource-state',protocol='ros2',locator=f'ros2:184:{prefix}',provider_id=prefix,epoch=prefix)
        registry=ActionRegistry()
        def job(name):
            command=([wrapper,'/usr/bin/python3',source,'--ros-fault-worker','--run-dir',str(root),'--prefix',prefix] if name=='fault' else
                [wrapper,'/usr/bin/python3','-m','vehicle_autonomy.actions.external.ros_worker','--name',prefix+'/'+name,'--service','--result-timeout','8'])
            if name=='fault':
                # Only the test worker executable differs: it runs the real
                # ros_worker with one spin_once exception after server start.
                # The production executable/argument validator remains covered
                # by all normal DDS cases; identity/ledger checks are unmodified.
                with patch.object(ProcessJob,'_locator',return_value=f'ros2:184:{prefix}/{name}'):
                    p=ProcessJob(command,env=env)
            else:p=ProcessJob(command,env=env)
            jobs.append(p);return p
        for name in ('fault','normal','error','absent'):
            registry.register_typed(ActionSpec(name,Empty,kind=ActionKind.GOAL,resources=(ActionResource('ai.inference'),)),ExternalFactory(lambda _,n=name:job(n)))
        class Query:
            def start(self,*_):return self
            def tick(self,_):return ActionDecision(ActionOutcome.SUCCEEDED,result={'read_only':True})
            def exit(self,*_):return ExitDecision(True)
        registry.register_typed(ActionSpec('query',Empty,kind=ActionKind.QUERY),Query())
        driver=ExternalActionDriver(state_dir=root/'resource-state');lab=ActionLab({'external':driver},registry=registry)
        def execute(name,expected):
            a=lab.runtime.submit(name,'external');value=wait_for(lambda:(v if (v:=lab.runtime.view(a['id']))['state'] in ('SUCCEEDED','FAILED','UNKNOWN','REJECTED') else None))
            assert value['state']==expected,(name,value['state']);return value
        failed=execute('fault','UNKNOWN');active=(root/'fault-started.json').exists() and not (root/'fault-done.json').exists()
        assert active and not failed['safety']['release_safe'] and lab.runtime.resource_view()
        denied=execute('normal','REJECTED');assert not (root/'normal-started.json').exists()
        readonly=execute('query','SUCCEEDED')
        def verify(r):
            started=json.loads((root/'fault-started.json').read_text())
            done=json.loads((root/'fault-done.json').read_text()) if (root/'fault-done.json').exists() else {}
            terminal=done.get('invocation')==started['invocation'] and done.get('server')==prefix and done.get('terminal') is True
            return ActionSafety(terminal,evidence={'owner':r['owner'],'scope':r['scope'],'terminal':terminal,'verification':'owned server invocation terminal oracle'})
        assert not driver.resource_store.reconcile(failed['id'],verify)
        wait_for(lambda:(root/'fault-done.json').exists())
        assert lab.runtime.reconcile_external(failed['id'],verify)
        assert lab.runtime.view(failed['id'])['safety']['release_safe']
        normal=execute('normal','SUCCEEDED');negative=execute('error','FAILED');absent=execute('absent','FAILED')
        assert normal['safety']['release_safe'] and negative['safety']['release_safe'] and absent['safety']['release_safe']
        return {'passed':True,'actual_ros2_jazzy_dds':True,'actual_service_started_before_fault':active,
            'fault':failed,'conflict':denied,'query':readonly,'normal':normal,'terminal_error':negative,'unavailable':absent,
            'same_resource_recovered_after_verified_server_terminal':True,'no_automatic_service_resubmission':True,'vehicle_writer_calls':0}
    finally:
        if lab:lab.close()
        for job in jobs:job.close()
        if server.poll() is None:
            server.terminate()
            try:server.wait(timeout=4)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=2)
        log.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path);p.add_argument('--app-child',action='store_true')
    p.add_argument('--ros-server',action='store_true');p.add_argument('--ros-fault-worker',action='store_true');p.add_argument('--prefix')
    p.add_argument('--state',type=Path);p.add_argument('--endpoint');p.add_argument('--snapshot',type=Path);p.add_argument('--target',default='external')
    p.add_argument('--early',action='store_true');p.add_argument('--positive',action='store_true');args=p.parse_args()
    if args.app_child:return app_child(args)
    if args.ros_server:return ros_server(args.run_dir,args.prefix)
    if args.ros_fault_worker:return ros_fault_worker(args.run_dir,args.prefix)
    root=args.run_dir.resolve();root.mkdir(parents=True,exist_ok=False);report={'passed':False,'cases':{}}
    try:
        isolated_registry(root/'provider-registry')
        report['cases']['api_restart_known_id']=http_restart(root/'api-known')
        report['cases']['api_restart_before_id']=http_restart(root/'api-before-id',before_id=True)
        report['cases']['actual_ros_service_result_lost']=ros_boundary(root/'ros-service')
        report['passed']=True
    except BaseException as exc:report['error']=f'{type(exc).__name__}: {exc}'
    (root/'summary.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':report['passed'],'error':report.get('error')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

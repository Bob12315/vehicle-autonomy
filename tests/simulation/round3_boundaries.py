"""Real HTTP/multiprocess provider identity and mixed Rover exit regressions."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
import time
from urllib.request import urlopen
from unittest.mock import patch

from vehicle_autonomy.actions.common.standard import Empty
from vehicle_autonomy.actions.external.clients import ApiJob
from vehicle_autonomy.app.bootstrap.external_actions import ExternalActionDriver,register_external,initialize_http_resources,reconcile_api_resource
from vehicle_autonomy.app.web.action_lab import ActionLab
from vehicle_autonomy.contracts.action import ActionKind,ActionResource,ActionSafety
from vehicle_autonomy.contracts.decision import ActionSpec,ActionDecision,ActionOutcome,ExitDecision
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect,ModeEffect
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.action.resources import PersistentResources
from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry
from tests.simulation.external_actions import JobServer,isolated_registry,adopt_test_registry
from tests.simulation.remediation_external import wait_for,http_restart


def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def active(server):return sum(j.poll()['state']=='RUNNING' for j in server.jobs.values())
def endpoint(server):return f'http://127.0.0.1:{server.server_address[1]}'
def proof(server):return ActionSafety(active(server)==0,evidence={'quiescent':active(server)==0,'verification':'complete owned provider inventory'})


class Applications:
    def __init__(self,root):self.root=root;self.children=[];self.number=0
    def start(self,server,state,scope='external',*,positive=False,initialize=False,signal=None):
        self.number+=1;name=f'app-{self.number}';snapshot=self.root/(name+'.json')
        command=[sys.executable,'-m','tests.simulation.round3_boundaries','--child','--endpoint',endpoint(server),
            '--state',str(state),'--scope',scope,'--snapshot',str(snapshot),'--target',name]
        if positive:command.append('--positive')
        if initialize:command.append('--initialize')
        if signal:command.extend(['--signal',str(signal)])
        log=(self.root/(name+'.log')).open('w');p=subprocess.Popen(command,stdout=log,stderr=log,start_new_session=True)
        self.children.append((p,log));return p,snapshot
    def result(self,process,path):
        wait_for(lambda:path.exists() or process.poll() is not None)
        if not path.exists():raise AssertionError('application exited without a result: '+str(path))
        return json.loads(path.read_text())
    def run(self,*args,**kw):
        p,path=self.start(*args,**kw);return p,self.result(p,path)
    def close(self):
        for p,log in self.children:
            if p.poll() is None:p.terminate();p.wait(timeout=4)
            log.close()


def child(args):
    adopt_test_registry()
    if args.signal:
        args.snapshot.with_suffix('.ready').write_text('{}');wait_for(lambda:args.signal.exists())
    if args.initialize:
        try:
            def inventory():
                with urlopen(args.endpoint+'/identity',timeout=1) as r:identity=json.load(r)
                with urlopen(args.endpoint+'/inventory',timeout=1) as r:value=json.load(r)
                quiet=value['instance']==identity['provider_epoch'] and all(s in ('SUCCEEDED','FAILED','CANCELLED') for s in value['states'])
                return ActionSafety(quiet,evidence={'quiescent':quiet,'verification':'actual complete owned provider inventory',**identity})
            initialize_http_resources(args.state,args.endpoint,inventory,scope=args.scope)
        except (OSError,ValueError) as exc:
            write(args.snapshot,{'initialization_rejected':True,'error_type':type(exc).__name__});return 0
    registry=ActionRegistry();register_external(registry,'remote',lambda p:ApiJob(args.endpoint,asdict(p)))
    lab=ActionLab({args.target:ExternalActionDriver(args.target,state_dir=args.state,resource_scope=args.scope)},registry=registry)
    try:
        a=lab.runtime.submit('remote',args.target,{'duration_s':.2 if args.positive else 30.})
        def finished():
            v=lab.runtime.view(a['id'])
            if args.positive:return v if v['state'] in ('SUCCEEDED','FAILED','UNKNOWN','REJECTED') else None
            if v['state']=='REJECTED' or v['state']=='RUNNING' and v['feedback']:return v
        value=wait_for(finished)
        write(args.snapshot,{'action':value,'claims':lab.runtime.resource_view(),'pid':os.getpid()})
        while True:time.sleep(.1)
    finally:lab.close()


def provider_matrix(root):
    root.mkdir();apps=Applications(root);servers=[];threads=[];result={}
    def new_server():
        s=JobServer();t=Thread(target=s.serve_forever,daemon=True);t.start();servers.append(s);threads.append(t);return s
    try:
        server=new_server();state=root/'one';other=root/'two'
        initialize_http_resources(state,endpoint(server),lambda:proof(server),scope='primary')
        assert active(server)==0 and not server.jobs
        second_truth=proof(server).release_safe
        try:initialize_http_resources(other,endpoint(server),lambda:proof(server),scope='primary')
        except ValueError:pass
        else:raise AssertionError('same actual provider initialized twice')
        result['E']={'passed':True,'both_actual_empty_checks_true':second_truth,'second_ledger_registered':False,'jobs':len(server.jobs)}
        first,a=apps.run(server,state,'primary');owner=a['action']['id']
        assert a['action']['state']=='RUNNING' and active(server)==1
        for name,directory,scope in [('A',state,'primary'),('B',state,'alternate'),('C',other,'primary'),('D',other,'alternate')]:
            _,v=apps.run(server,directory,scope)
            assert v['action']['state']=='REJECTED' and len(server.jobs)==active(server)==1
            result[name]={'passed':True,'state':v['action']['state'],'actual_started':len(server.jobs),'actual_active':active(server)}
        different=new_server();different_state=root/'different-provider'
        initialize_http_resources(different_state,endpoint(different),lambda:proof(different))
        _,v=apps.run(different,different_state)
        assert v['action']['state']=='RUNNING' and active(server)==active(different)==1
        result['J']={'passed':True,'different_actual_identities':server.instance!=different.instance,'first_active':active(server),'different_active':active(different)}
        first.kill();first.wait(timeout=3)
        for directory,scope in ((state,'primary'),(state,'alternate'),(other,'other-epoch-label')):
            _,v=apps.run(server,directory,scope)
            assert v['action']['state']=='REJECTED' and len(server.jobs)==active(server)==1
        result['F']={'passed':True,'old_app_sigkill':first.returncode==-9,'alias_new_uuid_and_scopes_rejected':True,'actual_active':active(server)}
        # Corrupt only owned test records, then restore their exact original
        # bytes including the unresolved owner. Never clear a reservation.
        rejected=0
        for path,contents in ((state/'claims.json',b'35'),(state/'claims.json',None),
                (ProviderRegistry().root/'bindings.json',b'{'),(ProviderRegistry().root/'bindings.json',None)):
            good=path.read_bytes()
            try:
                if contents is None:path.unlink()
                else:path.write_bytes(contents)
                _,v=apps.run(server,state,'primary')
                assert v['action']['state']=='REJECTED' and len(server.jobs)==active(server)==1;rejected+=1
            finally:path.write_bytes(good);path.chmod(0o600)
        fresh=new_server();fresh_state=root/'registry-short-write'
        original=os.write
        with patch('vehicle_autonomy.engine.action.durable.os.write',side_effect=lambda fd,data:original(fd,data[:2])):
            try:initialize_http_resources(fresh_state,endpoint(fresh),lambda:proof(fresh))
            except OSError:pass
            else:raise AssertionError('partial identity write accepted')
        assert not fresh_state.exists() and not fresh.jobs
        initialize_http_resources(fresh_state,endpoint(fresh),lambda:proof(fresh))
        _,v=apps.run(fresh,fresh_state,positive=True)
        assert v['action']['state']=='SUCCEEDED'
        result['I']={'passed':True,'corrupt_or_missing_rejections':rejected,'short_identity_write_started_jobs':0,'normal_after_short_write':v['action']['state']}
        ledger=PersistentResources(state,'primary')
        assert not ledger.reconcile(owner,reconcile_api_resource)
        for job in server.jobs.values():job.cancel()
        wait_for(lambda:active(server)==0)
        assert ledger.reconcile(owner,reconcile_api_resource)
        _,v=apps.run(server,state,'primary',positive=True)
        assert v['action']['state']=='SUCCEEDED' and len(server.jobs)==2 and active(server)==0
        result['K']={'passed':True,'readonly_trusted_terminal_reconciliation':True,'new_state':v['action']['state'],'actual_total_after_recovery':len(server.jobs),'active':active(server)}
        concurrent=new_server();go=root/'initialize-go'
        children=[apps.start(concurrent,root/f'race-{i}',initialize=True,signal=go) for i in (1,2)]
        wait_for(lambda:all(path.with_suffix('.ready').exists() for _,path in children));go.write_text('{}')
        values=[apps.result(p,path) for p,path in children]
        assert sum(v.get('action',{}).get('state')=='RUNNING' for v in values)==1
        assert sum(v.get('initialization_rejected') is True for v in values)==1 and len(concurrent.jobs)==active(concurrent)==1
        result['H']={'passed':True,'concurrent_independent_apps':2,'successful_owners':1,'actual_started':len(concurrent.jobs),'actual_active':active(concurrent)}
        result['G']=http_restart(root/'before-job-id',before_id=True)
        result['passed']=all(result[k]['passed'] for k in 'ABCDEFGHIJK')
        result['vehicle_writer_calls']=0
        return result
    finally:
        apps.close()
        for s in servers:
            for j in s.jobs.values():j.cancel();j.close()
            s.shutdown();s.server_close()
        for t in threads:t.join(3)
        result['providers_closed']=all(not t.is_alive() for t in threads)
        write(root/'summary.json',result)


def hybrid(root,*,emit=False,timeout=False):
    from tests.simulation.launch import OwnedSimulation
    from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation
    from vehicle_autonomy.app.bootstrap.action_driver import VehicleActionDriver
    from vehicle_autonomy.vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
    from vehicle_autonomy.vehicles.ardupilot.transports.bytes import TcpByteTransport
    root.mkdir();owned=OwnedSimulation(root,'rover',confirmation_signing=True);lab=driver=server=None;result={'passed':False};writer=[]
    events=(root/'runtime.jsonl').open('w');apps=Applications(root)
    try:
        owned.start();ownership=OwnedActionSimulation(root/'manifest.json');server=JobServer();thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        store=initialize_http_resources(root/'provider-state',endpoint(server),lambda:proof(server))
        class Observe:
            def __init__(self,t):self.t=t
            def read(self,*a,**kw):return self.t.read(*a,**kw)
            def write(self,data):writer.append({'host_ns':time.monotonic_ns(),'raw_hex':data.hex()});return self.t.write(data)
            def close(self):self.t.close()
        def connect(host,port,**kw):
            assert (host,port)==('127.0.0.1',owned.port)
            return Observe(TcpByteTransport.connect(host,port,**kw))
        def event(e):events.write(json.dumps(e)+'\n');events.flush()
        driver=VehicleActionDriver('rover',owned.profile,ArduRoverCommandTranslator(mode_ids=owned.profile.mode_ids),ownership,
            allow_send=True,event_sink=event,transport_factory=connect)
        time.sleep(owned.profile.warmup_ns/1e9)
        class Instance:
            sent=False
            def __init__(self,positive=False):self.job=ApiJob(endpoint(server),{'duration_s':.3 if positive else 20.,'behavior':'normal'});self.positive=positive
            def tick(self,w):
                if self.positive and self.job.poll()['state']=='SUCCEEDED':return ActionDecision(ActionOutcome.SUCCEEDED,result={})
                effects=(ModeEffect('HOLD'),) if emit and not self.sent else ();self.sent=True
                return ActionDecision(ActionOutcome.RUNNING,effects,feedback=self.job.poll())
            def exit(self,*args):
                if self.positive:return ExitDecision(True)
                if timeout:return ExitDecision(False)
                raise RuntimeError('independent external cancel response lost')
        class Factory:
            resource_store=store;positive=False
            def start(self,*_):return Instance(self.positive)
        factory=Factory();reg=ActionRegistry();reg.register_typed(ActionSpec('mixed',Empty,kind=ActionKind.GOAL,effect_types=(ArmEffect,ModeEffect),
            external_lifecycle='managed',resources=(ActionResource('vehicle.motion',conflict_group='vehicle.control'),ActionResource('ai.inference'))),factory)
        lab=ActionLab({'rover':driver},registry=reg,event_sink=event)
        a=lab.runtime.submit('mixed','rover',allow_send=True)
        wait_for(lambda:lab.runtime.view(a['id'])['state']=='RUNNING' and active(server)==1)
        if emit:wait_for(lambda:any(r.phase.value=='COMPLETED' for r in driver.effect_results(a['id'])))
        lab.runtime.cancel(a['id'])
        value=wait_for(lambda:(v if (v:=lab.runtime.view(a['id']))['state']=='UNKNOWN' else None),seconds=12)
        time.sleep(.8);value=lab.runtime.view(a['id']);claims=lab.runtime.resource_view()
        assert not value['safety']['release_safe'] and active(server)==len(server.jobs)==1
        assert driver.guard_status(a['id']).release_safe
        assert len(writer)==int(emit) and len(value['effects'])==int(emit)
        b=lab.runtime.submit('mixed','rover',allow_send=True)
        assert b['state']=='REJECTED' and len(server.jobs)==active(server)==1
        _,alias=apps.run(server,store.root)
        assert alias['action']['state']=='REJECTED' and len(server.jobs)==1
        for job in server.jobs.values():job.cancel()
        wait_for(lambda:lab.runtime.view(a['id'])['safety']['release_safe'])
        assert lab.runtime.view(a['id'])['state']=='UNKNOWN' and not lab.runtime.resource_view()
        factory.positive=True;c=lab.runtime.submit('mixed','rover',allow_send=True)
        normal=wait_for(lambda:(v if (v:=lab.runtime.view(c['id']))['state'] in ('SUCCEEDED','FAILED','REJECTED','UNKNOWN') else None))
        assert normal['state']=='SUCCEEDED' and normal['safety']['release_safe'] and not lab.runtime.resource_view()
        result.update(passed=True,real_vehicle_driver=True,real_owned_rover_sitl_gazebo=True,real_http=True,
            emitted_vehicle_effects_before_cancel=int(emit),writer_calls_before_cancel=int(emit),actual_writer=writer,
            exit_timeout=timeout,first=value,claims_during_unknown=claims,vehicle_guard_release_safe=True,
            competing_action=b['state'],independent_alias=alias['action']['state'],jobs_during_unknown=1,
            recovered_logical_state=lab.runtime.view(a['id'])['state'],normal=normal)
        return result
    finally:
        apps.close()
        if lab:lab.close()
        elif driver:driver.close()
        if server:
            for job in server.jobs.values():job.cancel();job.close()
            server.shutdown();server.server_close();thread.join(3)
        owned.close();events.close();write(root/'summary.json',result)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path);p.add_argument('--child',action='store_true')
    p.add_argument('--endpoint');p.add_argument('--state',type=Path);p.add_argument('--scope',default='external');p.add_argument('--snapshot',type=Path)
    p.add_argument('--positive',action='store_true');p.add_argument('--initialize',action='store_true');p.add_argument('--signal',type=Path);p.add_argument('--target')
    args=p.parse_args()
    if args.child:return child(args)
    root=args.run_dir.resolve();root.mkdir(parents=True,exist_ok=False);result={'passed':False}
    try:
        isolated_registry(root/'provider-registry')
        result['provider_matrix']=provider_matrix(root/'provider-matrix')
        result['hybrid_unsent_exception']=hybrid(root/'hybrid-unsent')
        result['hybrid_actual_effect_timeout']=hybrid(root/'hybrid-actual',emit=True,timeout=True)
        result['passed']=all(result[k]['passed'] for k in ('provider_matrix','hybrid_unsent_exception','hybrid_actual_effect_timeout'))
    except BaseException as exc:result['error']=f'{type(exc).__name__}: {exc}'
    write(root/'summary.json',result);print(json.dumps({'passed':result['passed'],'error':result.get('error')}),flush=True)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())

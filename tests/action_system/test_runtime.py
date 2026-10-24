"""Deterministic standalone scheduler contracts; no simulated flight claims."""
from concurrent.futures import Future
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import unittest

from vehicle_autonomy.contracts.action import ActionContext, ActionKind, ActionResource, ActionSafety, ResourceMode
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected
from vehicle_autonomy.contracts.core.time import TimePoint
from vehicle_autonomy.contracts.decision import ActionDecision, ActionOutcome, ActionSpec, ExitDecision
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.action.runtime import ActionRuntime


def ready(value=None):
    f=Future();f.set_result(value);return f


class Clock:
    ns=1_000_000_000
    def __call__(self):return TimePoint(self.ns,datetime(2026,1,1,tzinfo=timezone.utc),'test')
    def advance(self,seconds):self.ns+=int(seconds*1e9)


@dataclass(frozen=True)
class Parameters:
    count: int=field(default=2,metadata={'minimum':1,'maximum':10})


class Instance:
    def __init__(self,p,*,continuous=False,emit=False,exit_error=False):
        self.p=p;self.ticks=0;self.continuous=continuous;self.emit=emit;self.exit_error=exit_error
    def tick(self,world):
        self.ticks+=1
        if not self.continuous and self.ticks>=self.p.count:
            return ActionDecision(ActionOutcome.SUCCEEDED,result={'count':self.ticks})
        return ActionDecision(ActionOutcome.RUNNING,(ArmEffect(),) if self.emit and self.ticks==1 else (),feedback={'tick':self.ticks})
    def exit(self,world,reason):
        if self.exit_error:raise RuntimeError('exit broke')
        return ExitDecision(True)


class Factory:
    def __init__(self,**kw):self.kw=kw
    def start(self,p,w):return Instance(p,**self.kw)


class Driver:
    def __init__(self):
        self.opened=[];self.writes=[];self.exiting=[];self.closed=[]
        self.safety=ActionSafety(True);self.open_future=None;self.close_future=None;self.dispatch_future=None
    def context(self):return ActionContext('v','rover',frozenset({'arm'}),True)
    def snapshot(self):return object()
    def open_scope(self,identifier,**kw):
        self.opened.append((identifier,kw));return self.open_future or ready()
    def emit(self,identifier,envelope,**kw):
        self.writes.append(envelope);return self.dispatch_future or ready()
    def effect_results(self,identifier):return ()
    def begin_exit(self,identifier):self.exiting.append(identifier)
    def finish_scope(self,identifier,**kw):
        self.closed.append((identifier,kw));return self.close_future or ready(self.safety)
    def guard_status(self,identifier):return None


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.registry=ActionRegistry();self.driver=Driver()
        self.runtime=ActionRuntime(self.registry,{'v':self.driver,'other':Driver()},clock=self.clock)
    def register(self,name='a',kind=ActionKind.GOAL,*,write=False,resources=True,**kw):
        spec=ActionSpec(name,Parameters,kind=kind,effect_types=(ArmEffect,) if write else (),
            resources=(ActionResource('vehicle.motion',conflict_group='vehicle.control'),) if resources else (),
            output_schema={'type':'object','properties':{'count':{'type':'integer'}},'required':['count'],'additionalProperties':False})
        self.registry.register_typed(spec,Factory(continuous=kind is ActionKind.CONTINUOUS,emit=write,**kw))
        return spec
    def ticks(self,n=5):
        for _ in range(n):self.runtime.tick()
    def test_four_semantics_feedback_results_and_explicit_continuous_cancel(self):
        for kind in ActionKind:
            self.register(kind.value,kind)
            r=self.runtime.submit(kind.value,'v')
            self.ticks()
            if kind is ActionKind.CONTINUOUS:
                self.assertEqual(self.runtime.view(r['id'])['state'],'RUNNING')
                self.runtime.cancel(r['id']);self.ticks()
                self.assertEqual(self.runtime.view(r['id'])['state'],'CANCELLED')
            else:self.assertEqual(self.runtime.view(r['id'])['state'],'SUCCEEDED')
            self.assertTrue(self.runtime.view(r['id'])['feedback'])
        self.assertEqual(self.driver.writes,[])
        self.assertEqual(self.driver.opened,[])
    def test_motion_query_shared_read_and_other_vehicle_concurrency(self):
        self.register('motion',ActionKind.CONTINUOUS,write=True)
        self.registry.register_typed(ActionSpec('query',Parameters,kind=ActionKind.QUERY,
            resources=(ActionResource('vehicle.state',ResourceMode.SHARED),)),Factory())
        a=self.runtime.submit('motion','v',allow_send=True)
        denied=self.runtime.submit('motion','v',allow_send=True)
        q=self.runtime.submit('query','v');q2=self.runtime.submit('query','v')
        other=self.runtime.submit('motion','other',allow_send=True);self.ticks()
        self.assertEqual(denied['state'],'REJECTED')
        for r in (q,q2):self.assertEqual(self.runtime.view(r['id'])['state'],'SUCCEEDED')
        for r in (a,other):self.assertEqual(self.runtime.view(r['id'])['state'],'RUNNING')
        self.assertEqual(len(self.driver.writes),1)
    def test_unknown_retains_resource_and_prohibits_handoff(self):
        self.register(kind=ActionKind.CONTINUOUS,write=True)
        self.driver.safety=ActionSafety(False,False,'stop UNCONFIRMED')
        a=self.runtime.submit('a','v',allow_send=True);self.ticks(1)
        self.runtime.cancel(a['id']);self.ticks()
        self.assertEqual(self.runtime.view(a['id'])['state'],'UNKNOWN')
        self.assertEqual(self.runtime.submit('a','v',allow_send=True)['state'],'REJECTED')
        self.assertEqual(len(self.driver.writes),1)
        self.assertIn('UNCONFIRMED',self.runtime.resources.view()[0]['retained'])
    def test_wait_cancel_and_deadline_never_write(self):
        self.register(kind=ActionKind.CONTINUOUS,write=True)
        self.runtime.submit('a','v',allow_send=True);self.ticks(1)
        waiting=self.runtime.submit('a','v',wait_timeout_s=2,allow_send=True)
        self.assertEqual(waiting['state'],'WAITING_RESOURCE')
        self.runtime.cancel(waiting['id']);self.ticks()
        self.assertEqual(self.runtime.view(waiting['id'])['state'],'CANCELLED')
        other=self.runtime.submit('a','v',wait_timeout_s=2,timeout_s=1,allow_send=True)
        self.clock.advance(1.1);self.ticks()
        self.assertEqual(self.runtime.view(other['id'])['state'],'TIMED_OUT')
        self.assertEqual(len(self.driver.writes),1)
    def test_hung_admission_and_exit_are_bounded_without_freeing_claim(self):
        self.register(write=True)
        self.driver.open_future=Future()
        a=self.runtime.submit('a','v',allow_send=True,timeout_s=1)
        self.clock.advance(2);self.ticks(1);self.clock.advance(8.1);self.ticks(1)
        self.assertEqual(self.runtime.view(a['id'])['state'],'UNKNOWN')
        self.assertTrue(self.runtime.resources.view());self.assertEqual(self.driver.writes,[])
        self.assertIn(a['id'],self.driver.exiting)
    def test_admission_errors_require_explicit_no_side_effect_contract(self):
        self.register(write=True)
        for exc,state in ((ActionAdmissionRejected('denied'),'REJECTED'),(RuntimeError('lost'),'UNKNOWN')):
            self.driver.open_future=Future();self.driver.open_future.set_exception(exc)
            target='other' if state=='UNKNOWN' else 'v'
            self.runtime.drivers[target]=self.driver
            a=self.runtime.submit('a',target,allow_send=True)
            self.ticks()
            self.assertEqual(self.runtime.view(a['id'])['state'],state)
        self.assertEqual(self.driver.writes,[])
    def test_dispatch_and_exit_exceptions_cannot_succeed(self):
        self.register(write=True)
        self.driver.dispatch_future=Future();self.driver.dispatch_future.set_exception(RuntimeError('send failed'))
        a=self.runtime.submit('a','v',allow_send=True);self.ticks()
        self.assertEqual(self.runtime.view(a['id'])['state'],'FAILED')
        self.register('bad_exit',exit_error=True)
        b=self.runtime.submit('bad_exit','v');self.ticks()
        self.assertEqual(self.runtime.view(b['id'])['state'],'FAILED')
    def test_explicit_successful_continuation_and_immutable_views(self):
        self.register(write=True)
        self.driver.safety=ActionSafety(False,True,'native flight remains active')
        a=self.runtime.submit('a','v',allow_send=True);self.ticks()
        self.assertEqual(self.runtime.view(a['id'])['state'],'SUCCEEDED')
        self.assertEqual(self.runtime.submit('a','v',continuation_of=a['id'])['state'],'REJECTED')
        b=self.runtime.submit('a','v',allow_send=True,continuation_of=a['id']);self.ticks()
        self.assertEqual(self.runtime.view(b['id'])['state'],'SUCCEEDED')
        owners={c['owner'] for c in self.runtime.resources.view()};self.assertEqual(owners,{b['id']})
        view=self.runtime.view(b['id']);view['result']['count']=99;view['history'].clear()
        self.assertEqual(self.runtime.view(b['id'])['result']['count'],2)
        self.assertTrue(self.runtime.view(b['id'])['history'])
    def test_strict_parameters_and_bounded_record_storage(self):
        self.register()
        for params in ([],False,{'unknown':1},{'count':True},{'count':0},{'count':11},{'count':float('nan')}):
            self.assertEqual(self.runtime.submit('a','v',params)['state'],'REJECTED')
        self.runtime.max_instances=len(self.runtime.views())
        with self.assertRaises(ValueError):self.runtime.submit('a','v')
    def test_registry_versions_filter_and_metadata_use_one_schema(self):
        spec=self.register(write=True)
        with self.assertRaises(ValueError):self.registry.register_typed(spec,Factory())
        self.registry.register_typed(replace(spec,version='1.2.0',vehicle_types=frozenset({'copter'})),Factory())
        self.assertEqual(self.registry.resolve_typed('a').spec.version,'1.2.0')
        self.assertEqual(self.registry.resolve_typed('a','1.0.0').spec.version,'1.0.0')
        self.assertEqual(len(self.registry.catalog(vehicle_kind='rover')),1)
        self.assertEqual(self.registry.metadata('a')['parameters']['properties']['count']['maximum'],10)


if __name__=='__main__':unittest.main()

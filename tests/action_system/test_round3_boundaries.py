"""Independent vehicle and external responsibilities, including terminal ticks."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vehicle_autonomy.actions.common.standard import Empty
from vehicle_autonomy.actions.external.clients import ApiJob
from vehicle_autonomy.actions.external.native import NativeJob
from vehicle_autonomy.contracts.action import ActionKind,ActionResource,ActionSafety
from vehicle_autonomy.contracts.action_ports import ActionAdmissionRejected
from vehicle_autonomy.contracts.decision import ActionSpec,ActionDecision,ActionOutcome,ExitDecision
from vehicle_autonomy.contracts.effects.vehicle import ArmEffect
from vehicle_autonomy.engine.action.registry import ActionRegistry
from vehicle_autonomy.engine.action.runtime import ActionRuntime
from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry
from vehicle_autonomy.engine.action.resources import PersistentResources
from tests.action_system.test_runtime import Clock,Driver
from tests.action_system.test_persistent_resources import isolated_test_registry,initialize_test_store


class Round3LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);isolated_test_registry(self,self.root/'registry')
        self.store=initialize_test_store(self.root/'ledger');self.clock=Clock();self.driver=Driver()

    def build(self,*,emit=False,timeout=False,managed=True):
        jobs=[];store=self.store
        class Job:
            state='RUNNING'
            def poll(self):return {'state':self.state}
            def cancel(self):pass
            def close(self):pass
        class Instance:
            sent=False
            def tick(self,w):
                effects=(ArmEffect(),) if emit and not self.sent else ()
                self.sent=True;return ActionDecision(ActionOutcome.RUNNING,effects)
            def exit(self,*_):
                if timeout:return ExitDecision(False)
                raise RuntimeError('external cancellation response lost')
        class Factory:
            resource_store=store
            def start(self,*_):raise AssertionError('context required')
            def start_with_context(self,p,w,ctx):
                job=Job();ctx.external_jobs.start(lambda:job);jobs.append(job);return Instance()
        spec=ActionSpec('mixed',Empty,kind=ActionKind.CONTINUOUS,effect_types=(ArmEffect,),
            external_lifecycle='managed' if managed else 'opaque',resources=(ActionResource('vehicle.motion'),ActionResource('ai.inference')))
        reg=ActionRegistry();reg.register_typed(spec,Factory())
        rt=ActionRuntime(reg,{'v':self.driver},clock=self.clock)
        a=rt.submit('mixed','v',allow_send=True);rt.tick()
        self.assertEqual(rt.view(a['id'])['state'],'RUNNING')
        return rt,a,jobs

    def exercise(self,*,emit=False,timeout=False):
        rt,a,jobs=self.build(emit=emit,timeout=timeout)
        rt.cancel(a['id']);rt.tick()
        if timeout:self.clock.advance(9)
        for _ in range(12):rt.tick()
        value=rt.view(a['id'])
        self.assertEqual(value['state'],'UNKNOWN');self.assertFalse(value['safety']['release_safe'])
        self.assertEqual(len(self.driver.writes),int(emit))
        self.assertEqual({r['name'] for r in rt.resource_view()},{'vehicle.motion','ai.inference'})
        self.assertEqual(rt.submit('mixed','v',allow_send=True)['state'],'REJECTED')
        self.assertEqual(len(jobs),1)
        jobs[0].state='SUCCEEDED'
        for _ in range(3):rt.tick()
        self.assertEqual(rt.view(a['id'])['state'],'UNKNOWN')
        self.assertTrue(rt.view(a['id'])['safety']['release_safe']);self.assertEqual(rt.resource_view(),[])
        b=rt.submit('mixed','v',allow_send=True);rt.tick()
        self.assertEqual(rt.view(b['id'])['state'],'RUNNING');self.assertEqual(len(jobs),2)

    def test_declared_but_unsent_vehicle_effect_and_external_exit_exception(self):self.exercise()
    def test_actual_typed_effect_and_external_exit_exception(self):self.exercise(emit=True)
    def test_exit_timeout_external_responsibility_survives_vehicle_guard(self):self.exercise(timeout=True)
    def test_both_responsibilities_exit_timeout(self):self.exercise(emit=True,timeout=True)

    def test_opaque_external_contract_is_not_inferred_from_effect_types(self):
        rt,a,jobs=self.build(managed=False);rt.cancel(a['id'])
        for _ in range(12):rt.tick()
        self.assertEqual(rt.view(a['id'])['state'],'UNKNOWN');self.assertTrue(rt.resource_view())
        jobs[0].state='SUCCEEDED'
        for _ in range(3):rt.tick()
        self.assertFalse(rt.view(a['id'])['safety']['release_safe'])  # opaque callbacks need their own proof
        self.assertTrue(rt.reconcile_external(a['id'],lambda r:ActionSafety(True,evidence={
            'owner':r['owner'],'scope':r['scope'],'terminal':True,'verification':'trusted complete external inventory'})))
        self.assertTrue(rt.view(a['id'])['safety']['release_safe'])

    def test_typed_only_and_query_contracts_cannot_start_unregistered_jobs(self):
        for kind in (ActionKind.GOAL,ActionKind.QUERY):
            class Factory:
                resource_store=self.store
                def start(self,*_):NativeJob(lambda *args:None)
            reg=ActionRegistry();reg.register_typed(ActionSpec('forbidden',Empty,kind=kind,external_lifecycle='typed_only'),Factory())
            rt=ActionRuntime(reg,{'v':self.driver},clock=Clock());a=rt.submit('forbidden','v')
            for _ in range(5):rt.tick()
            self.assertEqual(rt.view(a['id'])['state'],'FAILED');self.assertEqual(rt.resource_view(),[])
        with self.assertRaises(ActionAdmissionRejected):NativeJob(lambda *args:None)

    def test_captured_job_port_cannot_start_work_after_logical_terminal_or_release(self):
        rt,a,jobs=self.build();rt.cancel(a['id'])
        for _ in range(6):rt.tick()
        port=rt._records[a['id']].external;started=[]
        with self.assertRaises(ActionAdmissionRejected),port.callback():port.start(lambda:started.append(True))
        jobs[0].state='SUCCEEDED'
        for _ in range(3):rt.tick()
        self.assertEqual(rt.resource_view(),[])
        with self.assertRaises(ActionAdmissionRejected),port.callback():port.start(lambda:started.append(True))
        self.assertEqual(started,[])


class Round3IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);isolated_test_registry(self,self.root/'registry')
        self.store=initialize_test_store(self.root/'one')

    def test_ordinary_environment_and_scope_cannot_select_a_second_registry(self):
        expected=ProviderRegistry().root
        with patch.dict(os.environ,{'VAF_PROVIDER_REGISTRY':str(self.root/'alternate'),'XDG_STATE_HOME':str(self.root/'other')}):
            self.assertEqual(ProviderRegistry().root,expected)
            with self.assertRaises(ValueError):PersistentResources(self.root/'one','new-identity').records()

    def test_truthful_second_empty_initialization_cannot_create_a_second_ledger(self):
        binding=self.store.binding()
        with self.assertRaises(ValueError):PersistentResources.initialize(self.root/'two',lambda:ActionSafety(True,evidence={
            **binding,'quiescent':True}),scope='alternate')
        self.assertFalse((self.root/'two').exists())
        with self.assertRaises(ValueError):PersistentResources(self.root/'one','alternate').records()

    def test_identity_state_missing_corrupt_truncated_and_lock_missing_fail_closed(self):
        registry=ProviderRegistry();path=registry.root/'bindings.json';good=path.read_bytes()
        for raw in (b'',b'35',good[:40],b'{"bindings":[]}'):
            path.write_bytes(raw)
            with self.assertRaises((ValueError,OSError)):self.store.records()
        path.write_bytes(good);path.unlink()
        with self.assertRaises((ValueError,OSError)):self.store.records()
        path.write_bytes(good);path.chmod(0o600);(registry.root/'registry.lock').unlink()
        with self.assertRaises((ValueError,OSError)):self.store.records()

    def test_short_registry_registration_never_creates_an_alternate_ledger(self):
        original=os.write
        with patch('vehicle_autonomy.engine.action.durable.os.write',side_effect=lambda fd,data:original(fd,data[:2])):
            with self.assertRaises(OSError):initialize_test_store(self.root/'new-provider')
        self.assertFalse((self.root/'new-provider').exists());self.assertEqual(self.store.records(),[])
        self.assertEqual(initialize_test_store(self.root/'new-provider').records(),[])

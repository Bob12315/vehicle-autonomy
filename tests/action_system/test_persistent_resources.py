"""Cross-runtime exclusion, damaged storage, and evidence-based reconciliation."""
from pathlib import Path
import os
import multiprocessing
import shutil
import tempfile
import unittest
from unittest.mock import patch

from vehicle_autonomy.contracts.action import ActionResource,ActionSafety,ResourceMode
from vehicle_autonomy.engine.action.resources import ActionResources,PersistentResources
from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry


def isolated_test_registry(case,directory):
    location=patch.object(ProviderRegistry,'_root',directory)
    location.start();case.addCleanup(location.stop);ProviderRegistry.initialize()


def initialize_test_store(root):
    return PersistentResources.initialize(root,lambda:ActionSafety(True,evidence={
        'quiescent':True,'provider_epoch':str(root),'provider_id':str(root),'resource_id':'jobs','protocol':'native','locator':str(root)}))


def compete(root,barrier,results,name):
    resources=ActionResources({'external':PersistentResources(root)})
    barrier.wait(timeout=3)
    results.put(resources.acquire(name,'external',(ActionResource('ai.inference'),),persistent=True))


class PersistentResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        isolated_test_registry(self,Path(self.temp.name)/'provider-registry')
        self.root=Path(self.temp.name)/'state';self.store=initialize_test_store(self.root)
        self.a=ActionResources({'a':self.store});self.b=ActionResources({'alias':PersistentResources(self.root)})
        self.resource=(ActionResource('ai.inference'),)
    def acquire(self,resources,owner='old',target='a'):
        return resources.acquire(owner,target,self.resource,persistent=True,metadata={'action':'external_job'})
    @staticmethod
    def proof(r):return ActionSafety(True,evidence={'owner':r['owner'],'scope':r['scope'],'terminal':True,'verification':'test-only provider terminal'})

    def test_old_and_new_runtime_and_target_alias_cannot_overlap(self):
        self.assertTrue(self.acquire(self.a));self.a.started('old')
        self.a.describe('old',{'protocol':'http_job','endpoint':'http://127.0.0.1:1234','job_id':'trustedJob'})
        self.assertFalse(self.acquire(self.b,'new','alias'))
        self.a.retain('old','lost response')
        for _ in range(5):self.assertFalse(self.acquire(self.b,'new','alias'))
        record=self.store.records()[0]
        self.assertEqual(record['descriptor']['job_id'],'trustedJob')
        self.assertEqual(record['phase'],'UNKNOWN')
        self.assertEqual(record['metadata']['action'],'external_job')
        self.assertTrue(self.b.view()[0]['retained'])

    def test_plain_release_or_new_identity_cannot_erase_uncertain_owner(self):
        self.acquire(self.a);self.a.started('old');self.a.retain('old','uncertain')
        with self.assertRaises(ValueError):self.a.release('old')
        with self.assertRaises(ValueError):self.store.release('old',self.b.runtime_id,safety=ActionSafety(True))
        self.b.release('old')  # No in-memory claim is not authority over the ledger.
        self.assertEqual(len(self.store.records()),1)
        self.assertFalse(self.acquire(self.b,'old','alias'))

    def test_provider_terminal_evidence_restores_normal_reuse(self):
        self.acquire(self.a);self.a.started('old');self.a.retain('old','cancel unconfirmed')
        self.assertFalse(self.b.reconcile('old',lambda r:ActionSafety(False)))
        self.assertFalse(self.b.reconcile('old',lambda r:ActionSafety(True)))
        self.assertFalse(self.acquire(self.b,'new','alias'))
        self.assertFalse(self.b.reconcile('old',self.proof))  # The old coordinator is still alive.
        self.assertTrue(self.a.reconcile('old',self.proof))
        self.assertTrue(self.acquire(self.b,'new','alias'))
        self.b.started('new');self.b.release('new',safety=ActionSafety(True))
        self.assertEqual(self.store.records(),[])

    def test_query_shared_read_has_no_persistent_side_effect_reservation(self):
        self.acquire(self.a);self.a.started('old');self.a.retain('old','service still running')
        self.assertTrue(self.b.acquire('query','alias',(ActionResource('state',ResourceMode.SHARED),)))
        self.b.release('query',no_effects=True)
        self.assertFalse(self.acquire(self.b,'new','alias'))
        self.assertEqual(len(self.store.records()),1)

    def test_partial_write_before_admission_never_publishes_a_reservation(self):
        self.store.records()  # Complete initial durable namespace creation.
        original=os.write
        with patch('vehicle_autonomy.engine.action.durable.os.write',side_effect=lambda fd,data:original(fd,data[:2])):
            with self.assertRaises(OSError):self.acquire(self.a)
        self.assertEqual(self.store.records(),[])
        self.assertTrue(self.acquire(self.b,'valid','alias'))

    def test_corrupt_missing_lock_or_claim_file_does_not_initialize_as_free(self):
        self.acquire(self.a);good=(self.root/'claims.json').read_bytes()
        for content in (b'',b'35',good[:20],b'{"claims":[]}'):
            (self.root/'claims.json').write_bytes(content)
            with self.assertRaises((ValueError,OSError)):self.acquire(self.b,'new','alias')
        (self.root/'claims.json').write_bytes(good)
        (self.root/'claims.json').unlink()
        with self.assertRaises((ValueError,OSError)):self.acquire(self.b,'new','alias')
        (self.root/'claims.json').write_bytes(good);(self.root/'claims.json').chmod(0o600)
        (self.root/'owner.lock').unlink()
        with self.assertRaises((ValueError,OSError)):self.acquire(self.b,'new','alias')

    def test_removing_state_directory_is_detected_by_the_deployment_anchor(self):
        self.acquire(self.a);shutil.rmtree(self.root)
        with self.assertRaises((ValueError,OSError)):self.acquire(self.b,'new','alias')

    def test_completely_missing_namespace_cannot_be_treated_as_a_fresh_deployment(self):
        missing=Path(self.temp.name)/'not-initialized'
        with self.assertRaises((OSError,ValueError)):PersistentResources(missing).records()
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):PersistentResources.initialize(missing,lambda:ActionSafety(True))
        with self.assertRaises(ValueError):initialize_test_store(self.root)

    def test_write_exception_during_retain_keeps_the_prior_durable_claim(self):
        self.acquire(self.a);self.a.started('old')
        with patch('vehicle_autonomy.engine.action.durable.os.write',side_effect=OSError('disk unavailable')):
            self.a.retain('old','remote uncertain')
        self.assertTrue(self.a.view()[0]['retained'])
        self.assertFalse(self.acquire(self.b,'new','alias'))
        self.assertTrue(self.a.reconcile('old',self.proof))

    def test_two_processes_competing_at_the_same_instant_get_one_reservation(self):
        self.store.records()
        context=multiprocessing.get_context('fork');barrier=context.Barrier(2);results=context.Queue()
        children=[context.Process(target=compete,args=(self.root,barrier,results,name)) for name in ('first','second')]
        for child in children:child.start()
        for child in children:child.join(4);self.assertEqual(child.exitcode,0)
        self.assertEqual(sorted([results.get(timeout=1),results.get(timeout=1)]),[False,True])
        self.assertEqual(len(self.store.records()),1)
        results.close();results.join_thread()
